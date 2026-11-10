from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import SessionAuthentication


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """
    SessionAuthentication that skips CSRF validation.
    Used so that Swagger UI and API exploration tools can authenticate
    via sessions/tokens without CSRF cookie interference.
    """

    def enforce_csrf(self, request):
        return  # To not perform the csrf check


class CsrfExemptSessionAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = 'accounts.authentication.CsrfExemptSessionAuthentication'
    name = 'cookieAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'cookie',
            'name': 'sessionid',
        }
