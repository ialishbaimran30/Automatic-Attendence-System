"""Logistic regression on frozen ArcFace embeddings; group-disjoint holdout."""
import hashlib
import io
import json
import numpy as np
import joblib
from django.utils import timezone
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, confusion_matrix
from attendance.models import BiometricSample
from .storage import decode_embedding, encrypt, decrypt, private_path
from .engine import normalize, RecognitionRejected

def samples():
    return list(BiometricSample.objects.filter(student__active=True, student__consent_at__isnull=False,
        expires_at__gt=timezone.now(), model='ArcFace').defer('photo_ciphertext').order_by('student_id', 'created_at', 'id'))

def training_status():
    counts = {}
    for row in samples():
        item = counts.setdefault(row.student_id, {'student': row.student_id, 'sample_count': 0, 'groups': set()})
        item['sample_count'] += 1
        item['groups'].add(row.capture_group)
    students = [{'student': item['student'], 'sample_count': item['sample_count'], 'capture_groups': len(item['groups']),
                 'needed_groups': max(0, 3-len(item['groups']))} for item in counts.values()]
    ready = len(students) >= 2 and all(s['needed_groups'] == 0 for s in students)
    return {'ready': ready, 'student_count': len(students), 'students': students,
            'detail': 'Ready to train on stored ArcFace embeddings.' if ready else 'Insufficient training data: at least two students and three independent capture groups per enrolled student are required.'}

def fingerprint(rows):
    return hashlib.sha256('|'.join(f'{s.pk}:{s.student_id}:{s.capture_group}:{s.photo_sha256}' for s in rows).encode()).hexdigest()

def train():
    rows = samples()
    labels = sorted({s.student_id for s in rows})
    if len(labels) < 2: raise ValueError('At least two consented enrolled students required.')
    training, heldout = [], []
    for student_id in labels:
        student_rows = [s for s in rows if s.student_id == student_id]
        groups = list(dict.fromkeys(str(s.capture_group) for s in student_rows))
        if len(groups) < 3:
            raise ValueError(f'Student {student_id} needs at least 3 independent capture groups (2 train, 1 held out).')
        last_group = groups[-1]
        training.extend(s for s in student_rows if str(s.capture_group) != last_group)
        heldout.extend(s for s in student_rows if str(s.capture_group) == last_group)
    # No capture group may appear on both sides, including multi-student bulk captures.
    overlap = {s.capture_group for s in training} & {s.capture_group for s in heldout}
    if overlap: raise ValueError('Capture groups cross students inconsistently. Use separate capture events for the evaluation cohort.')
    x_train = np.vstack([normalize(decode_embedding(s.embedding_ciphertext)) for s in training])
    y_train = [s.student_id for s in training]
    x_test = np.vstack([normalize(decode_embedding(s.embedding_ciphertext)) for s in heldout])
    y_test = [s.student_id for s in heldout]
    model = LogisticRegression(C=10, max_iter=2000, random_state=42, class_weight='balanced')
    model.fit(x_train, y_train)
    predicted = model.predict(x_test)
    precision, recall, f1, _ = precision_recall_fscore_support(y_test, predicted, labels=labels, average='macro', zero_division=0)
    per_p, per_r, per_f, support = precision_recall_fscore_support(y_test, predicted, labels=labels, zero_division=0)
    report = {'accuracy': float(accuracy_score(y_test, predicted)), 'precision_macro': float(precision),
              'recall_macro': float(recall), 'f1_macro': float(f1), 'labels_student_ids': labels,
              'confusion_matrix': confusion_matrix(y_test, predicted, labels=labels).tolist(),
              'per_student': [{'student_id': label, 'precision': float(p), 'recall': float(r), 'f1': float(f), 'support': int(n)}
                              for label, p, r, f, n in zip(labels, per_p, per_r, per_f, support)],
              'train_samples': len(training), 'heldout_samples': len(heldout),
              'split': 'latest independent capture group per student; no group overlap',
              'trained_at': timezone.now().isoformat(), 'fingerprint': fingerprint(rows),
              'limitations': 'Closed-set held-out metrics; evaluate unknown-face rejection and spoofing separately. Small cohorts are not deployment evidence.'}
    buffer = io.BytesIO()
    joblib.dump({'model': model, 'report': report}, buffer)
    path = private_path('classifier.fernet')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_bytes(encrypt(buffer.getvalue()))
    temp.replace(path)
    return report

def load():
    path = private_path('classifier.fernet')
    if not path.exists(): raise RecognitionRejected('classifier_not_trained')
    # Only deserialize our authenticated, encrypted artifact. Never accept user-supplied pickles.
    artifact = joblib.load(io.BytesIO(decrypt(path.read_bytes())))
    if artifact['report']['fingerprint'] != fingerprint(samples()):
        raise RecognitionRejected('classifier_stale_retrain_required')
    return artifact

def predict(vector): return int(load()['model'].predict([normalize(vector)])[0])
