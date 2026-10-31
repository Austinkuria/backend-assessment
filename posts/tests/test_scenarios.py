"""
The "additional scenarios" from the brief: double-clicks, retries after a
dropped connection, retried updates and deletes, and requests that race
each other on the same post.
"""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from posts import idempotency
from posts.models import IdempotencyRecord, Post

from .helpers import PostTestMixin, detail_url, new_key


class DuplicatePublishTests(PostTestMixin, APITestCase):
    """Scenario 1 & 2: publish clicked repeatedly / retried after a dropped connection."""

    def test_repeated_clicks_with_same_key_create_one_post(self):
        key = new_key()
        responses = [self.publish(key=key) for _ in range(3)]

        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual({r.status_code for r in responses}, {status.HTTP_201_CREATED})
        self.assertEqual({r.data["id"] for r in responses}, {Post.objects.get().id})
        self.assertNotIn(idempotency.REPLAYED_HEADER, responses[0])
        self.assertEqual(responses[1][idempotency.REPLAYED_HEADER], "true")
        self.assertEqual(responses[2][idempotency.REPLAYED_HEADER], "true")

    def test_retry_after_lost_response_returns_original_result(self):
        key = new_key()
        first = self.publish(key=key)  # pretend this response never reached the phone

        # Later the app is reopened and the same action is retried.
        retry = self.publish(key=key)

        self.assertEqual(retry.status_code, status.HTTP_201_CREATED)
        self.assertEqual(retry.data, first.data)
        self.assertEqual(retry["Location"], first["Location"])
        self.assertEqual(Post.objects.count(), 1)

    def test_same_key_with_different_payload_is_rejected(self):
        key = new_key()
        self.publish({"title": "A", "content": "a"}, key=key)
        response = self.publish({"title": "B", "content": "b"}, key=key)

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(Post.objects.count(), 1)

    def test_distinct_keys_create_distinct_posts(self):
        # Two genuinely separate publish actions with identical text are allowed.
        self.publish(key=new_key())
        self.publish(key=new_key())
        self.assertEqual(Post.objects.count(), 2)

    def test_keys_are_scoped_per_user(self):
        key = new_key()
        self.publish(key=key)
        self.as_user(self.other)
        response = self.publish(key=key)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["author"]["username"], "other")
        self.assertEqual(Post.objects.count(), 2)

    def test_failed_validation_does_not_consume_the_key(self):
        key = new_key()
        bad = self.publish({"title": "", "content": "c"}, key=key)
        good = self.publish({"title": "fixed", "content": "c"}, key=key)

        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(good.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Post.objects.count(), 1)

    def test_expired_key_is_treated_as_new(self):
        key = new_key()
        self.publish(key=key)
        IdempotencyRecord.objects.update(created_at=timezone.now() - timedelta(days=2))

        response = self.publish(key=key)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn(idempotency.REPLAYED_HEADER, response)
        self.assertEqual(Post.objects.count(), 2)

    def test_concurrent_duplicate_that_loses_the_race_replays_winner(self):
        """
        Simulates two requests with the same key that both pass the lookup
        before either commits (possible on PostgreSQL). The loser hits the
        unique constraint, is rolled back, and replays the winner's response.
        """
        key = new_key()
        winner = self.publish(key=key)

        real_find = idempotency._find_record
        calls = {"n": 0}

        def find_misses_once(*args, **kwargs):
            calls["n"] += 1
            return None if calls["n"] == 1 else real_find(*args, **kwargs)

        with mock.patch.object(idempotency, "_find_record", side_effect=find_misses_once):
            loser = self.publish(key=key)

        self.assertEqual(loser.status_code, status.HTTP_201_CREATED)
        self.assertEqual(loser.data["id"], winner.data["id"])
        self.assertEqual(loser[idempotency.REPLAYED_HEADER], "true")
        self.assertEqual(Post.all_objects.count(), 1)  # the loser's post was rolled back

    def test_purge_command_removes_only_expired_records(self):
        self.publish(key="old")
        self.publish(key="fresh")
        IdempotencyRecord.objects.filter(key="old").update(created_at=timezone.now() - timedelta(days=2))

        call_command("purge_idempotency_records", stdout=StringIO())

        self.assertEqual(list(IdempotencyRecord.objects.values_list("key", flat=True)), ["fresh"])


