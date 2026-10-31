"""
Write operations on posts that must stay correct under retries and
concurrent requests.

Every write is a single conditional UPDATE ("compare-and-swap") executed by
the database, so there is no window between "check" and "write" in which a
competing request can sneak in - regardless of how many app servers or
threads are handling requests.
"""

from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from .models import Post


class PreconditionFailed(Exception):
    """The client's If-Match version no longer matches the stored post."""

    def __init__(self, current):
        super().__init__("Post has been modified since the given version.")
        self.current = current


def parse_if_match(request):
    """
    Return the version number from the If-Match header, or None when the
    client did not ask for a conditional request. Accepts ``"3"``, ``3``,
    ``W/"3"`` and ``*`` (any version).
    """
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    value = raw.strip()
    if value == "*":
        return None
    if value.startswith("W/"):
        value = value[2:]
    value = value.strip('"')
    if not value.isdigit():
        raise ValidationError({"If-Match": ["Must be the post's ETag / version, e.g. \"3\"."]})
    return int(value)


def _already_applied(post, changes):
    return all(getattr(post, field) == value for field, value in changes.items())


def update_post(*, post, changes, expected_version=None):
    """
    Apply ``changes`` to ``post`` and return the fresh post.

    - If the post already holds exactly these values (e.g. the client is
      retrying an update that actually succeeded), nothing is written and
      the current post is returned: retries are harmless.
    - If ``expected_version`` is given and someone else changed the post in
      the meantime, ``PreconditionFailed`` is raised instead of silently
      overwriting their change (no "lost updates").
    - If the post was deleted concurrently, ``NotFound`` is raised.
    """
    if _already_applied(post, changes):
        return post

    queryset = Post.objects.filter(pk=post.pk)
    if expected_version is not None:
        queryset = queryset.filter(version=expected_version)
    updated = queryset.update(**changes, version=F("version") + 1, updated_at=timezone.now())

    current = Post.all_objects.select_related("author").filter(pk=post.pk).first()
    if updated:
        return current
    if current is None or current.is_deleted:
        raise NotFound("Post not found.")
    if _already_applied(current, changes):
        # A concurrent duplicate of this same update won the race.
        return current
    raise PreconditionFailed(current)


def soft_delete_post(*, post, expected_version=None):
    """
    Mark ``post`` as deleted. Deleting an already-deleted post is a no-op,
    so a retried DELETE produces the same outcome as the first one.
    """
    if post.is_deleted:
        return

    queryset = Post.objects.filter(pk=post.pk)
    if expected_version is not None:
        queryset = queryset.filter(version=expected_version)
    if queryset.update(deleted_at=timezone.now(), version=F("version") + 1):
        return

    current = Post.all_objects.get(pk=post.pk)
    if current.is_deleted:
        # A concurrent duplicate of this delete got there first.
        return
    raise PreconditionFailed(current)

