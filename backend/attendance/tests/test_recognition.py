import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch
import numpy as np
from django.test import TestCase, override_settings
from django.utils import timezone
from attendance.models import Student, Department, BiometricSample
from recognition.engine import match_embedding, RecognitionRejected, normalize
from recognition.storage import encode_embedding, encrypt
from recognition.classifier import train, load

class RecognitionTests(TestCase):
    """Synthetic vectors test mechanics only; these metrics are NOT real face recognition metrics."""
    def setUp(self):
        department = Department.objects.create(name='CS')
        self.a = Student.objects.create(name='A', registration_number='A', department=department, consent_at=timezone.now())
        self.b = Student.objects.create(name='B', registration_number='B', department=department, consent_at=timezone.now())
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(PRIVATE_STORAGE=self.temp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.va, self.vb = np.eye(512)[0], np.eye(512)[1]
    def sample(self, student, vector, group=None):
        return BiometricSample.objects.create(student=student, capture_group=group or uuid.uuid4(),
            embedding_ciphertext=encode_embedding(vector.tolist()), photo_ciphertext=encrypt(b'synthetic'),
            photo_sha256=uuid.uuid4().hex*2, expires_at=timezone.now()+timedelta(days=5))
    def test_scoping_unknown_margin_and_classifier_agreement(self):
        self.sample(self.a, self.va)
        self.sample(self.b, self.vb)
        self.assertEqual(match_embedding(self.va, [self.a.pk], .65, .08, False)[0], self.a.pk)
        with self.assertRaisesMessage(RecognitionRejected, 'unknown_face'): match_embedding(self.vb, [self.a.pk], .65, .08, False)
        with self.assertRaisesMessage(RecognitionRejected, 'uncertain_match'): match_embedding(normalize(self.va+self.vb), [self.a.pk,self.b.pk], .65, .08, False)
        with patch('recognition.classifier.predict', return_value=self.b.pk):
            with self.assertRaisesMessage(RecognitionRejected, 'classifier_outside_roster'): match_embedding(self.va, [self.a.pk], .65, .08, True)
            with self.assertRaisesMessage(RecognitionRejected, 'classifier_template_disagreement'): match_embedding(self.va, [self.a.pk,self.b.pk], .65, .08, True)
    def test_group_split_metrics_and_stale_model(self):
        for _ in range(3): self.sample(self.a,self.va); self.sample(self.b,self.vb)
        report = train()
        self.assertEqual(report['train_samples'], 4)
        self.assertEqual(report['heldout_samples'], 2)
        self.assertEqual(report['confusion_matrix'], [[1,0],[0,1]])
        self.assertEqual(report['accuracy'], 1.0)
        self.assertEqual(match_embedding(self.va, [self.a.pk], .65, .08, True)[0], self.a.pk)
        self.sample(self.a, self.va)
        with self.assertRaisesMessage(RecognitionRejected, 'classifier_stale_retrain_required'): load()
    def test_require_multiple_independent_capture_groups(self):
        for student, vector in [(self.a,self.va),(self.b,self.vb)]:
            group = uuid.uuid4()
            for _ in range(4): self.sample(student, vector, group)
        with self.assertRaisesMessage(ValueError, 'independent capture groups'): train()
    def test_expired_and_revoked_consent_rejected(self):
        sample = self.sample(self.a, self.va)
        sample.expires_at = timezone.now()-timedelta(days=1)
        sample.save()
        with self.assertRaisesMessage(RecognitionRejected, 'no_enrolled_roster'): match_embedding(self.va,[self.a.pk],.65,.08,False)
        self.sample(self.b, self.vb)
        self.b.consent_at = None
        self.b.save()
        with self.assertRaisesMessage(RecognitionRejected, 'no_enrolled_roster'): match_embedding(self.vb,[self.b.pk],.65,.08,False)
    def test_invalid_embedding(self):
        for vector in [[1], [0]*512, [float('nan')]*512]:
            with self.assertRaises(RecognitionRejected): normalize(vector)
