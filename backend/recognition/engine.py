"""Only live single-face inputs. Frozen ArcFace, roster templates, optional trained classifier."""
import io
import numpy as np
from PIL import Image, UnidentifiedImageError

class RecognitionRejected(Exception): pass

def validate_image(data):
    if not data or len(data) > 5 * 1024 * 1024: raise RecognitionRejected('image_size')
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in ('JPEG', 'PNG') or img.width * img.height > 4_000_000:
                raise RecognitionRejected('image_format_or_dimensions')
            img.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise RecognitionRejected('invalid_image') from exc

def normalize(vector):
    arr = np.asarray(vector, dtype=np.float64)
    if arr.shape != (512,) or not np.isfinite(arr).all() or np.linalg.norm(arr) < 1e-10:
        raise RecognitionRejected('invalid_embedding')
    return arr / np.linalg.norm(arr)

def extract_embedding(data):
    validate_image(data)
    import cv2
    from deepface import DeepFace
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None: raise RecognitionRejected('invalid_image')
    try:
        faces = DeepFace.extract_faces(img_path=image, detector_backend='opencv', enforce_detection=True,
                                       align=True, anti_spoofing=True)
    except ValueError as exc:
        if 'Face could not be detected' in str(exc):
            raise RecognitionRejected('no_face_detected') from exc
        raise
    if len(faces) != 1: raise RecognitionRejected('exactly_one_face_required')
    face = faces[0]
    if face.get('is_real') is not True: raise RecognitionRejected('liveness_failed')
    area = face['facial_area']
    if min(area['w'], area['h']) < 80: raise RecognitionRejected('face_too_small')
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    crop = gray[max(0, area['y']):area['y'] + area['h'], max(0, area['x']):area['x'] + area['w']]
    if crop.size == 0 or crop.mean() < 35 or crop.mean() > 235 or cv2.Laplacian(crop, cv2.CV_64F).var() < 15:
        raise RecognitionRejected('poor_lighting_or_blur')
    # DeepFace extraction returns aligned RGB floats; skip detection only for this verified crop.
    aligned = (face['face'] * 255).clip(0, 255).astype('uint8')[:, :, ::-1]
    representations = DeepFace.represent(img_path=aligned, model_name='ArcFace', detector_backend='skip',
                                        enforce_detection=False, normalization='ArcFace')
    if len(representations) != 1: raise RecognitionRejected('representation_failed')
    return normalize(representations[0]['embedding'])

def match_embedding(vector, roster_ids, threshold, margin, require_classifier=True):
    from django.utils import timezone
    from attendance.models import BiometricSample
    from .storage import decode_embedding
    roster_ids = set(roster_ids)
    samples = BiometricSample.objects.filter(student_id__in=roster_ids, student__active=True,
        student__consent_at__isnull=False, expires_at__gt=timezone.now(), model='ArcFace').defer('photo_ciphertext')
    vector = normalize(vector)
    scores = {}
    for sample in samples:
        score = float(vector @ normalize(decode_embedding(sample.embedding_ciphertext)))
        scores[sample.student_id] = max(score, scores.get(sample.student_id, -1.0))
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    if not ranked: raise RecognitionRejected('no_enrolled_roster')
    candidate, score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else -1.0
    if score < threshold: raise RecognitionRejected('unknown_face')
    if score - second < margin: raise RecognitionRejected('uncertain_match')
    if require_classifier:
        from .classifier import predict
        # Do not remap an out-of-roster global prediction to a roster student.
        predicted = predict(vector)
        if predicted not in roster_ids: raise RecognitionRejected('classifier_outside_roster')
        if predicted != candidate: raise RecognitionRejected('classifier_template_disagreement')
    return candidate, score
