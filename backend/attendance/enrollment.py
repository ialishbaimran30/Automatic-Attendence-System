import hashlib
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import BiometricSample, Student, EnrollmentLink
from .services import token_hash, audit
from recognition.engine import extract_embedding, RecognitionRejected
from recognition.storage import cipher, encrypt, encode_embedding, invalidate_classifier
from .errors import diagnose, REJECTIONS

class EnrollmentUnavailable(Exception):
    def __init__(self, payload):
        self.payload = payload
        super().__init__(payload['code'])

CONSENT_VERSION = 'attendance-biometric-v1'

def prepare_samples(photos):
    photos = list(photos)
    if not 1 <= len(photos) <= 10: raise ValidationError({'detail': 'Provide 1 to 10 photos using the multipart field photos.', 'code': 'photos_required'})
    try: cipher()
    except Exception as exc: raise EnrollmentUnavailable(diagnose(exc, 'encryption')) from exc
    prepared = []
    try:
        for index, photo in enumerate(photos, 1):
            data = photo.read(5 * 1024 * 1024 + 1)
            vector = extract_embedding(data)
            prepared.append((data, vector.tolist(), hashlib.sha256(data).hexdigest()))
    except RecognitionRejected as exc:
        code = str(exc)
        raise ValidationError({'detail': f'Photo {index} rejected: {code}.', 'code': code,
                               'action': REJECTIONS.get(code, 'Retake a clear live selfie with one face.')}) from exc
    except Exception as exc:
        raise EnrollmentUnavailable(diagnose(exc, 'embedding')) from exc
    if len({p[2] for p in prepared}) != len(prepared): raise ValidationError('Duplicate photo in upload.')
    return prepared

def save_samples(student, prepared, group):
    now = timezone.now()
    if student.biometrics.filter(photo_sha256__in=[p[2] for p in prepared]).exists():
        raise ValidationError('This photo was already enrolled; capture an independent sample.')
    if student.biometrics.count() + len(prepared) > 30: raise ValidationError('Maximum 30 samples per student; purge older data first.')
    rows = BiometricSample.objects.bulk_create([BiometricSample(student=student, photo_ciphertext=encrypt(data),
        embedding_ciphertext=encode_embedding(vector), photo_sha256=digest, capture_group=group,
        expires_at=now + timedelta(days=settings.BIOMETRIC_RETENTION_DAYS)) for data, vector, digest in prepared])
    invalidate_classifier()
    return rows

def consume_link(token, photos, consent):
    if consent != 'true': raise ValidationError('Explicit biometric consent is required.')
    link = EnrollmentLink.objects.filter(token_hash=token_hash(token), used_at__isnull=True, expires_at__gt=timezone.now()).first()
    if not link: raise ValidationError('Link is expired, used, or invalid.')
    prepared = prepare_samples(photos)
    with transaction.atomic():
        link = EnrollmentLink.objects.select_for_update().get(pk=link.pk)
        if link.used_at or link.expires_at <= timezone.now(): raise ValidationError('Link is expired or used.')
        student = Student.objects.select_for_update().get(pk=link.student_id, active=True)
        save_samples(student, prepared, link.capture_group)
        student.consent_at, student.consent_version = timezone.now(), CONSENT_VERSION
        student.save(update_fields=['consent_at', 'consent_version'])
        link.used_at = timezone.now()
        link.save(update_fields=['used_at'])
        audit('enrollment.link_consumed', link.issued_by, student_id=student.pk, count=len(prepared), consent_version=CONSENT_VERSION)
