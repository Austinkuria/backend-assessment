from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Post

User = get_user_model()


class AuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username"]


class PostSerializer(serializers.ModelSerializer):
    """
    Title and content are trimmed, must not be blank, and are length-limited
    by the model (200 / 10,000 chars). The author is always the authenticated
    user and can never be supplied or changed by the client.
    """

    author = AuthorSerializer(read_only=True)

    class Meta:
        model = Post
        fields = ["id", "title", "content", "author", "created_at", "updated_at", "version"]
        read_only_fields = ["id", "author", "created_at", "updated_at", "version"]

