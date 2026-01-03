from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import redirect
from django.conf import settings
from django.urls import reverse
from django.contrib.auth.views import redirect_to_login
from django.utils.deprecation import MiddlewareMixin
from adminPanel.authentication import BlacklistCheckingJWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from django.contrib.auth.models import AnonymousUser
import jwt


class DashboardAuthenticationMiddleware:
    """
    Middleware to handle JWT authentication for dashboard pages
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.jwt_auth = BlacklistCheckingJWTAuthentication()

    def __call__(self, request):

        # Exempt a small set of lightweight OTP endpoints used by frontends
        # These endpoints must be reachable without a valid JWT so that
        # login flows that require OTP verification can poll status/resend/verify.
        try:
            exempt_api_paths = getattr(settings, 'EARLY_API_AUTH_EXEMPT_PATHS', None)
        except Exception:
            exempt_api_paths = None
        if not exempt_api_paths:
            exempt_api_paths = [
                '/api/login-otp-status/',
                '/api/resend-login-otp/',
                '/api/verify-otp/',
            ]
        for p in exempt_api_paths:
            if request.path.startswith(p):
                return self.get_response(request)
        # Only apply to dashboard pages
        if not (request.path.startswith('/manager/dashboard/') or 
                request.path.startswith('/admin/dashboard/')):
            return self.get_response(request)

        # Skip for static files and other public paths
        if (request.path.startswith('/static/') or 
            request.path.startswith('/.well-known/') or 
            request.path == '/favicon.ico'):
            return self.get_response(request)

        # Try to authenticate with JWT from Authorization header (centralized authenticate enforces aud/scope)
        try:
            auth_result = self.jwt_auth.authenticate(request)
            if auth_result:
                user, token = auth_result
                if user and user.is_authenticated:
                    request.user = user
                    return self.get_response(request)
        except (InvalidToken, TokenError) as e:
            print(f"JWT authentication failed: {e}")
            pass

        # Try to authenticate with JWT from cookies (if set by frontend)
        jwt_token = request.COOKIES.get('jwt_token')
        if jwt_token:
            # Temporarily set Authorization header so authenticate() inspects the token
            orig = request.META.get('HTTP_AUTHORIZATION')
            request.META['HTTP_AUTHORIZATION'] = f'Bearer {jwt_token}'
            try:
                auth_result = self.jwt_auth.authenticate(request)
                if auth_result:
                    user, token = auth_result
                    if user and user.is_authenticated:
                        request.user = user
                        return self.get_response(request)
            except (InvalidToken, TokenError) as e:
                print(f"JWT cookie authentication failed: {e}")
                pass
            finally:
                # restore original header
                if orig is None:
                    request.META.pop('HTTP_AUTHORIZATION', None)
                else:
                    request.META['HTTP_AUTHORIZATION'] = orig

        # If no valid authentication found, return unauthorized
        print(f"Unauthorized: {request.path}")
        if request.headers.get('Accept', '').find('application/json') != -1:
            return HttpResponseForbidden('{"detail":"Authentication credentials were not provided."}',
                                       content_type='application/json')
        else:
            # Redirect to login page for HTML requests Z$>[#UVW`L
            return redirect('/static/admin/index.html')
