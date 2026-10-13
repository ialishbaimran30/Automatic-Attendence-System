from django.core.management.base import BaseCommand
from attendance.tasks import purge_expired

class Command(BaseCommand):
    help = 'Purge expired biometric samples and abandoned frames (also scheduled by Celery beat).'
    def handle(self, *args, **options):
        purge_expired()
        self.stdout.write('Private retention cleanup complete.')
