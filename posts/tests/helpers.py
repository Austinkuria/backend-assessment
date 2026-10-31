import uuid

from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

LIST_URL = reverse("post-list")


def detail_url(post_id):
    return reverse("post-detail", kwargs={"pk": post_id})


def new_key():
    return str(uuid.uuid4())


class PostTestMixin:
    """Shared fixtures/helpers for post API tests."""

    def setUp(self):
        super().setUp()
        self.author = User.objects.create_user(username="author", password="pass12345!")
        self.other = User.objects.create_user(username="other", password="pass12345!")
        self.client.force_authenticate(self.author)

    def publish(self, data=None, key=None, client=None):
        data = data if data is not None else {"title": "Hello campus", "content": "First post!"}
        headers = {"Idempotency-Key": key} if key is not None else {"Idempotency-Key": new_key()}
        return (client or self.client).post(LIST_URL, data, headers=headers)

    def create_post(self, **data):
        response = self.publish({"title": "Hello campus", "content": "First post!", **data})
        assert response.status_code == 201, response.data
        return response.data

    def as_user(self, user):
        self.client.force_authenticate(user)

