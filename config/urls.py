"""
URL configuration for config project.
"""
from django.contrib import admin
from django.db import connection
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@extend_schema(
    summary="Health check",
    responses={200: {"type": "object", "properties": {"status": {"type": "string"}, "database": {"type": "string"}}}},
)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return Response({"status": "error", "database": "unreachable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"status": "ok", "database": "ok"}, status=status.HTTP_200_OK)


v1_patterns = [
    path('health/', health_check, name='health'),
    path('auth/', include('accounts.urls')),
    path('', include('posts.urls')),
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='swagger-ui', permanent=False), name='root'),
    path('health/', health_check, name='health-root'),
    path('admin/', admin.site.urls),
    path('api/v1/', include(v1_patterns)),
    # Login/logout for the browsable API.
    path('api-auth/', include('rest_framework.urls')),
]
