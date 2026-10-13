import uuid
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        TEACHER = 'teacher', 'Teacher'
        ADMIN = 'admin', 'Administrator'
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.TEACHER)


class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)
    def __str__(self): return self.name


class Course(models.Model):
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=160)
    attendance_threshold = models.PositiveSmallIntegerField(default=75, validators=[MaxValueValidator(100)])
    grace_minutes = models.PositiveSmallIntegerField(default=10, validators=[MaxValueValidator(120)])
    match_threshold = models.FloatField(default=0.65, validators=[MinValueValidator(0), MaxValueValidator(1)])
    match_margin = models.FloatField(default=0.08, validators=[MinValueValidator(0), MaxValueValidator(1)])
    def __str__(self): return f'{self.code}: {self.name}'


class Section(models.Model):
    course = models.ForeignKey(Course, on_delete=models.PROTECT)
    name = models.CharField(max_length=60)
    semester = models.CharField(max_length=40)
    teachers = models.ManyToManyField(User, related_name='sections', blank=True, limit_choices_to={'role': 'teacher'})
    attendance_threshold = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(100)])
    grace_minutes = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(120)])
    match_threshold = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])
    match_margin = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])
    class Meta:
        constraints = [models.UniqueConstraint(fields=['course', 'name', 'semester'], name='unique_section')]
    def setting(self, key):
        value = getattr(self, key)
        return value if value is not None else getattr(self.course, key)
    def __str__(self): return f'{self.course.code} / {self.name} / {self.semester}'


class Schedule(models.Model):
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='schedules')
    weekday = models.PositiveSmallIntegerField(validators=[MaxValueValidator(6)])
    start_time = models.TimeField()
    end_time = models.TimeField()
    valid_from = models.DateField()
    valid_until = models.DateField()
    grace_minutes = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(120)])
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(end_time__gt=models.F('start_time')), name='schedule_time_order'),
                       models.CheckConstraint(condition=Q(valid_until__gte=models.F('valid_from')), name='schedule_date_order')]


class Student(models.Model):
    registration_number = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=40, blank=True)
    sections = models.ManyToManyField(Section, through='Membership', related_name='students')
    def __str__(self): return f'{self.registration_number} — {self.name}'


class Membership(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    section = models.ForeignKey(Section, on_delete=models.CASCADE)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['student', 'section'], name='unique_membership')]


class BiometricSample(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='biometrics')
    embedding_ciphertext = models.BinaryField()
    photo_ciphertext = models.BinaryField()
    capture_group = models.UUIDField()
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    model = models.CharField(max_length=20, default='ArcFace')
    photo_sha256 = models.CharField(max_length=64)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['student', 'photo_sha256'], name='unique_enrollment_photo')]


class EnrollmentLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    issued_by = models.ForeignKey(User, on_delete=models.PROTECT)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)
    capture_group = models.UUIDField(default=uuid.uuid4)


class AttendanceSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name='attendance_sessions')
    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT)
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    started_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True)
    started_by = models.ForeignKey(User, on_delete=models.PROTECT)
    grace_minutes = models.PositiveSmallIntegerField()
    match_threshold = models.FloatField()
    match_margin = models.FloatField()
    class Meta:
        constraints = [models.UniqueConstraint(fields=['section'], condition=Q(closed_at__isnull=True), name='one_open_session'),
                       models.UniqueConstraint(fields=['schedule', 'scheduled_start'], name='one_schedule_occurrence')]


class SessionRoster(models.Model):
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name='roster')
    student = models.ForeignKey(Student, on_delete=models.PROTECT)
    name = models.CharField(max_length=160)
    registration_number = models.CharField(max_length=40)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['session', 'student'], name='unique_roster_student')]


class RecognitionJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name='jobs')
    requested_by = models.ForeignKey(User, on_delete=models.PROTECT)
    captured_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=20, default='queued', choices=[(s, s) for s in ['queued', 'processing', 'review', 'rejected', 'error', 'confirmed']])
    proposed_student = models.ForeignKey(Student, on_delete=models.PROTECT, null=True)
    score = models.FloatField(null=True)
    reason = models.CharField(max_length=120, blank=True)
    frame_path = models.CharField(max_length=200, blank=True)
    confirmed_at = models.DateTimeField(null=True)


class CaptureGrant(models.Model):
    token_hash = models.CharField(max_length=64, unique=True)
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)


class AttendanceRecord(models.Model):
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name='records')
    student = models.ForeignKey(Student, on_delete=models.PROTECT)
    status = models.CharField(max_length=10, choices=[('present', 'Present'), ('late', 'Late'), ('absent', 'Absent')])
    timestamp = models.DateTimeField()
    score = models.FloatField(null=True)
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    method = models.CharField(max_length=20, choices=[('recognition', 'Recognition'), ('manual', 'Manual'), ('closure', 'Closure'), ('correction', 'Correction')])
    job = models.OneToOneField(RecognitionJob, on_delete=models.PROTECT, null=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['session', 'student'], name='unique_attendance')]


class AuditLog(models.Model):
    at = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(User, on_delete=models.PROTECT, null=True)
    section = models.ForeignKey(Section, on_delete=models.PROTECT, null=True)
    session = models.ForeignKey(AttendanceSession, on_delete=models.PROTECT, null=True)
    event = models.CharField(max_length=60)
    details = models.JSONField(default=dict)
    class Meta:
        ordering = ['-at', '-id']
