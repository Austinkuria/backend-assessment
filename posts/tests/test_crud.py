"""Core CRUD behaviour, validation, authentication and authorization."""

from rest_framework import status
from rest_framework.settings import api_settings
from rest_framework.test import APITestCase

from posts.models import Post

from .helpers import LIST_URL, PostTestMixin, detail_url, new_key


class CreatePostTests(PostTestMixin, APITestCase):
    def test_authenticated_user_can_publish(self):
        response = self.publish({"title": "  Exam tips  ", "content": "Start early."})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Exam tips")  # trimmed
        self.assertEqual(response.data["content"], "Start early.")
        self.assertEqual(response.data["author"], {"id": self.author.id, "username": "author"})
        self.assertEqual(response.data["version"], 1)
        self.assertIsNotNone(response.data["created_at"])
        self.assertEqual(response["ETag"], '"1"')
        self.assertTrue(response["Location"].endswith(detail_url(response.data["id"])))
        self.assertEqual(Post.objects.get().author, self.author)

    def test_client_cannot_choose_author_or_read_only_fields(self):
        response = self.publish({
            "title": "t", "content": "c",
            "author": self.other.id, "version": 99, "created_at": "2000-01-01T00:00:00Z",
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        post = Post.objects.get()
        self.assertEqual(post.author, self.author)
        self.assertEqual(post.version, 1)
        self.assertNotEqual(post.created_at.year, 2000)

    def test_unauthenticated_user_cannot_publish(self):
        self.client.force_authenticate(None)
        response = self.publish()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(Post.objects.exists())

    def test_validation_errors(self):
        cases = {
            "missing title": {"content": "c"},
            "missing content": {"title": "t"},
            "blank title": {"title": "   ", "content": "c"},
            "blank content": {"title": "t", "content": ""},
            "title too long": {"title": "x" * 201, "content": "c"},
            "content too long": {"title": "t", "content": "x" * 10_001},
        }
        for name, payload in cases.items():
            with self.subTest(name):
                response = self.publish(payload)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Post.objects.exists())

    def test_idempotency_key_is_required(self):
        response = self.client.post(LIST_URL, {"title": "t", "content": "c"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Idempotency-Key", response.data)
        self.assertFalse(Post.objects.exists())

    def test_idempotency_key_too_long(self):
        response = self.publish(key="k" * 256)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_idempotency_key_can_be_made_optional(self):
        with self.settings(POSTS_IDEMPOTENCY_KEY_REQUIRED=False):
            response = self.client.post(LIST_URL, {"title": "t", "content": "c"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class RetrievePostTests(PostTestMixin, APITestCase):
    def test_list_posts_newest_first_with_author_info(self):
        first = self.create_post(title="first")
        self.as_user(self.other)
        second = self.create_post(title="second")

        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual([p["id"] for p in response.data["results"]], [second["id"], first["id"]])
        self.assertEqual(response.data["results"][0]["author"]["username"], "other")

    def test_list_is_paginated(self):
        page_size = api_settings.PAGE_SIZE
        for i in range(page_size + 5):
            Post.objects.create(author=self.author, title=f"p{i}", content="c")

        first_page = self.client.get(LIST_URL)
        self.assertEqual(first_page.data["count"], page_size + 5)
        self.assertEqual(len(first_page.data["results"]), page_size)
        self.assertIsNotNone(first_page.data["next"])

        second_page = self.client.get(first_page.data["next"])
        self.assertEqual(len(second_page.data["results"]), 5)

    def test_filter_list_by_author(self):
        self.create_post(title="mine")
        self.as_user(self.other)
        self.create_post(title="theirs")

        response = self.client.get(LIST_URL, {"author": self.author.id})
        self.assertEqual([p["title"] for p in response.data["results"]], ["mine"])

        self.assertEqual(self.client.get(LIST_URL, {"author": "abc"}).status_code, status.HTTP_400_BAD_REQUEST)

    def test_retrieve_single_post(self):
        post = self.create_post()
        self.as_user(self.other)  # any member can read any post

        response = self.client.get(detail_url(post["id"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Hello campus")
        self.assertEqual(response.data["author"]["id"], self.author.id)
        self.assertEqual(response["ETag"], '"1"')

    def test_retrieve_missing_post_returns_404(self):
        self.assertEqual(self.client.get(detail_url(9999)).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get(f"{LIST_URL}abc/").status_code, status.HTTP_404_NOT_FOUND)

    def test_reading_requires_authentication(self):
        post = self.create_post()
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(LIST_URL).status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.client.get(detail_url(post["id"])).status_code, status.HTTP_401_UNAUTHORIZED)


class UpdatePostTests(PostTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.post = self.create_post()
        self.url = detail_url(self.post["id"])

    def test_author_can_replace_post(self):
        response = self.client.put(self.url, {"title": "New title", "content": "New content"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "New title")
        self.assertEqual(response.data["content"], "New content")
        self.assertEqual(response.data["version"], 2)
        self.assertEqual(response["ETag"], '"2"')

    def test_author_can_partially_update_post(self):
        response = self.client.patch(self.url, {"content": "Edited"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Hello campus")
        self.assertEqual(response.data["content"], "Edited")

    def test_put_requires_all_fields(self):
        response = self.client.put(self.url, {"title": "Only title"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_validation(self):
        response = self.client.patch(self.url, {"title": ""})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Post.objects.get().title, "Hello campus")

    def test_other_user_cannot_update(self):
        self.as_user(self.other)
        for method in (self.client.put, self.client.patch):
            with self.subTest(method.__name__):
                response = method(self.url, {"title": "Hacked", "content": "Hacked"})
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Post.objects.get().title, "Hello campus")

    def test_author_cannot_be_changed_via_update(self):
        self.client.patch(self.url, {"author": self.other.id, "title": "x"})
        self.assertEqual(Post.objects.get().author, self.author)

    def test_update_missing_post_returns_404(self):
        response = self.client.patch(detail_url(9999), {"title": "x"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_user_cannot_update(self):
        self.client.force_authenticate(None)
        response = self.client.patch(self.url, {"title": "x"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Post.objects.get().title, "Hello campus")


class DeletePostTests(PostTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.post = self.create_post()
        self.url = detail_url(self.post["id"])

    def test_author_can_delete(self):
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get(LIST_URL).data["count"], 0)
        self.assertEqual(self.client.patch(self.url, {"title": "x"}).status_code, status.HTTP_404_NOT_FOUND)

    def test_other_user_cannot_delete(self):
        self.as_user(self.other)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Post.objects.filter(pk=self.post["id"]).exists())

    def test_delete_missing_post_returns_404(self):
        self.assertEqual(self.client.delete(detail_url(9999)).status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_user_cannot_delete(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.delete(self.url).status_code, status.HTTP_401_UNAUTHORIZED)


class TokenAuthenticationTests(PostTestMixin, APITestCase):
    def test_full_flow_with_token_header(self):
        token = self.client.post("/api/v1/auth/token/", {"username": "author", "password": "pass12345!"}).data["token"]
        self.client.force_authenticate(None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

        response = self.client.post(LIST_URL, {"title": "t", "content": "c"}, headers={"Idempotency-Key": new_key()})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["author"]["username"], "author")


class OpenAPISchemaTests(PostTestMixin, APITestCase):
    def test_schema_and_swagger_ui_endpoints_load_without_auth(self):
        self.client.force_authenticate(None)

        schema_res = self.client.get("/api/v1/schema/", headers={"Accept": "application/json"})
        self.assertEqual(schema_res.status_code, status.HTTP_200_OK)
        self.assertIn("/api/v1/posts/", schema_res.data["paths"])

        swagger_res = self.client.get("/api/v1/docs/")
        self.assertEqual(swagger_res.status_code, status.HTTP_200_OK)

        redoc_res = self.client.get("/api/v1/redoc/")
        self.assertEqual(redoc_res.status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get("/").status_code, status.HTTP_302_FOUND)

        health_res = self.client.get("/api/v1/health/")
        self.assertEqual(health_res.status_code, status.HTTP_200_OK)
        self.assertEqual(health_res.data, {"status": "ok", "database": "ok"})

