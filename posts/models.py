from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class ActivePostManager(models.Manager):
    """Default manager: hides soft-deleted posts from every normal query."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Post(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    title = models.CharField(max_length=200)
    content = models.TextField(max_length=10_000)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Incremented on every successful write. Exposed to clients as the ETag so
    # they can make conditional (If-Match) updates/deletes and never silently
    # overwrite a change they have not seen (optimistic concurrency control).
    version = models.PositiveIntegerField(default=1)

    # Soft delete: a deleted post is kept as a tombstone so that a retried
    # DELETE from its author can be answered with a consistent 204.
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = ActivePostManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.title} (by {self.author})"

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def etag(self):
        return f'"{self.version}"'


class IdempotencyRecord(models.Model):
    """
    Remembers the outcome of a non-idempotent request (e.g. creating a post)
    so that a retry carrying the same Idempotency-Key gets the original
    response back instead of performing the action a second time.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="idempotency_records",
    )
    key = models.CharField(max_length=255)
    # Hash of method + path + payload; detects a key being reused for a
    # different request.
    request_fingerprint = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            # The database, not application code, is the final guard against
            # two concurrent requests both "winning" with the same key.
            models.UniqueConstraint(fields=["user", "key"], name="unique_idempotency_key_per_user"),
        ]

    def __str__(self):
        return f"{self.user} / {self.key}"

    @staticmethod
    def ttl():
        return timedelta(seconds=settings.POSTS_IDEMPOTENCY_KEY_TTL_SECONDS)

    @property
    def is_expired(self):
        return self.created_at < timezone.now() - self.ttl()
