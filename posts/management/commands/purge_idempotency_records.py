from django.core.management.base import BaseCommand
from django.utils import timezone

from posts.models import IdempotencyRecord


class Command(BaseCommand):
    help = "Delete idempotency records older than POSTS_IDEMPOTENCY_KEY_TTL_SECONDS (run e.g. daily via cron)."

    def handle(self, *args, **options):
        cutoff = timezone.now() - IdempotencyRecord.ttl()
        deleted, _ = IdempotencyRecord.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} expired idempotency record(s)."))

