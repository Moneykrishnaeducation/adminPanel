from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.exceptions import AuthenticationFailed
import typing
import logging

logger = logging.getLogger(__name__)


def _is_admin_path(path: str) -> bool:
    if not path:
        return False
    p = path.lower()
    return ('/api/admin/' in p) or p.startswith('/admin-api') or ('/admin-api/' in p) or ('/admin/dashboard' in p) or ('/manager/dashboard' in p)


class BlacklistCheckingJWTAuthentication(JWTAuthentication):
    """JWTAuthentication that also checks token JTI against the blacklist.

    This prevents access tokens that were explicitly blacklisted from being
    accepted even if they are not yet expired.
    """

    def get_validated_token(self, raw_token):
        token = super().get_validated_token(raw_token)

        try:
            jti = token.payload.get(api_settings.JTI_CLAIM)
        except Exception:
            jti = None

        if jti:
            try:
                if BlacklistedToken.objects.filter(token__jti=jti).exists():
                    raise InvalidToken('Token is blacklisted')
            except InvalidToken:
                raise
            except Exception:
                # If token blacklist models are not available or DB errors occur,
                # fail open (log at caller) to avoid locking out users during DB issues.
                pass

        return token

    def authenticate(self, request):
        """
        Authenticate request by checking:
        1. Authorization header (Bearer token)
        2. HttpOnly cookies (jwt_token, accessToken, etc.)
        """
        logger.debug(f"[Auth] Authenticating request to {request.path}")
        logger.debug(f"[Auth] Available cookies: {list(request.COOKIES.keys())}")
        
        # Try to get raw token from Authorization header first
        auth_header = self.get_header(request)
        if auth_header:
            try:
                logger.debug(f"[Auth] Found Authorization header")
                result = super().authenticate(request)
                if result:
                    user, token = result
                    logger.debug(f"[Auth] Authorization header validated for user: {user}")
                    return self._validate_token_for_request(token, request, user)
            except Exception as e:
                logger.debug(f"[Auth] Authorization header validation failed: {str(e)}")
                # Don't return, continue to check cookies
        
        # Try to get token from cookies (HttpOnly approach)
        raw_token = None
        cookie_source = None
        for cookie_name in ['jwt_token', 'accessToken', 'access_token']:
            raw_token = request.COOKIES.get(cookie_name)
            if raw_token:
                cookie_source = cookie_name
                break
        
        if not raw_token:
            logger.debug(f"[Auth] No token found in cookies or Authorization header")
            return None
        
        logger.debug(f"[Auth] Found token in cookie: {cookie_source}")
        
        # Validate the token extracted from cookie
        try:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)
            logger.debug(f"[Auth] Cookie token validated successfully for user: {user}")
            try:
                return self._validate_token_for_request(validated_token, request, user)
            except InvalidToken as e:
                logger.warning(f"[Auth] Token validation for request failed: {str(e)}")
                raise
        except Exception as e:
            logger.error(f"[Auth] Cookie token validation failed: {type(e).__name__}: {str(e)}")
            raise InvalidToken(f'Invalid token in cookie: {str(e)}')
    
    def _validate_token_for_request(self, token, request, user):
        """Validate token audience and scope for the request path."""
        # Enforce strict token separation based on request path
        try:
            aud = token.payload.get('aud') if hasattr(token, 'payload') else None
            scope = token.payload.get('scope') if hasattr(token, 'payload') else None
        except Exception:
            aud = None
            scope = None

        # If this is an admin endpoint, require admin audience/scope
        if _is_admin_path(getattr(request, 'path', '')):
            logger.debug(f"[Auth] Admin path detected: {request.path}, checking audience...")
            if aud != 'admin.vtindex':
                logger.warning(f"[Auth] Admin endpoint but token aud is '{aud}' (expected 'admin.vtindex')")
                raise InvalidToken('Token audience is not allowed for admin endpoints')
            if scope and isinstance(scope, str):
                if not scope.startswith('admin:'):
                    logger.warning(f"[Auth] Admin endpoint but token scope is '{scope}' (expected 'admin:*')")
                    raise InvalidToken('Token scope not permitted for admin endpoints')
        else:
            logger.debug(f"[Auth] Non-admin path, skipping audience check. Path: {request.path}, Token aud: {aud}")

        return (user, token)
