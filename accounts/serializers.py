from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["id", "username", "email", "password"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        # Run Django's password validators against a not-yet-saved user so
        # that "similar to username" checks work.
        validate_password(attrs["password"], user=User(username=attrs.get("username"), email=attrs.get("email", "")))
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)

