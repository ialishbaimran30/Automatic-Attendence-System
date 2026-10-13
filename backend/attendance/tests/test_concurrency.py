from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless
from django.db import connection, close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from attendance.models import User, Department, Course, Section, Schedule, Student, AttendanceSession, SessionRoster, AttendanceRecord, RecognitionJob
from attendance import services

@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL required for row-lock concurrency verification')
class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('teacher', role='teacher')
        department = Department.objects.create(name='CS')
        course = Course.objects.create(department=department, code='C', name='Vision')
        section = Section.objects.create(course=course, name='A', semester='F')
        section.teachers.add(self.teacher)
        now = timezone.localtime()
        schedule = Schedule.objects.create(section=section, weekday=now.weekday(), start_time='00:00:00', end_time='23:59:59', valid_from=now.date(), valid_until=now.date())
        self.session = AttendanceSession.objects.create(section=section, schedule=schedule, scheduled_start=now-timedelta(minutes=1),
            scheduled_end=now+timedelta(hours=1), started_by=self.teacher, grace_minutes=10, match_threshold=.65, match_margin=.08)
        self.student = Student.objects.create(name='A', registration_number='A', department=department, consent_at=timezone.now())
        SessionRoster.objects.create(session=self.session, student=self.student, name='A', registration_number='A')
    def race(self, operation):
        barrier = Barrier(2)
        user_id = self.teacher.pk
        def call():
            close_old_connections()
            try:
                user = User.objects.get(pk=user_id)
                barrier.wait(timeout=10)
                operation(user)
                return 'saved'
            except ValidationError: return 'rejected'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: outcomes = list(pool.map(lambda _: call(), range(2)))
        self.assertEqual(sorted(outcomes), ['rejected','saved'])
        self.assertEqual(AttendanceRecord.objects.count(), 1)
    def test_simultaneous_manual_duplicate(self):
        self.race(lambda user: services.manual_record(user, self.session.pk, self.student.pk, 'Visual verification'))
    def test_simultaneous_confirmation(self):
        job = RecognitionJob.objects.create(session=self.session, requested_by=self.teacher, status='review', proposed_student=self.student,
            score=.92, expires_at=timezone.now()+timedelta(minutes=5))
        self.race(lambda user: services.confirm_job(user, self.session.pk, job.pk))
