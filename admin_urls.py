from django.urls import path, re_path, include
from django.views.static import serve
from django.conf import settings
from django.conf.urls.static import static
from .views.admin_app_views import serve_admin_app
from .views.auth_views import login_view, logout_view, validate_token_view, api_status_view

# Add a simple test view to check authentication
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(['GET'])
def test_auth_view(request):
    """Test view to check authentication status"""
    # Include session debug info so we can verify session keys set during login
    session_info = {}
    try:
        session_info = {
            'user_id': request.session.get('user_id'),
            'user_email': request.session.get('user_email'),
            'user_name': request.session.get('user_name'),
            'role': request.session.get('role'),
            'is_manager': request.session.get('is_manager'),
            'is_superuser': request.session.get('is_superuser'),
            'expiry_age': request.session.get_expiry_age() if hasattr(request.session, 'get_expiry_age') else None
        }
    except Exception:
        session_info = {'error': 'session unavailable'}

    return Response({
        'authenticated': request.user.is_authenticated,
        'user': str(request.user) if request.user.is_authenticated else 'Anonymous',
        'is_superuser': getattr(request.user, 'is_superuser', False),
        'manager_admin_status': getattr(request.user, 'manager_admin_status', None),
        'session_key': request.session.session_key,
        'session': session_info
    })
from .views.user_views import list_users, check_kyc_status
from .views.views5 import ServerSettingsAPIView
from .views.views6 import dashboard_stats_view, dashboard_stats_view_public, recent_transactions_view_public, get_recent_withdrawals
from .views.transaction_views import (
    get_recent_deposits,
    get_recent_internal_transfers, 
    get_recent_withdrawals,
    admin_transactions_list
)
from .views.transaction_api import create_transaction, approve_transaction, transaction_summary
from .views.views import (
    get_ib_profiles, user_ib_status, get_user_transactions,
    user_bank_details, user_verification_status, get_demo_accounts, 
    update_demo_account, reset_demo_account
)
from .views.trading_views import trading_accounts_list, get_trading_accounts
from .views.views2 import upload_document, verify_document

# Verification Integration endpoints (NEW)
from .views.verification_integration import (
    get_verification_status,
    update_verification_status,
    get_pending_verifications,
    bulk_verification_update,
    get_client_verification_status,
    get_verification_analytics
)

# PAMM admin views removed (backend PAMM feature deleted)

urlpatterns = [
    # API endpoints FIRST (most specific patterns first)
    
    # Chat endpoints
    path('', include('brokerBackend.chat_urls')),
    
    # Auth endpoints
    path('api/login/', login_view, name='api-login'),
    path('api/logout/', logout_view, name='api-logout'),
    path('api/test-auth/', test_auth_view, name='api-test-auth'),
    
    # Trading Accounts API endpoint for admin subdomain
    path('admin-api/trading-accounts/', trading_accounts_list, name='api-trading-accounts-list'),
    
    # Transaction API endpoints for admin subdomain
    path('api/check-kyc-status/<int:user_id>/', check_kyc_status, name='api-check-kyc-status'),
    path('api/admin/transactions/', admin_transactions_list, name='api-admin-transactions'),
    path('api/admin/recent-deposits/', get_recent_deposits, name='api-admin-recent-deposits'),
    path('api/admin/recent-withdrawals/', get_recent_withdrawals, name='api-admin-recent-withdrawals'),
    path('api/admin/recent-transfers/', get_recent_internal_transfers, name='api-admin-recent-transfers'),
    path('api/status/', api_status_view, name='api-status'),
    
    # Dashboard and Statistics API (ADDED)
    path('api/dashboard/stats/', dashboard_stats_view, name='api-dashboard-stats'),
    path('api/recent-transactions/', get_recent_withdrawals, name='api-recent-transactions'),
    path('api/test/dashboard/stats/', dashboard_stats_view_public, name='api-test-dashboard-stats'),
    path('api/test/recent-transactions/', recent_transactions_view_public, name='api-test-recent-transactions'),
    
    # Server settings API endpoints
    path('api/server-settings/', ServerSettingsAPIView.as_view(), name='api-server-settings'),
    path('api/server-settings', ServerSettingsAPIView.as_view(), name='api-server-settings-no-slash'),
    
    # Document upload and verification endpoints
    path('api/upload-document/', upload_document, name='upload-document'),
    path('api/verify-document/<str:document_type>/', verify_document, name='verify-document'),
    
    # PAMM Admin endpoints removed (backend PAMM feature deleted)
    
    # Non-API endpoints (less specific patterns)
    # Users API endpoint for admin subdomain
    path('api/users/', list_users, name='list_users'),
    
    # Trading accounts API endpoint for admin subdomain
    # path('api/ib-user/<int:user_id>/trading-accounts/', get_trading_accounts, name='get-trading-accounts'),
    
    # NEW: Modal API endpoints
    path('api/ib-user/<int:user_id>/ib-profiles/', get_ib_profiles, name='get-ib-profiles'),
    path('api/ib-user/<int:user_id>/ib-status/', user_ib_status, name='user-ib-status'),
    path('api/ib-user/<int:user_id>/transactions/', get_user_transactions, name='get-user-transactions'),
    # NOTE: bank-details endpoint moved to user_details_views.py for better functionality
    # path('api/ib-user/<int:user_id>/bank-details/', user_bank_details, name='user-bank-details'),  # REMOVED - conflicts with new comprehensive view
    path('api/ib-user/<int:user_id>/verification/', user_verification_status, name='user-verification-status'),
    path('api/ib-user/<int:user_id>/demo-accounts/', get_demo_accounts, name='get-demo-accounts'),
    path('api/ib-user/<int:user_id>/demo-accounts/<str:account_number>/', update_demo_account, name='update-demo-account'),
    path('api/ib-user/<int:user_id>/demo-accounts/<str:account_number>/reset/', reset_demo_account, name='reset-demo-account'),
    
    # Legacy non-API ib-user routes (for backward compatibility with frontend)
    # path('ib-user/<int:user_id>/trading-accounts/', get_trading_accounts, name='get-trading-accounts-legacy'),
    path('ib-user/<int:user_id>/ib-profiles/', get_ib_profiles, name='get-ib-profiles-legacy'),
    path('ib-user/<int:user_id>/ib-status/', user_ib_status, name='user-ib-status-legacy'),
    path('ib-user/<int:user_id>/transactions/', get_user_transactions, name='get-user-transactions-legacy'),
    path('ib-user/<int:user_id>/verification/', user_verification_status, name='user-verification-status-legacy'),
    path('ib-user/<int:user_id>/demo-accounts/', get_demo_accounts, name='get-demo-accounts-legacy'),
    path('ib-user/<int:user_id>/demo-accounts/<str:account_number>/', update_demo_account, name='update-demo-account-legacy'),
    path('ib-user/<int:user_id>/demo-accounts/<str:account_number>/reset/', reset_demo_account, name='reset-demo-account-legacy'),
    
    # Static files
    re_path(r'^static/(?P<path>.*)$', serve, {
        'document_root': settings.STATIC_ROOT,
    }),
]

# Add static/media serving in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
