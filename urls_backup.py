import random
import string
import logging
import os
from django.http import HttpResponse

from django.urls import path, include, re_path
from django.conf.urls.static import static
from django.conf import settings
from django.utils import timezone
from django.utils.timezone import now
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.contrib.auth import authenticate
from django.views.decorators.csrf import csrf_exempt
from django.views.static import serve
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from django.db.models import Q

from adminPanel.mt5.services import MT5ManagerActions
from adminPanel.models import *
from adminPanel.serializers import *
from adminPanel.permissions import *
from adminPanel.decorators import role_required
from adminPanel.roles import UserRole

from .views.dashboard_views import (
    AdminDashboardView,
    ManagerDashboardView,
    ClientDashboardView
)
from .views.user_views import (
    list_admins_managers,
    get_admin_manager_details,
    ManageClientAssignmentsView
)
from .views.auth_views import login_view, logout_view, validate_token_view, create_server_settings_view, api_status_view
from .views.transaction_views import (
    transaction_history,
    transaction_details,
    transaction_approve,
    transaction_reject,
    get_recent_deposits,
    get_recent_internal_transfers,
    get_recent_withdrawals
)
from .views.history_views import (
    deposit_transactions, withdrawal_history,
    internal_transfer_transactions, credit_in_history, credit_out_history
)
from .views.partner_views import (
    get_partner_profile, update_partner_profile
)
from .views.views2 import commissioning_profiles_list, CreateCommissioningProfileView, UserProfileView
from .views.prop_trading_views import package_list_view, create_prop_trading_package
from .views.admin_app_views import serve_admin_app
from .views.trading_views import (
    trading_accounts_list,
    get_trading_accounts
)
from .views.trading_page_view import trading_accounts_page
from .views.views5 import ServerSettingsAPIView
from .views.views6 import dashboard_stats_view, dashboard_stats_view_public, recent_transactions_view_public
from .views.email_views import (
    BroadcastEmailView,
    SingleEmailView,
    GetActiveUsersEmailsView,
    send_test_email
)
from .views.views import create_user_view, list_users
from .views.unauthorized import UnauthorizedView
from .views.profile_views import get_user_profile
from .views.views9 import (
    IBRequestsView, UpdateIBRequestView, 
    BankDetailsRequestsView, ApproveBankDetailsRequestView, RejectBankDetailsRequestView,
    ProfileChangeRequestsView, ApproveProfileChangeRequestView, RejectProfileChangeRequestView,
    PendingWithdrawalRequestsView
)
from .views.views3 import (
    CommissionWithdrawView,
    CommissionWithdrawalHistoryView,
    CommissionWithdrawalHistoryUserView as CommissionWithdrawalHistoryUserViewV3
)
from .views.views8 import (
    CommissionWithdrawalHistoryUserView
)
from .views.views4 import SingleActivityLogView
# from .views.test_views import test_dashboard_stats_view, test_recent_transactions_view, test_user_profile_view

logger = logging.getLogger(__name__)

# URL patterns
from django.contrib.auth import views as auth_views

