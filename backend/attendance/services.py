import hashlib
import secrets
from datetime import datetime, timedelta
from django.db import transaction, IntegrityError
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import (AttendanceSession, SessionRoster, AttendanceRecord, AuditLog, CaptureGrant, RecognitionJob, Schedule)
from .permissions import authorize_section


def audit(event, actor=None, session=None, section=None, **details):
    return AuditLog.objects.create(event=event, actor=actor, session=session,
                                   section=section or (session.section if session else None), details=details)

def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()

def require_open(session):
    if session.closed_at:
        raise ValidationError('Session is closed.')


@transaction.atomic
def configure_class(user, section, class_date, start_time, duration_minutes, grace_minutes):
    from .models import Section
    section = Section.objects.select_for_update().get(pk=section.pk)
    authorize_section(user, section)
    if class_date < timezone.localdate(): raise ValidationError('Choose today or a future class date; capture time cannot be backdated.')
    if not 1 <= duration_minutes <= 480 or not 0 <= grace_minutes <= min(120, duration_minutes):
        raise ValidationError('Duration must be 1–480 minutes; grace must be 0–120 minutes and within the class duration.')
    end = datetime.combine(class_date, start_time) + timedelta(minutes=duration_minutes)
    if end.date() != class_date: raise ValidationError('Class must end on the selected date; overnight classes are unsupported.')
    # Add a dated occurrence without changing administration's recurring schedules or course defaults.
    schedule, created = Schedule.objects.get_or_create(section=section, weekday=class_date.weekday(),
        start_time=start_time, end_time=end.time(), valid_from=class_date, valid_until=class_date,
        grace_minutes=grace_minutes)
    if created:
        audit('class.configured', user, section=section, schedule_id=schedule.pk, class_date=class_date.isoformat(),
              start_time=start_time.isoformat(), duration_minutes=duration_minutes, grace_minutes=grace_minutes)
    return schedule


@transaction.atomic
def start_session(user, section, schedule):
    # Serialize starts for the same section on PostgreSQL.
    from .models import Section
    section = Section.objects.select_for_update().select_related('course').get(pk=section.pk)
    authorize_section(user, section)
    now = timezone.now()
    today = timezone.localdate(now)
    if schedule.section_id != section.pk or schedule.weekday != today.weekday() or not schedule.valid_from <= today <= schedule.valid_until:
        raise ValidationError('Schedule does not occur today for this section.')
    start = timezone.make_aware(datetime.combine(today, schedule.start_time))
    end = timezone.make_aware(datetime.combine(today, schedule.end_time))
    if not start - timedelta(minutes=15) <= now <= end:
        raise ValidationError('Start within 15 minutes before the scheduled class or during it.')
    if section.attendance_sessions.filter(closed_at__isnull=True).exists():
        raise ValidationError('Section already has an open session.')
    if AttendanceSession.objects.filter(section=section, scheduled_start=start).exists():
        raise ValidationError('This scheduled occurrence has already been recorded.')
    students = list(section.students.filter(active=True))
    if not students:
        raise ValidationError('Section roster is empty.')
    session = AttendanceSession.objects.create(section=section, schedule=schedule, scheduled_start=start,
        scheduled_end=end, started_by=user, grace_minutes=schedule.grace_minutes if schedule.grace_minutes is not None else section.setting('grace_minutes'),
        match_threshold=section.setting('match_threshold'), match_margin=section.setting('match_margin'))
    SessionRoster.objects.bulk_create([SessionRoster(session=session, student=s, name=s.name,
        registration_number=s.registration_number) for s in students])
    audit('session.started', user, session, roster_count=len(students))
    return session


def locked_session(user, session_id):
    session = AttendanceSession.objects.select_for_update().select_related('section').get(pk=session_id)
    authorize_section(user, session.section)
    return session

def status_at(session, captured_at):
    return 'late' if captured_at > session.scheduled_start + timedelta(minutes=session.grace_minutes) else 'present'

def require_roster(session, student_id):
    if not session.roster.filter(student_id=student_id).exists():
        raise ValidationError('Student is outside the session roster.')