class RetriedUpdateTests(PostTestMixin, APITestCase):
    """Scenario 3: an update appears to fail and is submitted again."""

    def setUp(self):
        super().setUp()
        self.post = self.create_post()
        self.url = detail_url(self.post["id"])

    def test_retried_conditional_update_succeeds_without_double_write(self):
        payload = {"title": "Edited", "content": "Edited content"}
        first = self.client.put(self.url, payload, headers={"If-Match": '"1"'})
        # The client never saw `first`, so it retries with the same (now stale) ETag.
        retry = self.client.put(self.url, payload, headers={"If-Match": '"1"'})

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(retry.status_code, status.HTTP_200_OK)
        self.assertEqual(retry.data["version"], 2)  # not bumped twice
        self.assertEqual(Post.objects.get().version, 2)

    def test_retried_unconditional_update_is_harmless(self):
        for _ in range(3):
            response = self.client.patch(self.url, {"title": "Edited"})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Post.objects.get().version, 2)

    def test_no_op_update_does_not_change_version(self):
        response = self.client.patch(self.url, {"title": "Hello campus"})
        self.assertEqual(response.data["version"], 1)


class RetriedDeleteTests(PostTestMixin, APITestCase):
    """Scenario 4: the client never receives confirmation of a delete."""

    def setUp(self):
        super().setUp()
        self.post = self.create_post()
        self.url = detail_url(self.post["id"])

    def test_retried_delete_returns_same_204(self):
        self.assertEqual(self.client.delete(self.url).status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.delete(self.url).status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Post.objects.count(), 0)
        self.assertEqual(Post.all_objects.get().version, 2)  # deleted exactly once

    def test_retried_conditional_delete_returns_204(self):
        for _ in range(2):
            response = self.client.delete(self.url, headers={"If-Match": '"1"'})
            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_deleted_post_is_404_for_other_users(self):
        self.client.delete(self.url)
        self.as_user(self.other)
        self.assertEqual(self.client.delete(self.url).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_404_NOT_FOUND)


class ConflictingRequestTests(PostTestMixin, APITestCase):
    """Scenario 5: two requests about the same post arrive close together."""

    def setUp(self):
        super().setUp()
        self.post = self.create_post()
        self.url = detail_url(self.post["id"])

    def test_stale_update_is_rejected_instead_of_overwriting(self):
        # Two devices of the same author load version 1 of the post.
        etag = self.client.get(self.url)["ETag"]

        laptop = self.client.patch(self.url, {"content": "From laptop"}, headers={"If-Match": etag})
        phone = self.client.patch(self.url, {"content": "From phone"}, headers={"If-Match": etag})

        self.assertEqual(laptop.status_code, status.HTTP_200_OK)
        self.assertEqual(phone.status_code, status.HTTP_412_PRECONDITION_FAILED)
        self.assertEqual(phone.data["current"]["content"], "From laptop")
        self.assertEqual(phone["ETag"], '"2"')
        self.assertEqual(Post.objects.get().content, "From laptop")

        # The phone reviews the latest version and retries deliberately.
        retry = self.client.patch(self.url, {"content": "From phone"}, headers={"If-Match": phone["ETag"]})
        self.assertEqual(retry.status_code, status.HTTP_200_OK)
        self.assertEqual(retry.data["version"], 3)

    def test_stale_delete_is_rejected(self):
        self.client.patch(self.url, {"content": "changed"})  # now version 2
        response = self.client.delete(self.url, headers={"If-Match": '"1"'})

        self.assertEqual(response.status_code, status.HTTP_412_PRECONDITION_FAILED)
        self.assertTrue(Post.objects.filter(pk=self.post["id"]).exists())

    def test_update_after_delete_returns_404(self):
        self.client.delete(self.url)
        response = self.client.patch(self.url, {"content": "too late"}, headers={"If-Match": '"1"'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_racing_a_delete_returns_404(self):
        """The post is deleted between the view loading it and the write."""
        pk = self.post["id"]

        def delete_then_update(**changes):
            # Another request deletes the post first...
            Post.all_objects.filter(pk=pk).update(deleted_at=timezone.now())
            # ...then our conditional write runs against active posts only.
            return Post.all_objects.filter(pk=pk, deleted_at__isnull=True).update(**changes)

        with mock.patch.object(Post.objects, "filter") as mocked_filter:
            mocked_filter.return_value.update.side_effect = delete_then_update
            response = self.client.patch(self.url, {"content": "racing"})

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Post.all_objects.get().content, "First post!")

    def test_if_match_formats(self):
        self.assertEqual(self.client.patch(self.url, {"title": "a"}, headers={"If-Match": 'W/"1"'}).status_code, 200)
        self.assertEqual(self.client.patch(self.url, {"title": "b"}, headers={"If-Match": "2"}).status_code, 200)
        self.assertEqual(self.client.patch(self.url, {"title": "c"}, headers={"If-Match": "*"}).status_code, 200)
        self.assertEqual(self.client.patch(self.url, {"title": "d"}, headers={"If-Match": "abc"}).status_code, 400)