urlpatterns = [
    # ====== CRITICAL: ALL API ROUTES MUST BE FIRST ======
    # Auth endpoints (highest priority)
    path('api/login/', login_view, name='api-login'),
    path('api/logout/', logout_view, name='api-logout'),
    path('api/validate-token/', validate_token_view, name='api-validate-token'),
    
    # Commissioning profiles API (MUST be before catch-all)
    path('api/commissioning-profiles/', commissioning_profiles_list, name='api-commissioning-profiles'),
    path('api/create-commissioning-profile/', CreateCommissioningProfileView.as_view(), name='api-create-commissioning-profile'),
    
    # Other API endpoints
    path('api/user/profile/', get_user_profile, name='api-user-profile'),
    path('api/send-broadcast-email/', BroadcastEmailView.as_view(), name='api-send-broadcast-email'),
    path('api/send-single-email/', SingleEmailView.as_view(), name='api-send-single-email'),
    path('api/get-active-users-emails/', GetActiveUsersEmailsView.as_view(), name='api-get-active-users-emails'),
    path('api/send-test-email/', send_test_email, name='api-send-test-email'),
    path('api/dashboard/stats/', dashboard_stats_view, name='api-dashboard-stats'),
    path('api/recent-transactions/', get_recent_withdrawals, name='api-recent-transactions'),
    path('api/test/dashboard/stats/', dashboard_stats_view_public, name='api-test-dashboard-stats'),
    path('api/test/recent-transactions/', recent_transactions_view_public, name='api-test-recent-transactions'),
    path('api/server-settings/', ServerSettingsAPIView.as_view(), name='api-server-settings'),
    path('api/create-server-settings/', create_server_settings_view, name='api-create-server-settings'),
    path('api/status/', api_status_view, name='api-status'),
    
    # Pending requests endpoints
    path('api/admin/ib-requests/', IBRequestsView.as_view(), name='ib-requests'),
    path('api/admin/ib-request/<int:id>/', UpdateIBRequestView.as_view(), name='update-ib-request'),
    path('api/admin/bank-detail-requests/', BankDetailsRequestsView.as_view(), name='bank-detail-requests'),
    path('api/admin/bank-detail-request/<int:id>/approve/', ApproveBankDetailsRequestView.as_view(), name='approve-bank-detail-request'),
    path('api/admin/bank-detail-request/<int:id>/reject/', RejectBankDetailsRequestView.as_view(), name='reject-bank-detail-request'),
    path('api/admin/profile-change-requests/', ProfileChangeRequestsView.as_view(), name='profile-change-requests'),
    path('api/admin/profile-change-request/<int:id>/approve/', ApproveProfileChangeRequestView.as_view(), name='approve-profile-change-request'),
    path('api/admin/profile-change-request/<int:id>/reject/', RejectProfileChangeRequestView.as_view(), name='reject-profile-change-request'),
    
    # Commission withdrawal endpoints
    path('api/admin/commission-withdraw/<int:user_id>/', CommissionWithdrawView.as_view(), name='commission-withdraw-user'),
    path('api/admin/commission-withdraw/', CommissionWithdrawView.as_view(), name='commission-withdraw'),
    path('api/admin/commission-withdrawal-history/', CommissionWithdrawalHistoryView.as_view(), name='commission-withdrawal-history'),
    path('api/admin/commission-withdrawal-history/<int:user_id>/', CommissionWithdrawalHistoryUserView.as_view(), name='commission-withdrawal-history-user'),
    path('api/admin/pending-withdrawal-requests/', PendingWithdrawalRequestsView.as_view(), name='pending-withdrawal-requests'),
    
    # ====== END OF API ROUTES ======
    
    # Static files
    re_path(r'^static/(?P<path>.*)$', serve, {
        'document_root': settings.STATIC_ROOT,
    }),
    path('', serve_admin_app, name='admin-home'),
    
    # Auth endpoints
    path('login/', auth_views.LoginView.as_view(template_name='admin/index.html'), name='index'),
    path('api/login/', login_view, name='api-login'),
    path('api/logout/', logout_view, name='api-logout'),
    path('api/validate-token/', validate_token_view, name='api-validate-token'),
    
    # User profile endpoint
    path('api/user/profile/', get_user_profile, name='api-user-profile'),
    
    # Email API endpoints
    path('api/send-broadcast-email/', BroadcastEmailView.as_view(), name='api-send-broadcast-email'),
    path('api/send-single-email/', SingleEmailView.as_view(), name='api-send-single-email'),
    path('api/get-active-users-emails/', GetActiveUsersEmailsView.as_view(), name='api-get-active-users-emails'),
    path('api/send-test-email/', send_test_email, name='api-send-test-email'),
    
    # Dashboard stats endpoint
    path('api/dashboard/stats/', dashboard_stats_view, name='api-dashboard-stats'),
    path('api/recent-transactions/', get_recent_withdrawals, name='api-recent-transactions'),  # Using recent withdrawals as a fallback
    
    # Test endpoints for dashboard (no authentication required)
    path('api/test/dashboard/stats/', dashboard_stats_view_public, name='api-test-dashboard-stats'),
    path('api/test/recent-transactions/', recent_transactions_view_public, name='api-test-recent-transactions'),
    
    # Server settings endpoints
    path('api/server-settings', ServerSettingsAPIView.as_view(), name='api-server-settings-no-slash'),  # Handle without slash first
    path('api/server-settings/', ServerSettingsAPIView.as_view(), name='api-server-settings'),
    path('api/create-server-settings/', create_server_settings_view, name='api-create-server-settings'),
    path('api/status/', api_status_view, name='api-status'),
    
    # Admin dashboard
    path('admin/dashboard/', AdminDashboardView.as_view(), name='admin-dashboard'),
    path('manager/dashboard/', ManagerDashboardView.as_view(), name='manager-dashboard'),
    path('client/dashboard/', ClientDashboardView.as_view(), name='client-dashboard'),
    path('unauthorized/', UnauthorizedView.as_view(), name='unauthorized'),
    
    # Client assignments management
    path('admin/manage-client-assignments/', ManageClientAssignmentsView.as_view(), name='manage-client-assignments'),

    # Authentication
    path('logout/', logout_view, name='logout'),
    path('validate-token/', validate_token_view, name='validate-token'),
    path('token/refresh/', validate_token_view, name='validate-token'),

    # User management
    path('users/', list_users, name='list_users'),
    path('create-user/', create_user_view, name='create_user'),
    path('admins-managers/', list_admins_managers, name='list_admins_managers'),
    path('admin-manager/<int:user_id>/', get_admin_manager_details, name='get_admin_manager_details'),
    
    # User details
    path('api/user/<int:user_id>/', UserProfileView.as_view(), name='api-user-details'),
    
    # Activity logs
    path('api/user/<int:user_id>/activity/', SingleActivityLogView.as_view(), name='api-user-activity'),

    # Transactions
    path('transactions/', transaction_history, name='transaction-history'),
    path('transaction/<int:transaction_id>/', transaction_details, name='transaction-details'),
    path('transaction/<int:transaction_id>/approve/', transaction_approve, name='transaction-approve'),
    path('transaction/<int:transaction_id>/reject/', transaction_reject, name='transaction-reject'),

    # Recent activities
    path('recent-deposits/', get_recent_deposits, name='get_recent_deposits'),
    path('recent-internal-transfers/', get_recent_internal_transfers, name='get_recent_internal_transfers'),
    path('recent-withdrawals/', get_recent_withdrawals, name='get_recent_withdrawals'),

    # History endpoints
    path('deposit-history/', deposit_transactions, name='deposit_history'),
    path('withdrawal-history/<int:user_id>/', withdrawal_history, name='withdrawal-history'),
    path('internal-transfer-history/', internal_transfer_transactions, name='internal_transfer_history'),
    path('credit-in-history/', credit_in_history, name='credit_in_history'),
    path('credit-out-history/', credit_out_history, name='credit_out_history'),

    # Trading accounts
    path('trading-accounts/', trading_accounts_page, name='trading_accounts'),
    path('admin-api/trading-accounts/', trading_accounts_list, name='api-trading-accounts-list'),
    # path('ib-user/<int:user_id>/trading-accounts/', get_trading_accounts, name='get-trading-accounts'),

    # IB/Partner management
    path('commissioning-profiles/', commissioning_profiles_list, name='commissioning-profiles-list'),
    path('partner-profile/<int:partner_id>/', get_partner_profile, name='get-partner-profile'),
    path('update-partner-profile/<int:partner_id>/', update_partner_profile, name='update-partner-profile'),

    # Prop trading
    path('prop-packages/', package_list_view, name='package_list'),
    path('create-prop-package/', create_prop_trading_package, name='create_prop_trading_package'),

    # Pending requests endpoints
    path('api/admin/ib-requests/', IBRequestsView.as_view(), name='ib-requests'),
    path('api/admin/ib-request/<int:id>/', UpdateIBRequestView.as_view(), name='update-ib-request'),
    path('api/admin/bank-detail-requests/', BankDetailsRequestsView.as_view(), name='bank-detail-requests'),
    path('api/admin/bank-detail-request/<int:id>/approve/', ApproveBankDetailsRequestView.as_view(), name='approve-bank-detail-request'),
    path('api/admin/bank-detail-request/<int:id>/reject/', RejectBankDetailsRequestView.as_view(), name='reject-bank-detail-request'),
    path('api/admin/profile-change-requests/', ProfileChangeRequestsView.as_view(), name='profile-change-requests'),
    path('api/admin/profile-change-request/<int:id>/approve/', ApproveProfileChangeRequestView.as_view(), name='approve-profile-change-request'),
    path('api/admin/profile-change-request/<int:id>/reject/', RejectProfileChangeRequestView.as_view(), name='reject-profile-change-request'),
    path('api/commissioning-profiles/', commissioning_profiles_list, name='api-commissioning-profiles'),
    path('api/create-commissioning-profile/', CreateCommissioningProfileView.as_view(), name='api-create-commissioning-profile'),

    # Commission withdrawal endpoints
    path('api/admin/commission-withdraw/<int:user_id>/', CommissionWithdrawView.as_view(), name='commission-withdraw-user'),
    path('api/admin/commission-withdraw/', CommissionWithdrawView.as_view(), name='commission-withdraw'),
    path('api/admin/commission-withdrawal-history/', CommissionWithdrawalHistoryView.as_view(), name='commission-withdrawal-history'),
    path('api/admin/commission-withdrawal-history/<int:user_id>/', CommissionWithdrawalHistoryUserView.as_view(), name='commission-withdrawal-history-user'),
    path('api/admin/pending-withdrawal-requests/', PendingWithdrawalRequestsView.as_view(), name='pending-withdrawal-requests'),

    # Static files
    re_path(r'^static/(?P<path>.*)$', serve, {
        'document_root': settings.STATIC_ROOT,
    }),

    # Catch all other paths to serve admin SPA (excluding client routes and API routes)
    # FIXED: More restrictive regex that ONLY matches specific admin pages
    re_path(r'^(?!client/|api/|static/)(?:admin/|manager/|dashboard/|login/|logout/|users/|transactions/|trading-accounts/|.*\.html)$', serve_admin_app),
]

