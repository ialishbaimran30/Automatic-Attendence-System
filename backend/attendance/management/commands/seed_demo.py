import os
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from attendance.models import User, Department, Course, Section, Student, Membership, Schedule

class Command(BaseCommand):
    help = 'Create idempotent non-biometric demo records and a schedule active now. Passwords from environment only.'
    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG: raise CommandError('Demo seed is only allowed with DJANGO_DEBUG=1.')
        password = os.getenv('DEMO_PASSWORD')
        if not password or len(password) < 10: raise CommandError('Set DEMO_PASSWORD to at least 10 characters.')
        for username, role in [('admin', 'admin'), ('teacher', 'teacher'), ('other-teacher', 'teacher')]:
            user, created = User.objects.get_or_create(username=username, defaults={'role': role, 'is_staff': role == 'admin'})
            if created:
                user.set_password(password)
                user.save()
        department, _ = Department.objects.get_or_create(name='Computer Science')
        course, _ = Course.objects.get_or_create(code='CS301', defaults={'name': 'Computer Vision', 'department': department})
        section, _ = Section.objects.get_or_create(course=course, name='A', semester='Fall 2026')
        section.teachers.add(User.objects.get(username='teacher'))
        other, _ = Section.objects.get_or_create(course=course, name='B', semester='Fall 2026')
        other.teachers.add(User.objects.get(username='other-teacher'))
        for i, name in enumerate(['Ayesha Khan', 'Bilal Ahmed', 'Hira Ali', 'Omar Raza', 'Zainab Noor'], 1):
            student, _ = Student.objects.get_or_create(registration_number=f'CS-2026-{i:03}', defaults={'name': name, 'department': department})
            Membership.objects.get_or_create(student=student, section=section)
            if i == 1: Membership.objects.get_or_create(student=student, section=other)
        now = timezone.localtime()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) if now.hour == 0 else now - timedelta(minutes=1)
        end = now.replace(hour=23, minute=59, second=59)
        Schedule.objects.get_or_create(section=section, weekday=now.weekday(), start_time=start.time().replace(tzinfo=None),
            end_time=end.time().replace(tzinfo=None), valid_from=now.date(), valid_until=now.date())
        self.stdout.write(self.style.SUCCESS('Seeded admin/teacher/other-teacher, two sections, five students, and today’s schedule. No photos or embeddings.'))
