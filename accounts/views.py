from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .serializers import RegisterSerializer


class RegisterView(generics.CreateAPIView):
    """Create an account and return an API token for it."""

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({**serializer.data, "token": token.key}, status=status.HTTP_201_CREATED)