# Add static/media serving in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

def generate_password(length=8):
    if length < 8:
        raise ValueError("Password length must be at least 8 characters.")
    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    special_chars = string.punctuation
    password = [
        random.choice(uppercase),
        random.choice(lowercase),
        random.choice(digits),
        random.choice(special_chars)
    ]
    all_chars = uppercase + lowercase + digits + special_chars
    password += random.choices(all_chars, k=length - len(password))
    random.shuffle(password)
    return ''.join(password)

def get_client_ip(request):
    """Get client IP address from request headers."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip

def send_deposit_email(user, transaction):
    subject = "Your Deposit Has Been Processed"
    html_message = render_to_string("emails/new_deposit.html", {
        "username": user.username,
        "account_id": transaction.trading_account.account_id,
        "deposit_amount": round(float(transaction.amount), 2),
        "transaction_id": transaction.id,
        "transaction_date": transaction.approved_at.strftime('%Y-%m-%d %H:%M:%S') if transaction.approved_at else "",
    })
    email = EmailMessage(
        subject=subject,
        body=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.content_subtype = "html"
    email.send()

def send_withdrawal_email(user, transaction):
    subject = "Your Withdrawal Has Been Processed"
    html_message = render_to_string("emails/withdrawal.html", {
        "username": user.username,
        "account_id": transaction.trading_account.account_id,
        "withdrawal_amount": round(float(transaction.amount), 2),
        "transaction_id": transaction.id,
        "transaction_date": transaction.approved_at.strftime('%Y-%m-%d %H:%M:%S') if transaction.approved_at else "",
    })
    email = EmailMessage(
        subject=subject,
        body=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.content_subtype = "html"
    email.send()

def send_ib_approval_email(user):
    """
    Sends an email to the user notifying them that their IB request has been approved.
    """
    subject = "Your IB Request Has Been Approved"
    html_message = render_to_string("emails/ib_approved.html", {
        "username": user.username,
    })
    email = EmailMessage(
        subject=subject,
        body=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.content_subtype = "html"
    email.send()

def serve_admin_app(request):
    try:
        static_file = os.path.join(settings.BASE_DIR, 'static', 'admin', 'index.html')
        with open(static_file, 'r') as file:
            return HttpResponse(file.read())
    except FileNotFoundError:
        return HttpResponse("Admin app not found.", status=404)

class AdminDashboardView(APIView):
    @role_required([UserRole.ADMIN.value])
    def get(self, request):
        # Only admins can access this
        return Response({"message": "Admin dashboard"})

class ManagerDashboardView(APIView):
    @role_required([UserRole.MANAGER.value])
    def get(self, request):
        # Only managers can access this
        return Response({"message": "Manager dashboard"})

class ClientDashboardView(APIView):
    @role_required([UserRole.CLIENT.value])
    def get(self, request):
        # Only clients can access this
        return Response({"message": "Client dashboard"})

# For views that allow multiple roles
class SharedView(APIView):
    @role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
    def get(self, request):
                # Both admins and managers can access this
        return Response({"message": "Shared view"})
