from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from attendance.models import Section
from recognition.engine import extract_embedding, match_embedding, RecognitionRejected

class Command(BaseCommand):
    help = 'Offline live-photo recognition against one section; never writes attendance.'
    def add_arguments(self, parser):
        parser.add_argument('--section', required=True, type=int)
        parser.add_argument('--photo', required=True)
    def handle(self, *args, **options):
        from pathlib import Path
        section = Section.objects.get(pk=options['section'])
        try:
            vector = extract_embedding(Path(options['photo']).read_bytes())
            student_id, score = match_embedding(vector, section.students.values_list('id', flat=True),
                section.setting('match_threshold'), section.setting('match_margin'), settings.REQUIRE_CLASSIFIER)
        except RecognitionRejected as exc: raise CommandError(str(exc))
        student = section.students.get(pk=student_id)
        self.stdout.write(f'Proposed: {student.name}; cosine similarity {score:.4f}. No attendance saved.')