@transaction.atomic
def manual_record(user, session_id, student_id, reason):
    session = locked_session(user, session_id)
    require_open(session)
    require_roster(session, student_id)
    if not reason.strip(): raise ValidationError('A reason is required for manual attendance.')
    if session.records.filter(student_id=student_id).exists(): raise ValidationError('Attendance already exists; use correction.')
    now = timezone.now()
    record = AttendanceRecord.objects.create(session=session, student_id=student_id, status=status_at(session, now),
        timestamp=now, actor=user, method='manual')
    audit('attendance.manual', user, session, student_id=student_id, reason=reason, status=record.status)
    return record


@transaction.atomic
def correct_record(user, session_id, student_id, status, reason):
    session = locked_session(user, session_id)
    require_roster(session, student_id)
    if status not in ('present', 'late', 'absent') or not reason.strip():
        raise ValidationError('Valid status and correction reason are required.')
    record = session.records.filter(student_id=student_id).first()
    if not record: raise ValidationError('No attendance record exists; use manual check-in while session is open.')
    before = {'status': record.status, 'actor_id': record.actor_id, 'method': record.method}
    record.status, record.actor, record.method = status, user, 'correction'
    # Preserve original capture time and source job; audit records the correction time.
    record.save(update_fields=['status', 'actor', 'method'])
    audit('attendance.corrected', user, session, student_id=student_id, before=before, status=status, reason=reason)
    return record


@transaction.atomic
def close_session(user, session_id):
    session = locked_session(user, session_id)
    require_open(session)
    now = timezone.now()
    existing = set(session.records.values_list('student_id', flat=True))
    missing = session.roster.exclude(student_id__in=existing)
    records = [AttendanceRecord(session=session, student_id=r.student_id, status='absent', timestamp=now,
                                actor=user, method='closure') for r in missing]
    AttendanceRecord.objects.bulk_create(records)
    session.closed_at = now
    session.save(update_fields=['closed_at'])
    audit('session.closed', user, session, absent_count=len(records))
    return session


@transaction.atomic
def issue_capture(user, session_id):
    from django.conf import settings
    session = locked_session(user, session_id)
    require_open(session)
    if timezone.now() > session.scheduled_end:
        raise ValidationError('Scheduled capture window has ended. Close the session.')
    raw = secrets.token_urlsafe(32)
    grant = CaptureGrant.objects.create(user=user, session=session, token_hash=token_hash(raw),
        expires_at=timezone.now() + timedelta(seconds=settings.CAPTURE_TTL_SECONDS))
    return raw, grant.expires_at


@transaction.atomic
def create_job(user, session_id, token, frame_path):
    from django.conf import settings
    session = locked_session(user, session_id)
    require_open(session)
    now = timezone.now()
    if now > session.scheduled_end: raise ValidationError('Scheduled capture window has ended.')
    grant = CaptureGrant.objects.select_for_update().filter(user=user, session=session, token_hash=token_hash(token)).first()
    if not grant or grant.used_at or grant.expires_at <= now:
        raise ValidationError('Capture authorization is invalid, expired, or already used.')
    grant.used_at = now
    grant.save(update_fields=['used_at'])
    return RecognitionJob.objects.create(session=session, requested_by=user, captured_at=now,
        expires_at=now + timedelta(seconds=settings.JOB_REVIEW_TTL_SECONDS), frame_path=frame_path)


@transaction.atomic
def confirm_job(user, session_id, job_id):
    session = locked_session(user, session_id)
    require_open(session)
    job = RecognitionJob.objects.select_for_update().filter(pk=job_id, session=session, requested_by=user).first()
    now = timezone.now()
    if not job or job.status != 'review' or job.confirmed_at or job.expires_at <= now or not job.proposed_student_id:
        raise ValidationError('Job is not a fresh review for this user and session.')
    require_roster(session, job.proposed_student_id)
    if not job.proposed_student.active or job.proposed_student.consent_at is None:
        raise ValidationError('Student is inactive or biometric consent has been withdrawn. Use an audited manual override.')
    if session.records.filter(student_id=job.proposed_student_id).exists(): raise ValidationError('Student already checked in.')
    record = AttendanceRecord.objects.create(session=session, student_id=job.proposed_student_id,
        status=status_at(session, job.captured_at), timestamp=job.captured_at, score=job.score,
        actor=user, method='recognition', job=job)
    job.status, job.confirmed_at = 'confirmed', now
    job.save(update_fields=['status', 'confirmed_at'])
    audit('attendance.confirmed', user, session, student_id=job.proposed_student_id, job_id=str(job.id), score=job.score)
    return record
