"""Actionable API failures; log correlation metadata only, never photos, tokens or embeddings."""
import logging
import uuid
from cryptography.fernet import InvalidToken
from django.core.exceptions import RequestDataTooBig
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger('attendance.pipeline')

MESSAGES = {
    'ai_dependencies_missing': ('Facial recognition dependencies are missing.', 'Install backend/requirements-ai.txt in both backend and worker runtimes, then restart them.'),
    'ai_runtime_incompatible': ('Facial recognition libraries could not initialize.', 'Use Python 3.11 and the pinned AI dependencies; restart backend and worker after installing.'),
    'biometric_key_invalid': ('Biometric encryption is not configured correctly.', 'Set BIOMETRIC_KEY to a valid Fernet key. Restore the existing key for stored data; do not replace it with a new key.'),
    'biometric_key_mismatch': ('Stored biometric data could not be decrypted.', 'Restore the BIOMETRIC_KEY used during enrollment in both backend and worker environments.'),
    'weights_or_storage_unavailable': ('Model weights or private storage are unavailable.', 'Check model download connectivity, available disk space and private-storage permissions; retry after correcting them.'),
    'recognition_unavailable': ('The recognition pipeline failed closed.', 'Check the backend/worker log using the error ID; verify AI dependencies, weights and encryption configuration.'),
    'queue_unavailable': ('The recognition queue is unavailable.', 'Start Redis and the Celery worker, verify CELERY_BROKER_URL, then capture a new frame.'),
}
REJECTIONS = {
    'image_size': 'Use a JPEG/PNG smaller than 5 MB.',
    'invalid_image': 'Upload a valid, uncorrupted JPEG/PNG image.',
    'image_format_or_dimensions': 'Use JPEG/PNG with no more than 4 million pixels.',
    'no_face_detected': 'Retake the photo with one visible face centered in good lighting.',
    'exactly_one_face_required': 'Retake the photo with exactly one face visible.',
    'liveness_failed': 'Use a live selfie; printed photos and screen replays are rejected.',
    'face_too_small': 'Move closer so the face is at least 80 pixels wide and high.',
    'poor_lighting_or_blur': 'Use front lighting, hold still and retake a sharp selfie.',
    'classifier_not_trained': 'Ask an administrator to train the classifier after enrolling at least two students with three independent capture groups each.',
    'classifier_stale_retrain_required': 'Ask an administrator to retrain on the current enrollment embeddings.',
    'no_enrolled_roster': 'Enroll consented students from this section before recognition.',
    'unknown_face': 'No enrolled roster match passed the threshold. Retake the frame or use an audited manual check-in.',
    'uncertain_match': 'The match is ambiguous. Retake the frame or use an audited manual check-in.',
}

def diagnose(exc, stage):
    chain = []
    current = exc
    while current is not None and len(chain) < 8:
        chain.append(current)
        current = current.__cause__ or current.__context__
    if any(isinstance(e, ModuleNotFoundError) for e in chain): code = 'ai_dependencies_missing'
    elif any(isinstance(e, InvalidToken) for e in chain): code = 'biometric_key_mismatch'
    elif any(isinstance(e, ImportError) for e in chain): code = 'ai_runtime_incompatible'
    elif stage == 'encryption' and isinstance(exc, ValueError): code = 'biometric_key_invalid'
    elif isinstance(exc, OSError): code = 'weights_or_storage_unavailable'
    else: code = 'recognition_unavailable'
    error_id = uuid.uuid4().hex[:12]
    logger.error('pipeline_failure error_id=%s stage=%s code=%s exception_type=%s', error_id, stage, code, type(exc).__name__)
    detail, action = MESSAGES[code]
    return {'detail': detail, 'code': code, 'action': action, 'error_id': error_id}

def failure_response(exc, stage): return Response(diagnose(exc, stage), status=503)

def exception_handler(exc, context):
    if isinstance(exc, RequestDataTooBig):
        return Response({'detail': 'Photo upload exceeds the private-memory limit.', 'code': 'upload_too_large',
                         'action': 'Use at most 5 MB per file and 20 MB total; upload fewer or smaller photos.'}, status=413)
    return drf_exception_handler(exc, context)
