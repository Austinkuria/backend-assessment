"""
Views for handling user authentication and registration workflows.
"""
from rest_framework import generics, serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, inline_serializer

from .serializers import RegisterSerializer


class RegisterView(generics.CreateAPIView):
    """
    Create an account and return an API token for it.
    """
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="User Registration",
        responses={
            201: inline_serializer(
                name="RegisterResponse",
                fields={
                    "id": serializers.IntegerField(),
                    "username": serializers.CharField(),
                    "email": serializers.EmailField(),
                    "token": serializers.CharField(),
                }
            )
        }
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Issue an authentication token for the newly minted user
        # pylint: disable=no-member
        token, _ = Token.objects.get_or_create(user=user)

        return Response(
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "token": token.key
            },
            status=status.HTTP_201_CREATED
        )
