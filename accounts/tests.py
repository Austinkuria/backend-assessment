from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class AuthEndpointTests(APITestCase):
    def test_register_returns_token_that_authenticates(self):
        response = self.client.post(
            reverse("register"),
            {"username": "austin", "email": "austin@uni.ac.ke", "password": "s3cure-Passw0rd!"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["username"], "austin")
        self.assertNotIn("password", response.data)

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['token']}")
        self.assertEqual(self.client.get(reverse("post-list")).status_code, status.HTTP_200_OK)

    def test_register_rejects_weak_password(self):
        response = self.client.post(reverse("register"), {"username": "austin", "password": "123"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(username="austin").exists())

    def test_register_rejects_duplicate_username(self):
        User.objects.create_user(username="austin", password="s3cure-Passw0rd!")
        response = self.client.post(reverse("register"), {"username": "austin", "password": "s3cure-Passw0rd!"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_obtain_token_with_credentials(self):
        User.objects.create_user(username="austin", password="s3cure-Passw0rd!")
        response = self.client.post(reverse("token"), {"username": "austin", "password": "s3cure-Passw0rd!"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)

        bad = self.client.post(reverse("token"), {"username": "austin", "password": "wrong"})
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

