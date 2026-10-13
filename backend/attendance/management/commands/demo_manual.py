from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from attendance.models import User, Section
from attendance.services import start_session, manual_record, close_session
from attendance.reports import grid
from django.utils import timezone

class Command(BaseCommand):
    help = 'Runnable manual milestone: start, check in one, close, print percentages. Use after seed_demo.'
    def handle(self, *args, **options):
        if not settings.DEBUG: raise CommandError('Demo only allowed in DEBUG mode.')
        teacher = User.objects.get(username='teacher')
        section = Section.objects.get(course__code='CS301', name='A', semester='Fall 2026')
        schedule = section.schedules.filter(valid_from=timezone.localdate()).last()
        try:
            session = start_session(teacher, section, schedule)
            manual_record(teacher, session.pk, session.roster.first().student_id, 'Runnable demo: teacher visually verified identity')
            close_session(teacher, session.pk)
        except Exception as exc: raise CommandError(str(exc))
        data = grid(section, {})
        self.stdout.write(f'Session {session.pk}: one attended, remaining absent. Late counts as attended.')
        for row in data['students']:
            self.stdout.write(f"{row['registration_number']}: {row['percentage']}% ({row['attended']}/{row['denominator']})")
