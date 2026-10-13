from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import RecognitionJob, AttendanceSession, BiometricSample, EnrollmentLink, CaptureGrant
from .services import audit
from .errors import diagnose
from recognition.storage import read_private, delete_private, private_path, invalidate_classifier
from recognition.engine import extract_embedding, match_embedding, RecognitionRejected

@shared_task
def recognize(job_id):
    # Lock the session before the job everywhere to avoid confirmation/closure deadlocks.
    initial = RecognitionJob.objects.get(pk=job_id)
    frame = initial.frame_path
    with transaction.atomic():
        session = AttendanceSession.objects.select_for_update().get(pk=initial.session_id)
        job = RecognitionJob.objects.select_for_update().get(pk=job_id)
        if job.status != 'queued': return
        if session.closed_at or job.expires_at <= timezone.now():
            job.status, job.reason = 'rejected', 'session_closed_or_job_expired'
            job.save(update_fields=['status', 'reason'])
            delete_private(frame)
            return
        job.status = 'processing'
        job.save(update_fields=['status'])
    candidate, score, status, reason = None, None, 'error', 'recognition_unavailable'
    try:
        vector = extract_embedding(read_private(frame))
        candidate, score = match_embedding(vector, session.roster.values_list('student_id', flat=True),
            session.match_threshold, session.match_margin, settings.REQUIRE_CLASSIFIER)
        status, reason = 'review', ''
    except RecognitionRejected as exc:
        status, reason = 'rejected', str(exc)
    except Exception as exc:
        # No stack trace/biometric payload in API. Fail closed on missing weights, bad key, worker errors.
        payload = diagnose(exc, 'recognition')
        status, reason = 'error', payload['code']
    finally:
        delete_private(frame)
    with transaction.atomic():
        session = AttendanceSession.objects.select_for_update().get(pk=initial.session_id)
        job = RecognitionJob.objects.select_for_update().get(pk=job_id)
        if job.status != 'processing': return
        if session.closed_at or job.expires_at <= timezone.now():
            candidate, score, status, reason = None, None, 'rejected', 'session_closed_or_job_expired'
        job.proposed_student_id, job.score, job.status, job.reason, job.frame_path = candidate, score, status, reason, ''
        job.save()
        if status != 'review':
            audit('recognition.rejected' if status == 'rejected' else 'recognition.error', job.requested_by,
                  session, job_id=str(job.id), reason=reason)

@shared_task
def purge_expired():
    import time
    from datetime import timedelta
    now = timezone.now()
    expired = RecognitionJob.objects.filter(status__in=['queued', 'processing', 'review'], expires_at__lte=now)
    for row in expired:
        with transaction.atomic():
            session = AttendanceSession.objects.select_for_update().get(pk=row.session_id)
            job = RecognitionJob.objects.select_for_update().get(pk=row.pk)
            if job.status not in ('queued', 'processing', 'review'): continue
            delete_private(job.frame_path)
            job.status, job.reason, job.frame_path, job.proposed_student_id, job.score = 'rejected', 'job_expired', '', None, None
            job.save()
            audit('recognition.expired', job.requested_by, session, job_id=str(job.id))
    ids = list(BiometricSample.objects.filter(expires_at__lte=now).values_list('student_id', flat=True).distinct())
    count, _ = BiometricSample.objects.filter(expires_at__lte=now).delete()
    if count:
        invalidate_classifier()
        audit('biometrics.retention_purge', student_ids=ids, count=count)
    EnrollmentLink.objects.filter(expires_at__lt=now - timedelta(days=7)).delete()
    CaptureGrant.objects.filter(expires_at__lt=now - timedelta(days=1)).delete()
    root = private_path('frames')
    if root.exists():
        for path in root.glob('*.fernet'):
            if time.time() - path.stat().st_mtime > settings.FRAME_RETENTION_SECONDS:
                path.unlink(missing_ok=True)
