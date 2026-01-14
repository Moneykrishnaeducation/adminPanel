import json
import ast
import time
import logging
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from django.contrib.auth import authenticate, get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from datetime import timedelta
from django.db.models import Q
import hashlib
import secrets
import threading
from django.utils import timezone
from adminPanel.models import ActivityLog
from adminPanel.EmailSender import EmailSender
import random
from django.http import HttpResponse
from rest_framework import status as drf_status
from rest_framework.permissions import AllowAny
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
import os
from rest_framework.permissions import IsAuthenticated
from adminPanel.permissions import IsAdminOrManager
from clientPanel.views.auth_views import get_client_ip

logger = logging.getLogger(__name__)

# OTP Hashing utilities
def hash_otp(otp):
    """Hash OTP with salt for secure storage"""
    salt = secrets.token_hex(16)  # Generate random 16-byte salt
    otp_hash = hashlib.pbkdf2_hmac(
        'sha256',
        otp.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"{salt}${otp_hash.hex()}"

def verify_otp(stored_hash, provided_otp):
    """Verify provided OTP against stored hash"""
    try:
        salt, otp_hash = stored_hash.split('$')
        provided_hash = hashlib.pbkdf2_hmac(
            'sha256',
            provided_otp.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        ).hex()
        return provided_hash == otp_hash
    except Exception:
        return False

def verify_password(stored_hash, provided_password):
    """Verify provided password against stored hash+salt"""
    try:
        salt, password_hash = stored_hash.split('$')
        provided_hash = hashlib.pbkdf2_hmac(
            'sha256',
            provided_password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        ).hex()
        return provided_hash == password_hash
    except Exception:
        return False


@api_view(['POST', 'OPTIONS'])
@permission_classes([AllowAny])
@csrf_exempt
def login_view(request):
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = JsonResponse({})
        response['Content-Length'] = '0'
        return response

    # Parse request body safely
    try:
        if request.body:
            data = json.loads(request.body)
        else:
            data = request.data or {}
    except Exception:
        data = request.data or {}

    # Try both email and username fields
    email = (data.get('email') or data.get('username') or '').strip()
    password = data.get('password')

    if not email or not password:
        # Log failed login attempt
        try:
            ActivityLog.objects.create(
                user=None,
                activity="Login attempt - missing email/username or password",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                status_code=400,
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now()
            )
        except Exception:
            logger.exception("Failed to create failed login ActivityLog")
        return JsonResponse({'error': 'Email/username and password are required'}, status=400)

    # Start timing (for diagnostics only in DEBUG)
    start_t = time.perf_counter()

    # Single optimized DB query for user by email OR username. Limit selected fields
    User = get_user_model()
    user = User.objects.only('id', 'email', 'username', 'password', 'manager_admin_status', 'is_superuser')\
        .filter(Q(email__iexact=email) | Q(username__iexact=email)).first()

    if not user:
        # Log failed login attempt
        try:
            ActivityLog.objects.create(
                user=None,
                activity=f"Login attempt - user not found: {email}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                status_code=401,
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now()
            )
        except Exception:
            logger.exception("Failed to create user-not-found ActivityLog")
        return JsonResponse({'error': 'Invalid email or password'}, status=401)

    # Check password using hash+salt verification
    if not verify_password(user.password, password):
        # Log failed login attempt
        try:
            ActivityLog.objects.create(
                user=user,
                activity="Login attempt - invalid password",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                status_code=401,
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now()
            )
        except Exception:
            logger.exception("Failed to create invalid-password ActivityLog")
        return JsonResponse({'error': 'Invalid email or password'}, status=401)

    # Allow superusers or users with Admin/Manager status
    if not user.is_superuser and getattr(user, 'manager_admin_status', '') not in ['Admin', 'Manager']:
        # Log access denied
        try:
            ActivityLog.objects.create(
                user=user,
                activity="Login attempt - insufficient permissions",
                ip_address=request.META.get('REMOTE_ADDR', ''),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                status_code=403,
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now()
            )
        except Exception:
            logger.exception("Failed to create access-denied ActivityLog")
        return JsonResponse({'error': 'Access denied. Admin privileges required.'}, status=403)

    # Determine client IP (best-effort)
    try:
        current_ip = (request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR') or '').split(',')[0]
    except Exception:
        current_ip = request.META.get('REMOTE_ADDR', '')

    # Check previous login IP and require OTP verification if it changed
    try:
        # Exclude ephemeral verification logs when computing the last "real" login IP.
        # If we don't exclude these, the earlier "verification required" entry (created
        # right below) will become the most-recent ActivityLog and make subsequent
        # login attempts from the same IP bypass verification.
        last_log = ActivityLog.objects.filter(user=user).exclude(related_object_type='LoginVerification').order_by('-timestamp').first()
        last_ip = last_log.ip_address if last_log else None
    except Exception:
        last_ip = None

    if last_ip and current_ip and last_ip != current_ip:
        try:
            # Generate login-specific OTP and attach to user
            otp = f"{random.randint(100000, 999999)}"
            # Hash OTP before storing
            hashed_otp = hash_otp(otp)
            # Attach hashed OTP to user model
            setattr(user, 'login_otp', hashed_otp)
            setattr(user, 'login_otp_created_at', timezone.now())
            user.save(update_fields=['login_otp', 'login_otp_created_at'])

            # Send OTP via email using dedicated login template if available
            try:
                EmailSender.send_login_otp_email(
                    user.email,
                    otp,
                    ip_address=current_ip,
                    login_time=timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
                    first_name=(user.first_name if hasattr(user, 'first_name') else None)
                )
            except Exception:
                logger.exception('Failed to send admin login OTP email')

            # Log that verification is required
            try:
                ActivityLog.objects.create(
                    user=user,
                    activity="Admin login attempt - verification required (new IP)",
                    ip_address=current_ip,
                    endpoint=request.path,
                    activity_type="update",
                    activity_category="management",
                    status_code=202,
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=user.id,
                    related_object_type="LoginVerification"
                )
            except Exception:
                logger.exception('Failed to create ActivityLog for admin login verification requirement')

            # Inform caller that verification is required
            return JsonResponse({
                'verification_required': True,
                'message': 'A verification code was sent to your email because this login originates from a new IP address.'
            }, status=202)
        except Exception:
            logger.exception('Error while generating admin login OTP; falling back to normal login')

    # Issue JWT tokens
    # SECURITY: if there's an active (unverified) login OTP for this user, do not
    # issue tokens until the OTP has been verified. This prevents the client from
    # bypassing verification by re-sending the login request and receiving tokens.
    try:
        login_otp_val = getattr(user, 'login_otp', None)
        # Use the model helper if available to check TTL/validity
        is_valid_otp = False
        if login_otp_val:
            try:
                is_valid_otp = user.is_login_otp_valid()
            except Exception:
                # conservative fallback: treat presence of login_otp as valid
                is_valid_otp = True
        if is_valid_otp:
            return JsonResponse({
                'verification_required': True,
                'message': 'A verification code is pending for this account. Please verify to continue.'
            }, status=202)
    except Exception:
        logger.exception('Failed to enforce pending-login-otp guard')

    refresh = RefreshToken.for_user(user)
    # Enforce token audience/scope for admin tokens
    try:
        refresh['aud'] = 'admin.vtindex'
        refresh['scope'] = 'admin:*'
        access = refresh.access_token
        access['aud'] = 'admin.vtindex'
        access['scope'] = 'admin:*'
    except Exception:
        # best-effort: if tokens are not mutable, continue
        pass
    # Parse remember flag from request (accepts booleans or strings)
    remember_val = data.get('remember', False)
    try:
        remember = str(remember_val).lower() in ('1', 'true', 'yes', 'on')
    except Exception:
        remember = False

    # Determine lifetimes: when remember is true, extend tokens; otherwise use defaults
    remember_refresh_lifetime = timedelta(days=30)  # Very long for "remember me"
    remember_access_lifetime = timedelta(days=7)    # Still short for security

    default_refresh_lifetime = settings.SIMPLE_JWT.get('REFRESH_TOKEN_LIFETIME', timedelta(days=30))
    default_access_lifetime = settings.SIMPLE_JWT.get('ACCESS_TOKEN_LIFETIME', timedelta(days=7))

    if remember:
        refresh_lifetime = remember_refresh_lifetime
        access_lifetime = remember_access_lifetime
    else:
        refresh_lifetime = default_refresh_lifetime
        access_lifetime = default_access_lifetime

    # Apply custom expirations to refresh and derived access token
    try:
        refresh.set_exp(from_time=refresh.current_time, lifetime=refresh_lifetime)
        access = refresh.access_token
        access.set_exp(from_time=access.current_time, lifetime=access_lifetime)
        try:
            # Record the issued access token as outstanding so it can be revoked/blacklisted later
            access.outstand()
        except Exception:
            logger.exception('Failed to create OutstandingToken for newly issued access (login_view)')
        access_token = str(access)
    except Exception:
        # Fallback to default issued tokens
        access_token = str(refresh.access_token)

    # Use relative redirect paths so the frontend can handle same-origin
    # redirects correctly on both local and live environments.
    try:
        role_val = getattr(user, 'manager_admin_status', '') or ''
        role_lower = role_val.lower() if isinstance(role_val, str) else str(role_val).lower()
    except Exception:
        role_lower = ''

    # Route managers to /manager; everyone else (admins/superusers) to /admin
    if role_lower == 'manager':
        redirect_url = '/manager/dashboard'
    else:
        redirect_url = '/dashboard'

    # Get user's name
    user_name = user.get_full_name() if hasattr(user, 'get_full_name') else (user.username or user.email.split('@')[0])

    # Return both 'access' and legacy 'token' keys for compatibility with different frontends
    # NOTE: Server-side Django session writes removed. Authentication is JWT-based
    # and frontend should persist tokens. Keeping server-side session writes here
    # caused state coupling; they were removed to simplify auth and avoid creating
    # unnecessary session cookies.

    # --- Record login activity and notify on IP change (background) ---
    try:
        current_ip = None
        try:
            current_ip = (request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR') or '').split(',')[0]
        except Exception:
            current_ip = request.META.get('REMOTE_ADDR', '')

        def _background_admin_login_tasks():
            try:
                # Best-effort: find last IP
                last_log = ActivityLog.objects.filter(user=user).order_by('-timestamp').first()
                last_ip = last_log.ip_address if last_log else None

                # Create activity log (best-effort)
                try:
                    ActivityLog.objects.create(
                        user=user,
                        activity="Admin login",
                        ip_address=current_ip,
                        endpoint=request.path,
                        activity_type="update",
                        activity_category="management",
                        status_code=200,
                        user_agent=request.META.get("HTTP_USER_AGENT", ""),
                        timestamp=timezone.now(),
                        related_object_id=user.id,
                        related_object_type="Login"
                    )
                except Exception:
                    logger.exception("Failed to create admin ActivityLog (background)")

                # If IP changed, notify (best-effort)
                if last_ip and last_ip != current_ip:
                    try:
                        EmailSender.send_new_ip_login_email(
                            user.email,
                            user.get_full_name() if hasattr(user, 'get_full_name') else user.email,
                            current_ip,
                            timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
                            request.META.get('HTTP_USER_AGENT', '')
                        )
                    except Exception:
                        logger.exception("Failed to send new-IP admin login email (background)")
            except Exception:
                logger.exception("Unexpected error in background admin login tasks")

        try:
            bg = threading.Thread(target=_background_admin_login_tasks, daemon=True)
            bg.start()
        except Exception:
            logger.exception("Failed to start background thread for admin login tasks")
    except Exception:
        logger.exception("Error scheduling background admin login tasks")

    # Compute timing and add debug header when DEBUG enabled
    duration_ms = int((time.perf_counter() - start_t) * 1000)

    resp_body = {
        'access': access_token,
        'token': access_token,
        'refresh': str(refresh),
        'auto_login': True,
        'remember': remember,
        'user': {
            'name': user_name,
            'email': user.email,
            'role': getattr(user, 'manager_admin_status', 'Admin').lower()
        },
        'redirect_url': redirect_url
    }

    # Include perf info in DEBUG for diagnostics
    response = JsonResponse(resp_body, status=200)
    response['X-Login-Duration-ms'] = str(duration_ms)
    if settings.DEBUG:
        # Expose in body for easier local testing (non-sensitive)
        try:
            body = json.loads(response.content)
            body['perf_ms'] = duration_ms
            response = JsonResponse(body, status=200)
            response['X-Login-Duration-ms'] = str(duration_ms)
        except Exception:
            # ignore any JSON errors
            pass

    # Set secure SameSite cookies for access/refresh tokens so clients can use
    # credentialed requests. Use DEBUG to decide Secure flag.
    # NOTE: Tokens are NOT HttpOnly to allow JavaScript to read them for Authorization headers
    # Security is maintained through SameSite=Strict and short lifespans
# --- ADMIN COOKIE MODE = EXACT CLIENT LOGIN MODE ---
    try:
        secure_flag = not settings.DEBUG

        try:
            refresh_lifetime = getattr(settings, 'SIMPLE_JWT', {}).get('REFRESH_TOKEN_LIFETIME', None)
            access_lifetime  = getattr(settings, 'SIMPLE_JWT', {}).get('ACCESS_TOKEN_LIFETIME', None)
            refresh_max_age = int(refresh_lifetime.total_seconds()) if refresh_lifetime else None
            access_max_age  = int(access_lifetime.total_seconds()) if access_lifetime else None
        except Exception:
            refresh_max_age = None
            access_max_age = None

        cookie_domain = getattr(settings, 'COOKIE_DOMAIN', None)

        # expose a small set of user-readable cookies for frontend usage
        # (frontend expects `userRole` from cookie; set non-HttpOnly so JS can read)
        role_val = getattr(user, 'manager_admin_status', 'Admin')
        try:
            role_val = role_val.lower() if isinstance(role_val, str) else str(role_val)
        except Exception:
            role_val = 'admin'

        if access_token:
            response.set_cookie('jwt_token', access_token, httponly=True, secure=secure_flag,
                                samesite='Strict', path='/', max_age=access_max_age, domain=cookie_domain)
            response.set_cookie('access_token', access_token, httponly=True, secure=secure_flag,
                                samesite='Strict', path='/', max_age=access_max_age, domain=cookie_domain)
            response.set_cookie('accessToken', access_token, httponly=True, secure=secure_flag,
                                samesite='Strict', path='/', max_age=access_max_age, domain=cookie_domain)

            # UI-facing cookies (HttpOnly) for security - backend will handle auth
            try:
                response.set_cookie('userName', user_name or '', httponly=True, secure=secure_flag,
                                    samesite='Strict', path='/', max_age=access_max_age, domain=cookie_domain)
            except Exception:
                pass
            try:
                response.set_cookie('userEmail', user.email or '', httponly=True, secure=secure_flag,
                                    samesite='Strict', path='/', max_age=access_max_age, domain=cookie_domain)
            except Exception:
                pass
            try:
                response.set_cookie('userRole', role_val or 'admin', httponly=True, secure=secure_flag,
                                    samesite='Strict', path='/', max_age=access_max_age, domain=cookie_domain)
            except Exception:
                pass

        if resp_body.get('refresh'):
            response.set_cookie('refresh_token', resp_body['refresh'], httponly=True, secure=secure_flag,
                                samesite='Strict', path='/', max_age=refresh_max_age, domain=cookie_domain)
    except Exception:
        logger.exception("Failed to set admin auth cookies")

    return response
@api_view(['POST', 'OPTIONS'])
@permission_classes([AllowAny])
@csrf_exempt
def logout_view(request):
    """Secure logout endpoint that clears all auth cookies and blacklists tokens"""
    
    # Handle OPTIONS request for CORS
    if request.method == 'OPTIONS':
        response = Response({})
        response['Content-Length'] = '0'
        return response
    
    # Attempt to blacklist the provided refresh token, but always clear cookies/session
    refresh_token = None
    try:
        refresh_token = request.data.get('refresh') if hasattr(request, 'data') else None
    except Exception:
        pass
    
    # Try fallback to cookies if no refresh token in body
    if not refresh_token:
        try:
            refresh_token = request.COOKIES.get('refresh_token')
        except Exception:
            pass
    
    token_error = None
    if refresh_token:
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError as e:
            token_error = e
        except Exception:
            # Best-effort blacklist; ignore other errors but log if available
            try:
                logger.exception('Unexpected error while blacklisting refresh token')
            except Exception:
                pass

    # Build response and clear cookies - ALWAYS return 200 on logout for security
    # (don't reveal whether token was valid or not)
    resp_body = {'message': 'Successfully logged out', 'success': True}
    response = Response(resp_body, status=200)

    # Delete cookies set during login (all HttpOnly)
    # CRITICAL: Must use set_cookie with max_age=0 and EXACT same parameters as when created
    # delete_cookie() doesn't work properly for HttpOnly cookies
    try:
        secure_flag = not settings.DEBUG
        cookie_domain = getattr(settings, 'COOKIE_DOMAIN', None)
        
        # All auth and user metadata cookies are HttpOnly - MUST match login parameters exactly
        all_cookies = [
            'jwt_token', 'access_token', 'accessToken', 
            'refresh_token', 'refreshToken',
            'userName', 'userEmail', 'userRole', 'user_role', 'UserRole', 
            'current_page', 'themeMode', 'login_verification_pending', 
            'role', 'admin_app_loaded',
            'sessionid', 'csrftoken',  # Django session cookies
            'user_name', 'username'     # Fallback name cookies
        ]
        
        for name in all_cookies:
            try:
                response.set_cookie(
                    name,
                    '',
                    httponly=True,
                    secure=secure_flag,
                    samesite='Strict',
                    path='/',
                    max_age=0,
                    domain=cookie_domain
                )
            except Exception:
                pass
    except Exception:
        try:
            logger.exception('Failed to delete logout cookies')
        except Exception:
            pass

    # Clear server-side session if present
    try:
        if hasattr(request, 'session'):
            request.session.flush()
    except Exception:
        try:
            logger.exception('Failed to flush session on logout')
        except Exception:
            pass

    return response


@api_view(['POST', 'GET'])
@permission_classes([AllowAny])
@csrf_exempt
def validate_token_view(request):
    """Validate JWT token and return user info"""
    try:
        # Get token from different sources
        token = None
        
        if request.method == 'GET':
            # For GET requests, check Authorization header
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
        else:
            # For POST requests, check request body
            token = request.data.get('token')
            if not token:
                # Also check Authorization header for POST
                auth_header = request.headers.get('Authorization', '')
                if auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]
        
        if not token:
            return Response({'error': 'No token provided'}, status=400)
        
        # Validate token
        try:
            decoded_token = UntypedToken(token)
            user_id = decoded_token.get('user_id')
            
            # Get user info
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.get(id=user_id)
            
            return Response({
                'valid': True,
                'message': 'Token is valid',
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'name': user.get_full_name() or user.username or user.email.split('@')[0],
                    'role': getattr(user, 'manager_admin_status', 'User'),
                    'is_superuser': user.is_superuser
                }
            }, status=200)
            
        except (InvalidToken, TokenError) as e:
            return Response({'valid': False, 'error': f'Invalid token: {str(e)}'}, status=401)
        except Exception as e:
            return Response({'error': f'Token validation error: {str(e)}'}, status=500)
            
    except Exception as e:
        return Response({'error': f'Validation error: {str(e)}'}, status=500)


@api_view(['POST'])
@permission_classes([AllowAny])
@csrf_exempt
def create_server_settings_view(request):
    """Create default MT5 server settings"""
    try:
        from adminPanel.models import ServerSetting
        from django.utils import timezone
        
        # Check if settings already exist
        if ServerSetting.objects.exists():
            setting = ServerSetting.objects.first()
            return Response({
                'message': 'ServerSetting already exists',
                'setting': {
                    'id': setting.id,
                    'server_ip': setting.server_ip,
                    'server_name': setting.server_name,
                    'login_id': setting.login_id
                }
            }, status=200)
        
        # Create new settings
        setting = ServerSetting.objects.create(
            server_ip="127.0.0.1",
            server_name="MT5 Demo Server",
            login_id=1000,
            server_password="password123"
        )
        
        return Response({
            'message': 'ServerSetting created successfully',
            'setting': {
                'id': setting.id,
                'server_ip': setting.server_ip,
                'server_name': setting.server_name,
                'login_id': setting.login_id
            }
        }, status=201)
        
    except Exception as e:
        return Response({
            'error': 'Failed to create server settings',
            'details': str(e)
        }, status=500)


@api_view(['GET'])
@permission_classes([AllowAny])
def api_status_view(request):
    """API status check endpoint"""
    try:
        from adminPanel.models import ServerSetting
        from django.utils import timezone
        
        # Check server settings
        server_settings_count = ServerSetting.objects.count()
        
        # Check database connection
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            db_status = "OK"
        
        return Response({
            'status': 'OK',
            'timestamp': timezone.now().isoformat(),
            'database': db_status,
            'server_settings_count': server_settings_count,
            'api_version': '1.0'
        }, status=200)
        
    except Exception as e:
        return Response({
            'status': 'ERROR',
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=500)


@api_view(['POST', 'OPTIONS'])
@permission_classes([AllowAny])
@csrf_exempt
def token_refresh_view(request):
    """Proper JWT token refresh endpoint"""
    
    # Handle OPTIONS request for CORS
    if request.method == 'OPTIONS':
        response = Response({})
        response['Content-Length'] = '0'
        return response
    
    try:
        # Get refresh token from request data
        refresh_token = None
        
        # Try to get from DRF request.data first
        if hasattr(request, 'data') and request.data:
            refresh_token = request.data.get('refresh')
        
        # Fallback to parsing JSON body manually. Try strict JSON first,
        # then fall back to Python-literal parsing (handles single quotes)
        if not refresh_token and request.body:
            raw = None
            try:
                raw = request.body.decode('utf-8')
            except Exception:
                try:
                    raw = request.body.decode('utf-8', errors='replace')
                except Exception:
                    raw = None

            if raw:
                try:
                    data = json.loads(raw)
                    refresh_token = data.get('refresh')
                except json.JSONDecodeError:
                    try:
                        # Handle bodies like: {'refresh':'...'} (single quotes)
                        data = ast.literal_eval(raw)
                        if isinstance(data, dict):
                            refresh_token = data.get('refresh')
                    except Exception:
                        # Log raw body for debugging and continue
                        logger.debug('Invalid JSON in token_refresh_view body: %s', raw)
        
        # Final fallback to POST data
        if not refresh_token:
            refresh_token = request.POST.get('refresh')
        
        if not refresh_token:
            return Response({'error': 'Refresh token is required'}, status=400)
        
        try:
            # Create RefreshToken instance from the provided token (validates signature/exp)
            refresh = RefreshToken(refresh_token)

            # Obtain user id claim name from settings (fallback to 'user_id')
            user_id_claim = settings.SIMPLE_JWT.get('USER_ID_CLAIM', 'user_id')
            user_id = refresh.get(user_id_claim) or refresh.get('user_id')

            # Generate a new refresh token for the user (rotation)
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                user = User.objects.get(id=user_id)
            except Exception:
                return Response({'error': 'User not found for provided refresh token'}, status=401)

            # Create a fresh refresh token for the same user
            new_refresh = RefreshToken.for_user(user)
            # Preserve or set audience/scope: prefer preserving from old refresh when present
            try:
                aud = refresh.get('aud') or ('admin.vtindex' if (user.is_superuser or getattr(user, 'manager_admin_status', '') in ['Admin', 'Manager']) else 'client.vtindex')
                scope = refresh.get('scope') or ('admin:*' if (user.is_superuser or getattr(user, 'manager_admin_status', '') in ['Admin', 'Manager']) else 'client:*')
                new_refresh['aud'] = aud
                new_refresh['scope'] = scope
                new_refresh.access_token['aud'] = aud
                new_refresh.access_token['scope'] = scope
            except Exception:
                pass

            # Optionally match lifetimes from the existing token if needed (left as default)

            # Blacklist the old refresh token if token_blacklist app is available
            try:
                refresh.blacklist()
            except Exception:
                # If blacklisting isn't available or fails, continue but log
                logger.exception('Failed to blacklist old refresh token during rotation')

            # Return new access and refresh tokens
            # ensure the new access is recorded as an outstanding token so it can be blacklisted
            try:
                new_refresh.access_token.outstand()
            except Exception:
                logger.exception('Failed to create OutstandingToken for newly issued access (token_refresh_view)')
            new_access = str(new_refresh.access_token)
            new_refresh_str = str(new_refresh)

            return Response({
                'access': new_access,
                'refresh': new_refresh_str
            }, status=200)

        except TokenError as e:
            return Response({'error': f'Invalid refresh token: {str(e)}'}, status=401)
        except Exception as e:
            return Response({'error': f'Token refresh failed: {str(e)}'}, status=500)
            
    except Exception as e:
        return Response({'error': f'Request processing error: {str(e)}'}, status=500)


@api_view(['POST', 'OPTIONS'])
@permission_classes([AllowAny])
@csrf_exempt
def refresh_and_set_cookie_view(request):
    """Endpoint that rotates refresh token and sets secure HttpOnly cookies for client usage.
    Accepts `refresh` in JSON body or reads `refresh_token` cookie. Returns new access+refresh in JSON
    and sets cookies `jwt_token`, `access_token`, `refresh_token`.
    """
    if request.method == 'OPTIONS':
        resp = Response({})
        resp['Content-Length'] = '0'
        return resp

    # Parse refresh token from cookie or body
    refresh_token = None
    if request.COOKIES.get('refresh_token'):
        refresh_token = request.COOKIES.get('refresh_token')
    else:
        try:
            refresh_token = request.data.get('refresh') if hasattr(request, 'data') else None
        except Exception:
            refresh_token = None

    if not refresh_token:
        return Response({'error': 'Refresh token is required'}, status=400)

    try:
        refresh = RefreshToken(refresh_token)

        # build new refresh for user
        user_id_claim = settings.SIMPLE_JWT.get('USER_ID_CLAIM', 'user_id')
        user_id = refresh.get(user_id_claim) or refresh.get('user_id')
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except Exception:
            return Response({'error': 'User not found for provided refresh token'}, status=401)

        new_refresh = RefreshToken.for_user(user)
        try:
            # Try to preserve audience/scope from the incoming refresh, otherwise derive from user role
            aud = refresh.get('aud') or ('admin.vtindex' if (user.is_superuser or getattr(user, 'manager_admin_status', '') in ['Admin', 'Manager']) else 'client.vtindex')
            scope = refresh.get('scope') or ('admin:*' if (user.is_superuser or getattr(user, 'manager_admin_status', '') in ['Admin', 'Manager']) else 'client:*')
            new_refresh['aud'] = aud
            new_refresh['scope'] = scope
            new_refresh.access_token['aud'] = aud
            new_refresh.access_token['scope'] = scope
        except Exception:
            pass

        # blacklist old
        try:
            refresh.blacklist()
        except Exception:
            logger.exception('Failed to blacklist old refresh token during rotation (refresh_and_set_cookie_view)')

        # Always record the new access token as outstanding so it can be revoked later
        try:
            new_refresh.access_token.outstand()
        except Exception:
            logger.exception('Failed to create OutstandingToken for newly issued access (refresh_and_set_cookie_view)')

        new_access = str(new_refresh.access_token)
        new_refresh_str = str(new_refresh)

        # Prepare response and set cookies
        resp = Response({'access': new_access, 'refresh': new_refresh_str}, status=200)

        secure_flag = not settings.DEBUG
        try:
            # lifetimes
            try:
                refresh_lifetime = getattr(settings, 'SIMPLE_JWT', {}).get('REFRESH_TOKEN_LIFETIME', None)
                access_lifetime = getattr(settings, 'SIMPLE_JWT', {}).get('ACCESS_TOKEN_LIFETIME', None)
                refresh_max_age = int(refresh_lifetime.total_seconds()) if refresh_lifetime else None
                access_max_age = int(access_lifetime.total_seconds()) if access_lifetime else None
            except Exception:
                refresh_max_age = None
                access_max_age = None

            resp.set_cookie('jwt_token', new_access, httponly=True, secure=secure_flag, samesite='Strict', path='/', max_age=access_max_age)
            resp.set_cookie('access_token', new_access, httponly=True, secure=secure_flag, samesite='Strict', path='/', max_age=access_max_age)
            resp.set_cookie('accessToken', new_access, httponly=True, secure=secure_flag, samesite='Strict', path='/', max_age=access_max_age)
            resp.set_cookie('refresh_token', new_refresh_str, httponly=True, secure=secure_flag, samesite='Strict', path='/', max_age=refresh_max_age)
            resp.set_cookie('refreshToken', new_refresh_str, httponly=True, secure=secure_flag, samesite='Strict', path='/', max_age=refresh_max_age)
        except Exception:
            logger.exception('Failed to set auth cookies in refresh_and_set_cookie_view')

        return resp

    except TokenError as e:
        return Response({'error': f'Invalid refresh token: {str(e)}'}, status=401)
    except Exception as e:
        return Response({'error': f'Token refresh failed: {str(e)}'}, status=500)


@api_view(['GET'])
@permission_classes([AllowAny])
def public_key_view(request):
    """Return the public key PEM used for verifying RS* JWTs."""
    # Prefer verifying key loaded into SIMPLE_JWT (when settings use PEMs)
    verifying_key = getattr(settings, 'SIMPLE_JWT', {}).get('VERIFYING_KEY')
    if verifying_key:
        return HttpResponse(verifying_key, content_type='text/plain')

    # Fallback: check environment variable (as configured in brokerBackend.settings)
    pub_path = os.environ.get('JWT_PUBLIC_KEY_PATH', 'jwt_public.pem')
    p = pub_path if os.path.isabs(pub_path) else os.path.join(settings.BASE_DIR, pub_path)
    try:
        with open(p, 'r', encoding='utf-8') as f:
            pem = f.read()
        return HttpResponse(pem, content_type='text/plain')
    except Exception as e:
        logger.exception('Failed to read public key file for public_key_view: %s', e)
        return Response({'error': 'Public key not available'}, status=500)
