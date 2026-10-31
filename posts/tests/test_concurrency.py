"""
Real concurrency tests: several threads, each with its own database
connection, fire requests about the same post at the same moment.

These use TransactionTestCase (no wrapping test transaction) and a
file-backed SQLite test database so the threads genuinely compete.
"""

import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from posts.models import IdempotencyRecord, Post

from .helpers import LIST_URL, detail_url, new_key

User = get_user_model()

THREADS = 6


def run_concurrently(user, request_fn, count=THREADS):
    """Run ``request_fn(client, index)`` in ``count`` threads released at once."""
    barrier = threading.Barrier(count)
    responses = [None] * count
    errors = []

    def worker(index):
        client = APIClient()
        client.force_authenticate(user)
        try:
            barrier.wait()
            responses[index] = request_fn(client, index)
        except Exception as exc:  # surfaced in the main thread below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]
    return responses


class ConcurrentRequestTests(TransactionTestCase):
    def setUp(self):
        self.author = User.objects.create_user(username="author", password="pass12345!")

    def test_simultaneous_publishes_with_same_key_create_one_post(self):
        key = new_key()
        payload = {"title": "Hello", "content": "World"}

        responses = run_concurrently(
            self.author,
            lambda client, _: client.post(LIST_URL, payload, headers={"Idempotency-Key": key}),
        )

        self.assertEqual([r.status_code for r in responses], [201] * THREADS)
        self.assertEqual(len({r.data["id"] for r in responses}), 1)
        self.assertEqual(Post.all_objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_simultaneous_conditional_updates_only_one_wins(self):
        post = Post.objects.create(author=self.author, title="t", content="c")

        responses = run_concurrently(
            self.author,
            lambda client, i: client.patch(detail_url(post.id), {"content": f"edit {i}"}, headers={"If-Match": '"1"'}),
        )

        codes = sorted(r.status_code for r in responses)
        self.assertEqual(codes, [200] + [412] * (THREADS - 1))
        winner = next(r for r in responses if r.status_code == 200)
        post.refresh_from_db()
        self.assertEqual(post.version, 2)
        self.assertEqual(post.content, winner.data["content"])

    def test_simultaneous_deletes_all_succeed_and_delete_once(self):
        post = Post.objects.create(author=self.author, title="t", content="c")

        responses = run_concurrently(self.author, lambda client, _: client.delete(detail_url(post.id)))

        self.assertEqual([r.status_code for r in responses], [204] * THREADS)
        post = Post.all_objects.get(pk=post.id)
        self.assertTrue(post.is_deleted)
        self.assertEqual(post.version, 2)

