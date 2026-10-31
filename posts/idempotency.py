"""
Idempotency-Key support for non-idempotent requests (creating a post).

The client generates a unique key (e.g. a UUID) once per user action - for
example when the "Publish" form is opened - and sends it with every attempt
of that action. The first attempt performs the work and stores its response;
every later attempt with the same key receives the stored response instead.
"""

import hashlib
import json
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError

from .models import IdempotencyRecord

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
MAX_KEY_LENGTH = 255


class IdempotencyKeyReused(APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "This Idempotency-Key has already been used for a different request."
    default_code = "idempotency_key_reused"


@dataclass(frozen=True)
class IdempotentResult:
    status_code: int
    body: dict
    replayed: bool


def get_idempotency_key(request):
    """Return the request's Idempotency-Key, or None if absent and optional."""
    key = request.headers.get(IDEMPOTENCY_HEADER, "").strip()
    if not key:
        if settings.POSTS_IDEMPOTENCY_KEY_REQUIRED:
            raise ValidationError({
                IDEMPOTENCY_HEADER: [
                    "This header is required. Send a unique value (e.g. a UUID) per "
                    "publish action and reuse it when retrying that action."
                ]
            })
        return None
    if len(key) > MAX_KEY_LENGTH:
        raise ValidationError({IDEMPOTENCY_HEADER: [f"Must be at most {MAX_KEY_LENGTH} characters."]})
    return key


def fingerprint_request(request, payload):
    """Stable hash identifying *what* is being asked for, independent of the key."""
    canonical = json.dumps(
        {"method": request.method, "path": request.path, "payload": payload},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _find_record(user, key, fingerprint):
    record = IdempotencyRecord.objects.filter(user=user, key=key).first()
    if record is None:
        return None
    if record.is_expired:
        record.delete()
        return None
    if record.request_fingerprint != fingerprint:
        raise IdempotencyKeyReused()
    return record


def execute_idempotently(*, user, key, fingerprint, operation):
    """
    Run ``operation`` at most once per (user, key).

    ``operation()`` must return ``(status_code, body)``. It runs in the same
    database transaction that stores the idempotency record, so either both
    the side effect and the record are committed or neither is.

    Concurrency: on SQLite (IMMEDIATE transactions) a second request with the
    same key waits for the first to commit and then finds its record. On
    databases where both requests can get past the lookup (e.g. PostgreSQL),
    the unique constraint makes the slower transaction fail and roll back;
    we then replay the winner's response.
    """
    try:
        with transaction.atomic():
            record = _find_record(user, key, fingerprint)
            if record is not None:
                return IdempotentResult(record.response_status, record.response_body, replayed=True)

            status_code, body = operation()
            IdempotencyRecord.objects.create(
                user=user,
                key=key,
                request_fingerprint=fingerprint,
                response_status=status_code,
                response_body=body,
            )
            return IdempotentResult(status_code, body, replayed=False)
    except IntegrityError:
        record = _find_record(user, key, fingerprint)
        if record is None:
            # The integrity error was not caused by a competing request.
            raise
        return IdempotentResult(record.response_status, record.response_body, replayed=True)

