import io
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch
import numpy as np
from django.test import TestCase, override_settings
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from PIL import Image
from attendance.models import User, Department, Course, Section, Membership, Student, Schedule, AttendanceSession, AttendanceRecord, BiometricSample, EnrollmentLink, AuditLog
from attendance import services
from recognition.engine import match_embedding
from recognition.storage import decode_embedding, decrypt

def photo(colour):
    stream = io.BytesIO()
    Image.new('RGB', (120,120), colour).save(stream, format='JPEG')
    return SimpleUploadedFile('selfie.jpg', stream.getvalue(), content_type='image/jpeg')

class FocusedWorkflowTests(TestCase):
    """Real storage/sklearn/matcher/API; only ArcFace inference is replaced by synthetic vectors."""
    def setUp(self):
        self.teacher = User.objects.create_user('lecturer-one', password='separate-password-one', role='teacher')
        self.other = User.objects.create_user('lecturer-two', password='separate-password-two', role='teacher')
        self.admin = User.objects.create_user('administrator', role='admin')
        department = Department.objects.create(name='CS')
        course = Course.objects.create(department=department, code='AI', name='AI')
        self.section = Section.objects.create(course=course, name='A', semester='Fall')
        self.foreign = Section.objects.create(course=course, name='B', semester='Fall')
        self.section.teachers.add(self.teacher)
        self.foreign.teachers.add(self.other)
        self.a = Student.objects.create(name='A', registration_number='A', department=department)
        self.b = Student.objects.create(name='B', registration_number='B', department=department)
        for student in (self.a,self.b): Membership.objects.create(section=self.section, student=student)
        Membership.objects.create(section=self.foreign, student=self.a)
        self.client = APIClient()
        self.client.force_authenticate(self.teacher)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = override_settings(PRIVATE_STORAGE=self.temp.name, REQUIRE_CLASSIFIER=True)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.now = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
        self.clock = patch('django.utils.timezone.now', return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
    def config(self, section=None, **changes):
        data = {'class_date':self.now.date().isoformat(), 'start_time':'12:00', 'duration_minutes':60, 'grace_minutes':3}
        data.update(changes)
        return self.client.post(f'/api/sections/{(section or self.section).pk}/configure-class/', data)
    def enroll(self, student, vector, colour):
        with patch('attendance.enrollment.extract_embedding', return_value=vector):
            return self.client.post(f'/api/students/{student.pk}/bulk-enroll/', {'consent':'true','photos':photo(colour)}, format='multipart')

    def test_separate_cookie_accounts_and_teacher_class_scope(self):
        for user,password,section in [(self.teacher,'separate-password-one',self.section),(self.other,'separate-password-two',self.foreign)]:
            client = APIClient(enforce_csrf_checks=True)
            token = client.get('/api/auth/csrf/').data['csrfToken']
            self.assertEqual(client.post('/api/auth/login/', {'username':user.username,'password':password}, HTTP_X_CSRFTOKEN=token).status_code,200)
            self.assertEqual([s['id'] for s in client.get('/api/sections/').data],[section.pk])
        self.assertEqual(self.config(self.foreign).status_code,404)
        self.assertEqual(self.client.post('/api/schedules/',{}).status_code,403)
        self.assertEqual(self.client.patch(f'/api/sections/{self.section.pk}/', {'teachers':[self.other.pk]}).status_code,403)

    def test_configure_start_grace_snapshot_and_preserve_admin_schedule(self):
        original = Schedule.objects.create(section=self.section, weekday=self.now.weekday(), start_time='09:00', end_time='10:00',
            valid_from=self.now.date(), valid_until=self.now.date()+timedelta(days=30))
        config = self.config()
        self.assertEqual(config.status_code,201)
        original.refresh_from_db()
        self.assertEqual(str(original.start_time),'09:00:00')
        self.assertIsNone(original.grace_minutes)
        response = self.client.post(f'/api/sections/{self.section.pk}/start/',{'schedule':config.data['id']})
        self.assertEqual(response.status_code,201)
        session = AttendanceSession.objects.get(pk=response.data['id'])
        self.assertEqual(session.grace_minutes,3)
        self.assertEqual(session.scheduled_end-session.scheduled_start,timedelta(minutes=60))
        Schedule.objects.filter(pk=config.data['id']).update(grace_minutes=8)
        session.refresh_from_db()
        self.assertEqual(session.grace_minutes,3)
        self.assertEqual(services.status_at(session,self.now+timedelta(minutes=3)),'present')
        self.assertEqual(services.status_at(session,self.now+timedelta(minutes=3,seconds=1)),'late')
        self.assertTrue(AuditLog.objects.filter(event='class.configured',actor=self.teacher).exists())

    def test_schedule_validation_and_duplicate_occurrence_across_configs(self):
        for changes in [{'duration_minutes':0},{'duration_minutes':481},{'grace_minutes':61},
                        {'start_time':'23:50'},{'class_date':(self.now-timedelta(days=1)).date().isoformat()}]:
            self.assertEqual(self.config(**changes).status_code,400)
        first = self.config().data
        session = services.start_session(self.teacher,self.section,Schedule.objects.get(pk=first['id']))
        services.close_session(self.teacher,session.pk)
        second = self.config(grace_minutes=7).data
        self.assertEqual(self.client.post(f'/api/sections/{self.section.pk}/start/',{'schedule':second['id']}).status_code,400)

    def test_public_503_has_correlation_and_action_and_does_not_consume_link(self):
        link = EnrollmentLink.objects.create(student=self.a,issued_by=self.teacher,token_hash=services.token_hash('diagnostic-token'),expires_at=self.now+timedelta(minutes=30))
        public = APIClient()
        with patch('attendance.enrollment.extract_embedding',side_effect=ModuleNotFoundError("No module named 'cv2'")):
            with self.assertLogs('attendance.pipeline',level='ERROR') as logs:
                response = public.post('/api/enroll/',{'token':'diagnostic-token','consent':'true','photos':photo((100,120,130))},format='multipart')
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.data['code'],'ai_dependencies_missing')
        self.assertIn('requirements-ai.txt',response.data['action'])
        self.assertIn(response.data['error_id'],' '.join(logs.output))
        self.assertNotIn('diagnostic-token',' '.join(logs.output))
        link.refresh_from_db()
        self.assertIsNone(link.used_at)
        self.assertFalse(BiometricSample.objects.exists())
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_encryption_error_clear_and_missing_photos_400(self):
        with override_settings(BIOMETRIC_KEY='invalid'):
            response = self.enroll(self.a,np.eye(512)[0],(100,100,100))
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.data['code'],'biometric_key_invalid')
        self.assertEqual(self.client.post(f'/api/students/{self.a.pk}/bulk-enroll/',{'consent':'true'}).status_code,400)

    def test_upload_stored_embeddings_train_match_confirm_and_reuse_across_sections(self):
        self.client.force_authenticate(self.admin)
        before = self.client.get('/api/classifier/status/').data
        self.assertFalse(before['ready'])
        self.assertIn('Insufficient training data',before['detail'])
        self.assertEqual(self.client.post('/api/classifier/',{}).status_code,409)
        self.client.force_authenticate(self.teacher)
        # Separate enrollment requests are independent capture groups; vectors are synthetic test data only.
        for student,index in [(self.a,0),(self.b,1)]:
            for event in range(3):
                result = self.enroll(student,np.eye(512)[index],(100+index*30,110+event*20,120))
                self.assertEqual(result.status_code,201)
        self.assertEqual(BiometricSample.objects.count(),6)
        sample = self.a.biometrics.first()
        self.assertEqual(len(decode_embedding(sample.embedding_ciphertext)),512)
        self.assertTrue(decrypt(sample.photo_ciphertext).startswith(b'\xff\xd8'))
        self.assertEqual(AttendanceRecord.objects.count(),0)
        self.client.force_authenticate(self.other)
        reused = self.client.get(f'/api/students/?section={self.foreign.pk}').data
        self.assertEqual(reused[0]['enrolled_samples'],3)
        self.assertEqual(reused[0]['capture_groups'],3)
        self.assertEqual(self.client.post('/api/classifier/',{}).status_code,403)
        self.client.force_authenticate(self.admin)
        self.assertTrue(self.client.get('/api/classifier/status/').data['ready'])
        with patch('recognition.engine.extract_embedding',side_effect=AssertionError('Training must not call ArcFace')):
            trained = self.client.post('/api/classifier/',{})
        self.assertEqual(trained.status_code,201)
        self.assertEqual(trained.data['heldout_samples'],2)
        self.assertEqual(trained.data['train_samples'],4)
        self.assertEqual(match_embedding(np.eye(512)[0],[self.a.pk],.65,.08,True)[0],self.a.pk)
        self.client.force_authenticate(self.teacher)
        configured = self.config().data
        session = self.client.post(f'/api/sections/{self.section.pk}/start/',{'schedule':configured['id']}).data
        path = f"/api/sessions/{session['id']}/"
        token = self.client.post(path+'capture-grant/',{}).data['token']
        with patch('attendance.tasks.extract_embedding',return_value=np.eye(512)[0]), patch('recognition.classifier.train',side_effect=AssertionError('Scan must not retrain')):
            job = self.client.post(path+'capture/',{'token':token,'frame':photo((130,130,130))},format='multipart')
        self.assertEqual(job.status_code,202)
        self.assertEqual(job.data['status'],'review')
        self.assertEqual(job.data['proposed_student'],self.a.pk)
        self.assertEqual(AttendanceRecord.objects.count(),0)
        self.assertEqual(self.client.post(path+'confirm/',{'job':job.data['id']}).status_code,201)
        self.assertEqual(self.client.post(path+'confirm/',{'job':job.data['id']}).status_code,400)
        self.assertEqual(BiometricSample.objects.count(),6)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get('/api/classifier/status/').data['classifier'],'current')
