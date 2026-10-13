import json
from django.core.management.base import BaseCommand, CommandError
from recognition.classifier import train
from attendance.services import audit

class Command(BaseCommand):
    help = 'Train/evaluate required logistic-regression classifier on encrypted frozen ArcFace samples.'
    def handle(self, *args, **options):
        try: report = train()
        except (ValueError, RuntimeError) as exc: raise CommandError(str(exc))
        audit('classifier.trained', train_samples=report['train_samples'], heldout_samples=report['heldout_samples'], accuracy=report['accuracy'])
        self.stdout.write(json.dumps(report, indent=2))
