import random
import string
import logging
import os
from django.http import HttpResponse
from .views.views import change_leverage_info, change_leverage_update, demo_accounts_api_view, disable_demo_account, enable_demo_account
from .views.activity_api import activity_logs_client, activity_logs_staff, ib_clients_activity_logs, error_activity_logs
from django.http import JsonResponse

from django.urls import path, include, re_path
from django.contrib import admin
from .views.admin_profile_image import AdminUserProfileImageView
from django.conf.urls.static import static
from django.conf import settings
from django.contrib.auth import views as auth_views
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
from django.urls import path
from clientPanel.views import auth_views as client_auth_views

from .views.user_views import get_user_info, get_ib_user_bank_details

from adminPanel.mt5.services import MT5ManagerActions
from adminPanel.models import *
from adminPanel.serializers import *
from adminPanel.permissions import *
from .views.views3 import CommissionZeroView
from .views.commission_db_withdraw import CommissionDBWithdrawView
from adminPanel.decorators import role_required
from adminPanel.roles import UserRole

from .views.dashboard_views import (
    admin_dashboard_view,
    manager_dashboard_view,
    client_dashboard_view,
    dashboard_stats,
    recent_activity
)
from .views.dashboard_api_views import get_dashboard_data

# Import notification views
from .views.notification_views import (
    get_notifications,
    mark_notification_read,
    mark_all_notifications_read,
    delete_notification,
    get_unread_count,
    create_notification
)
from .views.user_views import (
    list_admins_managers,
    get_admin_manager_details,
    ManageClientAssignmentsView,
    get_user_info,
    update_user_status,
    list_ib_users
)
from .views.user_bank_details import UserBankDetailsView
from .views.admin_manager_views import (
    list_admin_managers,
    get_admin_manager_details as api_get_admin_manager_details,
    create_admin_manager,
    update_admin_manager,
    get_available_groups,
    test_available_groups,  # Add test endpoint
    debug_groups_status,  # Add debug endpoint
    current_group_config,  # Add current config endpoint
    update_trading_group,
    save_group_configuration,
    list_mam_managers
)
from clientPanel.views import auth_views as client_auth_views
from .views.auth_views import login_view, logout_view, validate_token_view, token_refresh_view, create_server_settings_view, api_status_view, refresh_and_set_cookie_view, public_key_view
from .views.debug_auth_view import AuthDebugView, auth_debug_public
from .views.dashboard_page_views import manager_dashboard_page, admin_dashboard_page
from .views.transaction_views import (
    transaction_history,
    transaction_details,
    transaction_approve,
    transaction_reject,
    get_recent_deposits,
    get_recent_internal_transfers,
    get_recent_withdrawals,
    admin_transactions_list,
    pending_deposits_view,
    pending_withdrawals_view,
    pending_transfers_view,
    transaction_details_api,
    approve_transaction_api,
    reject_transaction_api
)
from .views.history_views import (
    deposit_transactions, withdrawal_history,
    internal_transfer_transactions, credit_in_history, credit_out_history
)
from .views.partner_views import (
    get_partner_profile, update_partner_profile,
    disable_ib_user_view, enable_ib_user_view,
    ib_user_statistics_view
)
from .views.views2 import CreateCommissioningProfileView, UpdateCommissioningProfileView, UserProfileView, update_demo_account, get_available_trading_groups, get_available_trading_groups_non_demo, get_commission_profile_details
from .views.views import commissioning_profiles_list, get_ib_profiles, user_ib_status, get_user_transactions, user_verification_status, get_demo_accounts, reset_demo_account
from .views.prop_trading_views import package_list_view, create_prop_trading_package, approve_prop_request, reject_prop_request
from .views.admin_app_views import serve_admin_app
from .views.trading_views import (
    trading_accounts_list,
    get_trading_accounts
)
from .views.ib_commission_balance import get_ib_commission_balance
# Import the new view for trading account history and positions
from .views.trading_account_history import trading_account_history_view, trading_account_positions_view 
from .views.trading_page_view import trading_accounts_page
from .views.views5 import ServerSettingsAPIView, CommissionCreationView
from .views.mt5_refresh_view import RefreshMT5ConnectionAPIView
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
    DocumentRequestsView, ApproveDocumentRequestView, RejectDocumentRequestView,
    PendingWithdrawalRequestsView, CryptoDetailsRequestsView, ApproveCryptoDetailsView, 
    RejectCryptoDetailsView, PendingDepositRequestsView, PendingUSDTTransactionsView,
    ApproveTransactionView, RejectTransactionView,
    unapproved_users_list, ApproveUserView
)
from .views.views3 import (
    CommissionWithdrawView,
    CommissionWithdrawalHistoryView,
    CommissionWithdrawalHistoryUserView as CommissionWithdrawalHistoryUserViewV3,
    CreditInTransactionView,
    CreditOutView,
    ChangeLeverageView,
    EnableDisableTradingView,
    EnableDisableAccountView
)
from .views.views8 import (
    CommissionWithdrawalHistoryUserView,
    IBClientsListView,MAMInvestorView,
    MAMInvestmentDetailsView
)
from .views.views7 import (
    DepositView,
    WithdrawView,
    InternalTransferView,
    csrf_token_view,
    create_trading_account_view,
    create_demo_account_view,
    create_demo_account_view,
    ib_clients_deposit_transactions,
    ib_clients_withdrawal_transactions,
    ib_clients_internal_transfer_transactions
)
from .views.simple_transaction_views import (
    SimpleDepositView,
    SimpleWithdrawView
)
from .views.views4 import SingleActivityLogView, AvailableGroupsView, AvailableLeverageOptionsView, UpdateTradingGroupSettingsView, CurrentGroupConfigurationView, TestAvailableGroupsView
from .views.views5 import UpdateTradingGroupView
from .views.verification_integration import (
    get_verification_status,
    update_verification_status,
    get_pending_verifications,
    bulk_verification_update,
    get_client_verification_status,
    get_verification_analytics
)
from .views.user_details_views import (
    UserBankDetailsView,
    UserCryptoDetailsView,
    approve_user_bank_details,
    reject_user_bank_details,
    approve_user_crypto_details,
    reject_user_crypto_details
)
from .views.client_assignment_api import (
    assign_manager_clients_api,
    manager_client_stats_api,
    assign_specific_client_api,
    unassigned_clients_api,
    bulk_assign_clients_api
)
from .views.views import reset_leverage_demo_account, reset_balance_demo_account
# from .views.test_views import test_dashboard_stats_view, test_recent_transactions_view, test_user_profile_view

from .views.commission_details import commission_details_view
from .views.views4 import UserDetailView
# New: Import the new API view for listing accounts by type
from .views.mam_api_views import mam_accounts_list, investor_accounts_list
from .views.trading_account_api import ListAccountsByTypeView, InternalTransferSubmitView
from .views.export_views import (
    export_users_csv,
    export_trading_accounts_csv,
    export_transactions_csv,
)

from .views.ticket_views import TicketView, TicketDetailView


logger = logging.getLogger(__name__)

urlpatterns = [
    # Chat endpoints
    path('', include('brokerBackend.chat_urls')),
    # MT5 Webhook for instant commission creation (CRITICAL - must be accessible)
    path('api/v1/commission-creation/', CommissionCreationView, name='api-commission-creation-webhook'),
    
    # CSV export endpoints (admin only)
    path('api/export/users/csv/', export_users_csv, name='export-users-csv'),
    path('api/export/trading-accounts/csv/', export_trading_accounts_csv, name='export-trading-accounts-csv'),
    path('api/export/transactions/csv/', export_transactions_csv, name='export-transactions-csv'),
    # Note: Django admin is registered at the project root (brokerBackend.urls).
    # Avoid registering admin.site.urls here to prevent duplicate 'admin' namespace warnings.
    path('api/accounts/list-by-type/', ListAccountsByTypeView.as_view(), name='list-accounts-by-type'),
    path('api/accounts/internal-transfer/', InternalTransferSubmitView.as_view(), name='internal-transfer-submit'),
    # Other API routes
    path('api/activity/client-logs/', activity_logs_client, name='api-activity-client-logs'),
    path('api/activity/ib-clients/', ib_clients_activity_logs, name='api-activity-ib-clients'),
    path('api/activity/staff/', activity_logs_staff, name='api-activity-staff'),
    path('api/activity/error-logs/', error_activity_logs, name='api-activity-error-logs'),
    # User status update endpoint for frontend status toggle
    path('api/users/<int:user_id>/status/', update_user_status, name='api-user-status'),
    # ====== DASHBOARD API ROUTES ======
    path('api/dashboard/data/', get_dashboard_data, name='api-dashboard-data'),
    path('api/dashboard/activity/', recent_activity, name='api-dashboard-activity'),


    # === DEMO ACCOUNTS API ENDPOINT (for admin demo accounts table) ===
    path('api/demo_accounts/', demo_accounts_api_view, name='api-demo-accounts'),
    path('api/demo_accounts/<str:account_id>/reset_leverage/', reset_leverage_demo_account, name='reset-leverage-demo-account'),
    path('api/demo_accounts/<str:account_id>/reset_balance/', reset_balance_demo_account, name='reset-balance-demo-account'),
    path('api/demo_accounts/<str:account_id>/disable/', disable_demo_account, name='disable-demo-account'),
    path('api/demo_accounts/<str:account_id>/enable/', enable_demo_account, name='enable-demo-account'),

    # Admin: Get user profile image by email
    path('api/admin/user/profile-image/<str:email>/', AdminUserProfileImageView.as_view(), name='admin-user-profile-image'),

    # ====== ESSENTIAL TRANSACTION API ROUTES ======
    # Trading account history endpoint for modal
    re_path(r'^api/trading-account/(?P<account_id>\d+)/history/$', trading_account_history_view, name='trading_account_history'),
    # Simple transaction endpoints for testing (bypasses MT5)
    path('api/simple-deposit/', SimpleDepositView.as_view(), name='api-simple-deposit'),
    path('api/simple-withdraw/', SimpleWithdrawView.as_view(), name='api-simple-withdraw'),

    # Trading account positions endpoint (used by admin UI to fetch open positions)
    re_path(r'^api/trading-account/(?P<account_id>\d+)/positions/$', trading_account_positions_view, name='trading_account_positions'),
    
    # Primary API endpoints for admin transactions (RESTORED FOR FRONTEND CONNECTIVITY)
    path('api/admin/deposit/', DepositView.as_view(), name='api-admin-deposit'),
    path('api/admin/ib-clients-deposit/', ib_clients_deposit_transactions, name='api-ib-clients-deposit'),
    path('api/admin/withdraw/', WithdrawView.as_view(), name='api-admin-withdraw'),
    path('api/admin/ib-clients-withdraw/', ib_clients_withdrawal_transactions, name='api-ib-clients-withdraw'),
    path('api/admin/internal-transfer/', InternalTransferView.as_view(), name='api-admin-internal-transfer'),
    path('api/admin/ib-clients-internal-transfer/', ib_clients_internal_transfer_transactions, name='api-ib-clients-internal-transfer'),
    path('api/admin/credit-in/', CreditInTransactionView.as_view(), name='api-admin-credit-in'),
    path('api/admin/credit-out/', CreditOutView.as_view(), name='api-admin-credit-out'),
    path('api/admin/toggle-account-status/', EnableDisableAccountView.as_view(), name='api-admin-toggle-account-status'),
    path('api/admin/toggle-algo/', EnableDisableTradingView.as_view(), name='api-admin-toggle-algo'),
  
    
    # Alternative transaction routes for frontend compatibility
    path('api/transactions/deposit/', DepositView.as_view(), name='api-deposit'),
    path('api/transactions/withdraw/', WithdrawView.as_view(), name='api-withdraw'),
    path('api/transactions/credit-in/', CreditInTransactionView.as_view(), name='api-credit-in'),
    path('api/transactions/credit-out/', CreditOutView.as_view(), name='api-credit-out'),

    # Admin-api routes for backwards compatibility with existing frontend
    path('admin-api/transactions/deposit/', DepositView.as_view(), name='admin-api-deposit'),
    path('admin-api/transactions/withdraw/', WithdrawView.as_view(), name='admin-api-withdraw'),
    path('admin-api/transactions/credit-in/', CreditInTransactionView.as_view(), name='admin-api-credit-in'),
    path('admin-api/transactions/credit-out/', CreditOutView.as_view(), name='admin-api-credit-out'),
    path('admin-api/transactions/deposit/', DepositView.as_view(), name='admin-api-deposit'),
    path('admin-api/transactions/withdraw/', WithdrawView.as_view(), name='admin-api-withdraw'),
    path('admin-api/transactions/credit-in/', CreditInTransactionView.as_view(), name='admin-api-credit-in'),
    path('admin-api/transactions/credit-out/', CreditOutView.as_view(), name='admin-api-credit-out'),
    path('admin-api/create-demo-account/', create_demo_account_view, name='admin-api-create-demo-account'),
    
    # Admin Manager API endpoints
    path('api/admins-managers/', list_admin_managers, name='api-admins-managers-list'),
    # MAM / Investor listing endpoints
    path('api/mam-accounts/', mam_accounts_list, name='api-mam-accounts'),
    path('api/investor-accounts/', investor_accounts_list, name='api-investor-accounts'),
    path('api/admin-manager/<int:user_id>/', api_get_admin_manager_details, name='api-admin-manager-details'),
    path('api/create-admin-manager/', create_admin_manager, name='api-create-admin-manager'),
    
    # MAM investor endpoints
    path('api/mam-investors/', MAMInvestorView.as_view(), name='api-mam-investors'),
    path('api/mam-investors/<str:account_id>/', MAMInvestmentDetailsView.as_view(), name='api-mam-investor-detail'),
    path('api/mam-managers/', list_mam_managers, name='api-mam-managers'),
    path('api/admin-manager/<int:user_id>/', api_get_admin_manager_details, name='api-admin-manager-details'),
    path('api/create-admin-manager/', create_admin_manager, name='api-create-admin-manager'),
    path('api/admin-manager/<int:user_id>/update/', update_admin_manager, name='api-update-admin-manager'),
    
    # Client Assignment API endpoints (for IB-to-Manager assignments)
    path('api/admin/assign-manager-clients/', assign_manager_clients_api, name='api-assign-manager-clients'),
    path('api/admin/manager-client-stats/', manager_client_stats_api, name='api-manager-client-stats'),
    path('api/admin/manager-client-stats/<int:manager_id>/', manager_client_stats_api, name='api-manager-client-stats-detail'),
    path('api/admin/assign-specific-client/', assign_specific_client_api, name='api-assign-specific-client'),
    path('api/admin/unassigned-clients/', unassigned_clients_api, name='api-unassigned-clients'),
    path('api/admin/bulk-assign-clients/', bulk_assign_clients_api, name='api-bulk-assign-clients'),
    
    # Updated: Use the correct class-based view for trading group update
    # path('api/update-trading-group/',
    #      __import__('adminPanel.views.views5', fromlist=['UpdateTradingGroupView']).UpdateTradingGroupView.as_view(),
    #      name='api-update-trading-group'),
    path('api/save-group-configuration/', save_group_configuration, name='api-save-group-configuration'),
    
    # ====== ALL OTHER API ROUTES ======
    # Auth endpoints (highest priority)
    path('api/login/', login_view, name='api-login'),
    path('api/logout/', logout_view, name='api-logout'),
    path('api/validate-token/', validate_token_view, name='api-validate-token'),
    path('api/token/refresh/', token_refresh_view, name='api-token-refresh'),
    path('api/refresh-and-set/', refresh_and_set_cookie_view, name='api-refresh-and-set'),
    path('api/public_key/', public_key_view, name='api-public-key'),
    path('api/csrf/', csrf_token_view, name='api-csrf-token'),  # CSRF token endpoint
    path('api/verify-otp/', csrf_exempt(client_auth_views.VerifyOtpView.as_view()), name='api-verify-otp'),
    path('api/resend-login-otp/', csrf_exempt(client_auth_views.resend_login_otp_view), name='api-resend-login-otp'),
    path('api/login-otp-status/', csrf_exempt(client_auth_views.login_otp_status_view), name='api-login-otp-status'),
    # Forgot password endpoints (for admin reset password feature)
    path('api/send-reset-otp/', csrf_exempt(client_auth_views.send_reset_otp_view), name='api-send-reset-otp'),
    path('api/reset-password/', csrf_exempt(client_auth_views.confirm_reset_password_view), name='api-reset-password'),
    # Client API prefix for compatibility
    path('client/api/send-reset-otp/', csrf_exempt(client_auth_views.send_reset_otp_view), name='client-api-send-reset-otp'),
    path('client/api/verify-otp/', csrf_exempt(client_auth_views.VerifyOtpView.as_view()), name='client-api-verify-otp'),
    path('client/api/reset-password/', csrf_exempt(client_auth_views.confirm_reset_password_view), name='client-api-reset-password'),
    
    # Client session management
    
    # TEST ENDPOINT - TEMPORARY
    path('api/test/', lambda request: __import__('django.http', fromlist=['JsonResponse']).JsonResponse({"test": "success", "path": request.path}), name='api-test'),
    
      # Commissioning profiles API (RESTORED WITH ORIGINAL VIEW)
    path('api/commissioning-profiles/', commissioning_profiles_list, name='api-commissioning-profiles'),
    path('api/commissioning-profiles/<int:profile_id>/', UpdateCommissioningProfileView.as_view(), name='api-update-commissioning-profile'),
    path('api/commissioning-profiles/<int:profile_id>/details/', get_commission_profile_details, name='api-commission-profile-details'),
    path('api/create-commissioning-profile/', CreateCommissioningProfileView.as_view(), name='api-create-commissioning-profile'),
    path('api/trading-groups/', get_available_trading_groups, name='api-trading-groups'),
    path('api/trading-groups-non-demo/', get_available_trading_groups_non_demo, name='trading-groups-non-demo'),
    
    path('api/profile/', get_user_profile, name='api-profile'),
    # User and Profile API endpoints - Enhanced for client connectivity
    path('api/user/profile/', get_user_profile, name='api-user-profile'),
    # path('api/user/<int:user_id>/', UserProfileView.as_view(), name='api-user-details'),
    path('api/user/<int:user_id>/activity/', SingleActivityLogView.as_view(), name='api-user-activity'),
    path('api/users/', list_users, name='api-users-list'),
    path('api/admin/users/', list_users, name='api-admin-users'),
    # IB-only user list endpoint
    path('api/admin/ib-users/', list_ib_users, name='api-admin-ib-users'),
    # Find user by email (exact match)
    path('api/admin/find-user-by-email/', __import__('adminPanel.views.email_lookup', fromlist=['find_user_by_email']).find_user_by_email, name='api-find-user-by-email'),
    path('api/user/<int:user_id>/', UserDetailView.as_view(), name='api-user-details'),

    # === MISSING IB USER ENDPOINTS (for admin partner sub-functions) ===
    path('api/admin/ib-user/<int:user_id>/history/', lambda request, user_id: __import__('django.http', fromlist=['JsonResponse']).JsonResponse([{'date': '2025-07-20', 'action': 'Test Action', 'amount': 0}], safe=False), name='api-admin-ib-user-history'),
    path('api/admin/ib-user/<int:user_id>/statistics/', ib_user_statistics_view, name='api-admin-ib-user-statistics'),
    path('api/admin/ib-users/<int:user_id>/disable/', disable_ib_user_view, name='api-admin-ib-users-disable'),
    path('api/admin/ib-users/<int:user_id>/enable/', enable_ib_user_view, name='api-admin-ib-users-enable'),
    path('api/admin/ib-users/<int:user_id>/clients/', IBClientsListView.as_view(), name='api-admin-ib-users-clients'),
    path('api/client/profile/', get_user_profile, name='api-client-profile'),
    path('api/admin/ib-users/<int:user_id>/commission-details/', commission_details_view, name='api-admin-commission-details'),
    # Admin: raw commission transactions list (used by admin partnership UI)
    path('api/admin/ib-users/<int:user_id>/commission-transactions/', __import__('adminPanel.views.admin_commission_transactions', fromlist=['admin_commission_transactions_view']).admin_commission_transactions_view, name='api-admin-commission-transactions'),


    # Client user info endpoints for admin panel
    path('api/admin/user-info/<int:user_id>/', get_user_info, name='admin-api-user-info'),
    path('api/admin/update-user-status/<int:user_id>/', update_user_status, name='admin-api-update-user-status'),
    
    # Email API endpoints
    path('api/send-broadcast-email/', BroadcastEmailView.as_view(), name='api-send-broadcast-email'),
    path('api/send-single-email/', SingleEmailView.as_view(), name='api-send-single-email'),
    path('api/get-active-users-emails/', GetActiveUsersEmailsView.as_view(), name='api-get-active-users-emails'),
    path('api/send-test-email/', send_test_email, name='api-send-test-email'),
    
    # Dashboard and Statistics API
    path('api/dashboard/stats/', dashboard_stats_view, name='api-dashboard-stats'),
    path('api/recent-transactions/', get_recent_withdrawals, name='api-recent-transactions'),
    path('api/admin/transactions/', admin_transactions_list, name='api-admin-transactions'),
    path('api/admin/recent-deposits/', get_recent_deposits, name='api-admin-recent-deposits'),
    path('api/admin/recent-withdrawals/', get_recent_withdrawals, name='api-admin-recent-withdrawals'),
    path('api/admin/recent-transfers/', get_recent_internal_transfers, name='api-admin-recent-transfers'),
    path('api/test/dashboard/stats/', dashboard_stats_view_public, name='api-test-dashboard-stats'),
    path('api/test/recent-transactions/', recent_transactions_view_public, name='api-test-recent-transactions'),
    
    # Server settings API
    path('api/server-settings/', ServerSettingsAPIView.as_view(), name='api-server-settings'),
    path('api/server-settings', ServerSettingsAPIView.as_view(), name='api-server-settings-no-slash'),
    path('api/refresh-mt5-connection/', RefreshMT5ConnectionAPIView.as_view(), name='api-refresh-mt5-connection'),
    path('api/create-server-settings/', create_server_settings_view, name='api-create-server-settings'),
    path('api/status/', api_status_view, name='api-status'),
    
    # Trading accounts API - Enhanced for full connectivity
    path('admin-api/trading-accounts/', trading_accounts_list, name='api-trading-accounts-list'),
    path('api/trading-accounts/', trading_accounts_list, name='api-trading-accounts'),
    path('api/admin/trading-accounts/', trading_accounts_list, name='api-admin-trading-accounts'),
    path('api/available-groups/', AvailableGroupsView.as_view(), name='api-available-groups'),
    path('api/test-groups/', TestAvailableGroupsView.as_view(), name='api-test-groups'),
    path('api/debug-groups-status/', debug_groups_status, name='api-debug-groups-status'),
    path('api/current-group-config/', current_group_config, name='api-current-group-config-function'),
    path('api/available-leverage/', AvailableLeverageOptionsView.as_view(), name='api-available-leverage'),
    # IMPORTANT: This endpoint updates group settings in the database, NOT account group assignment
    path('api/update-trading-group-settings/', UpdateTradingGroupSettingsView.as_view(), name='api-update-trading-group-settings'),
    # This endpoint updates the trading group for a specific account in MT5
    path('api/update-trading-group/', UpdateTradingGroupView.as_view(), name='api-update-trading-group'),
    path('api/current-group-config-class/', CurrentGroupConfigurationView.as_view(), name='api-current-group-config'),
    
    # Trading account creation endpoints
    path('api/create-trading-account/', create_trading_account_view, name='api-create-trading-account'),
    path('client/create-trading-account/', create_trading_account_view, name='client-create-trading-account'),
    path('api/create-demo-account/', create_demo_account_view, name='api-create-demo-account'),
    path('client/create-demo-account/', create_demo_account_view, name='client-create-demo-account'),
    path('api/update-demo-account/', update_demo_account, name='api-update-demo-account'),
    
    # MT5 Integration API endpoints
    path('api/mt5/accounts/', trading_accounts_list, name='api-mt5-accounts'),
    path('api/mt5/status/', api_status_view, name='api-mt5-status'),
    
    path('api/admin/unapproved-users/', unapproved_users_list, name='unapproved-users'),
    path('api/admin/users/<int:id>/approve/', ApproveUserView.as_view(), name='approve-user'),
    # Admin requests and pending approvals API
    path('api/admin/ib-requests/', IBRequestsView.as_view(), name='ib-requests'),
    path('api/admin/ib-request/<int:id>/', UpdateIBRequestView.as_view(), name='update-ib-request'),
    path('api/admin/bank-detail-requests/', BankDetailsRequestsView.as_view(), name='bank-detail-requests'),
    path('api/admin/bank-detail-request/<int:id>/approve/', ApproveBankDetailsRequestView.as_view(), name='approve-bank-detail-request'),
    path('api/admin/bank-detail-request/<int:id>/reject/', RejectBankDetailsRequestView.as_view(), name='reject-bank-detail-request'),
    path('api/admin/profile-change-requests/', ProfileChangeRequestsView.as_view(), name='profile-change-requests'),
    path('api/admin/profile-change-request/<str:id>/approve/', ApproveProfileChangeRequestView.as_view(), name='approve-profile-change-request'),
    path('api/admin/profile-change-request/<str:id>/reject/', RejectProfileChangeRequestView.as_view(), name='reject-profile-change-request'),
   
    path('api/admin/document-requests/', DocumentRequestsView.as_view(), name='document-requests'),
    path('api/admin/document-request/<int:id>/approve/', ApproveDocumentRequestView.as_view(), name='approve-document-request'),
    path('api/admin/document-request/<int:id>/reject/', RejectDocumentRequestView.as_view(), name='reject-document-request'),
    
    path('api/admin/crypto-details/', CryptoDetailsRequestsView.as_view(), name='crypto-details-requests'),
    path('api/admin/crypto-detail/<int:id>/approve/', ApproveCryptoDetailsView.as_view(), name='approve-crypto-detail'),
    path('api/admin/crypto-detail/<int:id>/reject/', RejectCryptoDetailsView.as_view(), name='reject-crypto-detail'),
    path('api/admin/pending-deposit-requests/', PendingDepositRequestsView.as_view(), name='pending-deposit-requests'),
    path('api/admin/pending-usdt-transactions/', PendingUSDTTransactionsView.as_view(), name='pending-usdt-transactions'),
    path('api/admin/transaction/<int:id>/approve/', ApproveTransactionView.as_view(), name='approve-transaction'),
    path('api/admin/transaction/<int:id>/reject/', RejectTransactionView.as_view(), name='reject-transaction'),
    

    # Pending transactions API endpoints
    path('api/admin/pending-deposits/', pending_deposits_view, name='api-pending-deposits'),
    path('api/admin/pending-withdrawals/', pending_withdrawals_view, name='api-pending-withdrawals'),
    path('api/admin/pending-transfers/', pending_transfers_view, name='api-pending-transfers'),
    path('api/admin/transaction-details/<int:transaction_id>/', transaction_details_api, name='api-transaction-details'),
    path('api/admin/approve-transaction/', approve_transaction_api, name='api-approve-transaction'),
    path('api/admin/reject-transaction/', reject_transaction_api, name='api-reject-transaction'),
    

    # Commission withdrawal API endpoints
    path('api/admin/commission-withdraw/<int:user_id>/', CommissionWithdrawView.as_view(), name='commission-withdraw-user'),
    path('api/admin/commission-withdraw/', CommissionWithdrawView.as_view(), name='commission-withdraw'),
    # Admin endpoint to zero a user's withdrawable commission without MT5 deposit
    path('api/admin/commission-zero/', CommissionZeroView.as_view(), name='commission-zero'),
    # Admin endpoint for database-only commission withdrawal (specific amount)
    path('api/admin/commission-db-withdraw/', CommissionDBWithdrawView.as_view(), name='commission-db-withdraw'),
    
    path('api/admin/commission-withdrawal-history/', CommissionWithdrawalHistoryView.as_view(), name='commission-withdrawal-history'),
    path('api/admin/commission-withdrawal-history/<int:user_id>/', CommissionWithdrawalHistoryUserView.as_view(), name='commission-withdrawal-history-user'),
    path('api/admin/pending-withdrawal-requests/', PendingWithdrawalRequestsView.as_view(), name='pending-withdrawal-requests'),
    
    # Trading account operations API endpoints (legacy admin paths)
    path('admin/deposit/', DepositView.as_view(), name='admin-deposit'),
    path('admin/withdraw/', WithdrawView.as_view(), name='admin-withdraw'),
    path('admin/credit-in/', CreditInTransactionView.as_view(), name='admin-credit-in'),
    path('admin/credit-out/', CreditOutView.as_view(), name='admin-credit-out'),
    # ChangeLeverageView: GET with account_id as query param, POST for update
    path('admin/change-leverage/', ChangeLeverageView.as_view(), name='admin-change-leverage'),
    path('admin/change-leverage/<int:account_id>/', ChangeLeverageView.as_view(), name='admin-change-leverage-detail'),
    path('admin/toggle-algo/', EnableDisableTradingView.as_view(), name='admin-toggle-algo'),
    path('admin/toggle-account-status/', EnableDisableAccountView.as_view(), name='admin-toggle-account-status'),
    path('admin/internal-transfer/', InternalTransferView.as_view(), name='admin-internal-transfer'),
    path('api/admin/internal-transfer/', InternalTransferView.as_view(), name='api-admin-internal-transfer'),

    path('api/admin/change-leverage/<int:account_id>/', change_leverage_info, name='change_leverage_info'),
    

    # ====== END OF API ROUTES ======
    
    # Verification Integration API endpoints (NEW - moved here for proper URL resolution)
    path('api/admin/verification/status/<int:user_id>/', get_verification_status, name='api-verification-status'),
    path('api/admin/verification/update/<int:user_id>/', update_verification_status, name='api-verification-update'),
    path('api/admin/verification/pending/', get_pending_verifications, name='api-verification-pending'),
    path('api/admin/verification/bulk-update/', bulk_verification_update, name='api-verification-bulk-update'),
    path('api/admin/verification/analytics/', get_verification_analytics, name='api-verification-analytics'),
    path('api/client/verification-status/', get_client_verification_status, name='api-client-verification-status'),
    
    # Include additional admin URLs (verification integration, etc.)
    path('', include('adminPanel.admin_urls')),
    # ======================================
    # Tickets API (legacy frontend compatibility) - must be registered BEFORE the SPA catch-all
	# Backwards-compatible create endpoint used by older frontend bundles
    path('api/tickets/create/', TicketView.as_view(), name='ticket-create'),
    path('api/tickets/', TicketView.as_view(), name='tickets'),
    path('api/tickets/<int:ticket_id>/', TicketDetailView.as_view(), name='ticket-detail'),
    path('tickets/<int:ticket_id>/', TicketDetailView.as_view(), name='ticket-detail'),

    # Admin dashboard pages (HTML views, not API)
    path('admin/dashboard/', admin_dashboard_page, name='admin-dashboard-page'),
    path('manager/dashboard/', manager_dashboard_page, name='manager-dashboard-page'),
    
    # Dashboard API endpoints (for AJAX calls)
    path('api/admin/dashboard/', admin_dashboard_view, name='admin-dashboard-api'),
    path('api/manager/dashboard/', manager_dashboard_view, name='manager-dashboard-api'),
    path('api/client/dashboard/', client_dashboard_view, name='client-dashboard-api'),
    path('unauthorized/', UnauthorizedView.as_view(), name='unauthorized'),
    
    # Debug authentication endpoints
    path('api/auth-debug/', AuthDebugView.as_view(), name='auth-debug'),
    path('api/auth-debug-public/', auth_debug_public, name='auth-debug-public'),

    # Notification API endpoints
    path('client/notifications/', get_notifications, name='client-notifications'),
    path('client/notifications/<int:notification_id>/mark-read/', mark_notification_read, name='mark-notification-read'),
    path('client/notifications/mark-all-read/', mark_all_notifications_read, name='mark-all-notifications-read'),
    path('client/notifications/<int:notification_id>/delete/', delete_notification, name='delete-notification'),
    path('client/notifications/unread-count/', get_unread_count, name='notification-unread-count'),
    path('client/notifications/create/', create_notification, name='create-notification'),
  
    
    # Client assignments management
    path('admin/manage-client-assignments/', ManageClientAssignmentsView.as_view(), name='manage-client-assignments'),

    # Authentication pages - serve the admin SPA for login (SPA handles auth client-side)
    path('login/', serve_admin_app, name='index'),
    path('logout/', logout_view, name='logout'),
    path('validate-token/', validate_token_view, name='validate-token'),
    path('token/refresh/', token_refresh_view, name='token-refresh'),

    # User management pages
    path('users/', list_users, name='list_users'),
    path('users/<int:user_id>/', get_user_info, name='get_user_info'),
    path('create-user/', create_user_view, name='create_user'),
    path('api/admin/create-user/', create_user_view, name='api-create-user'),
    path('admins-managers/', list_admins_managers, name='list_admins_managers'),
    path('admin-manager/<int:user_id>/', get_admin_manager_details, name='get_admin_manager_details'),

    # Transaction pages
    path('transactions/', transaction_history, name='transaction-history'),
    path('transaction/<int:transaction_id>/', transaction_details, name='transaction-details'),
    path('transaction/<int:transaction_id>/approve/', transaction_approve, name='transaction-approve'),
    path('transaction/<int:transaction_id>/reject/', transaction_reject, name='transaction-reject'),
    

    # Recent activities pages
    path('recent-deposits/', get_recent_deposits, name='get_recent_deposits'),
    path('recent-internal-transfers/', get_recent_internal_transfers, name='get_recent_internal_transfers'),
    path('recent-withdrawals/', get_recent_withdrawals, name='get_recent_withdrawals'),

    # History pages
    path('deposit-history/', deposit_transactions, name='deposit_history'),
    path('withdrawal-history/<int:user_id>/', withdrawal_history, name='withdrawal-history'),
    path('internal-transfer-history/', internal_transfer_transactions, name='internal_transfer_history'),
    path('credit-in-history/', credit_in_history, name='credit_in_history'),
    path('credit-out-history/', credit_out_history, name='credit_out_history'),

    # Trading accounts pages
    path('trading-accounts/', trading_accounts_page, name='trading_accounts'),

    # IB/Partner management pages
    path('commissioning-profiles/', commissioning_profiles_list, name='commissioning-profiles-list'),
   # API version (returns JSON) to avoid MIME negotiation issues when called via fetch
    path('api/partner-profile/<int:partner_id>/', get_partner_profile, name='api-get-partner-profile'),
    path('update-partner-profile/<int:partner_id>/', update_partner_profile, name='update-partner-profile'),
    # API-prefixed update endpoint to ensure JSON response and consistent routing
    path('api/update-partner-profile/<int:partner_id>/', update_partner_profile, name='api-update-partner-profile'),
    path('api/admin/ib-user/<int:user_id>/commission-balance/', get_ib_commission_balance, name='api-admin-ib-user-commission-balance'),
    # Prop trading pages
    path('prop-packages/', package_list_view, name='package_list'),
    path('create-prop-package/', create_prop_trading_package, name='create_prop_trading_package'),

    # Static files serving - DISABLED (handled at project level)
    # re_path(r'^static/(?P<path>.*)$', serve, {
    #     'document_root': settings.STATIC_ROOT,
    # }),

    # CATCH-ALL PATTERNS - ONLY FOR ADMIN UI, NOT API
    # Only specific routes for SPA that don't start with 'api/'
    # Note: explicit index.html routes removed to avoid exposing the SPA at arbitrary paths.
    # The admin SPA is served only via the host-based catch-all (see re_path below).
    path('dashboard/', serve_admin_app, name='admin-dashboard-spa'),
    # Redirect legacy manager index path to the manager SPA root
    path('manager/index.html', serve_admin_app if False else __import__('adminPanel.views.admin_app_views', fromlist=['redirect_manager_index']).redirect_manager_index, name='manager-index-redirect'),
    path('settings/', serve_admin_app, name='admin-settings-spa'),
    
    # CRITICAL: ib-user routes MUST come before catch-all regex
    # API ib-user routes (NEW - with /api/ prefix for frontend compatibility)
    path('api/ib-user/<int:user_id>/trading-accounts/', get_trading_accounts, name='api-get-trading-accounts'),
    path('api/ib-user/<int:user_id>/ib-profiles/', get_ib_profiles, name='api-get-ib-profiles'),
    path('api/ib-user/<int:user_id>/ib-status/', user_ib_status, name='api-user-ib-status'),
    path('api/ib-user/<int:user_id>/transactions/', get_user_transactions, name='api-get-user-transactions'),
    path('api/ib-user/<int:user_id>/verification/', user_verification_status, name='api-user-verification-status'),
    path('api/ib-user/<int:user_id>/demo-accounts/', get_demo_accounts, name='api-get-demo-accounts'),
    path('api/ib-user/<int:user_id>/demo-accounts/<str:account_number>/', update_demo_account, name='api-update-demo-account'),
    path('api/ib-user/<int:user_id>/demo-accounts/<str:account_number>/reset/', reset_demo_account, name='api-reset-demo-account'),
    path('api/ib-user/<int:user_id>/bank-details/', get_ib_user_bank_details, name='api-ib-user-bank-details'),
    path('api/test-bank-details/', lambda request: __import__('rest_framework.response', fromlist=['Response']).Response({'test': 'success'}), name='api-test-bank-details'),
    path('api/ib-user/<int:user_id>/crypto-details/', UserCryptoDetailsView.as_view(), name='api-ib-user-crypto-details'),
    
    # Legacy non-API ib-user routes (for backward compatibility with frontend)
    path('ib-user/<int:user_id>/trading-accounts/', get_trading_accounts, name='get-trading-accounts-legacy'),
    path('ib-user/<int:user_id>/ib-profiles/', get_ib_profiles, name='get-ib-profiles-legacy'),
    path('ib-user/<int:user_id>/ib-status/', user_ib_status, name='user-ib-status-legacy'),
    path('ib-user/<int:user_id>/transactions/', get_user_transactions, name='get-user-transactions-legacy'),
    path('ib-user/<int:user_id>/verification/', user_verification_status, name='user-verification-status-legacy'),
    path('ib-user/<int:user_id>/demo-accounts/', get_demo_accounts, name='get-demo-accounts-legacy'),
    path('ib-user/<int:user_id>/demo-accounts/<str:account_number>/', update_demo_account, name='update-demo-account-legacy'),
    path('ib-user/<int:user_id>/demo-accounts/<str:account_number>/reset/', reset_demo_account, name='reset-demo-account-legacy'),
    
    # Root path for admin - catch all non-API routes and serve the admin SPA, but only when
    # the request host indicates the admin site (see serve_admin_app host check).
    re_path(r'^(?!api/)(?!ib-user/)(?!admin-api/).*$', serve_admin_app, name='admin-root-catch-all'),
]

# Static/media serving removed from adminPanel - handled at project level in brokerBackend/urls.py
# This prevents conflicts with API routes

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

# For views that allow multiple roles
class SharedView(APIView):
    @role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
    def get(self, request):
                # Both admins and managers can access this
        return Response({"message": "Shared view"})

# User bank and crypto details endpoints for admin panel
urlpatterns += [
    path('ib-user/<int:user_id>/bank-details/', UserBankDetailsView.as_view(), name='user-bank-details'),
    path('ib-user/<int:user_id>/crypto-details/', UserCryptoDetailsView.as_view(), name='user-crypto-details'),
    path('api/admin/user/<int:user_id>/bank-details/', UserBankDetailsView.as_view(), name='api-user-bank-details'),
    path('api/admin/user/<int:user_id>/crypto-details/', UserCryptoDetailsView.as_view(), name='api-user-crypto-details'),
    path('api/admin/user/<int:user_id>/bank-details/approve/', approve_user_bank_details, name='approve-user-bank-details'),
    path('api/admin/user/<int:user_id>/bank-details/reject/', reject_user_bank_details, name='reject-user-bank-details'),
    path('api/admin/user/<int:user_id>/crypto-details/approve/', approve_user_crypto_details, name='approve-user-crypto-details'),
    path('api/admin/user/<int:user_id>/crypto-details/reject/', reject_user_crypto_details, name='reject-user-crypto-details'),
    path('api/admin/change-leverage/', change_leverage_update, name='change_leverage_update'),
    
    # Prop Trading API endpoints
    path('api/admin/prop-packages/', package_list_view, name='api-prop-packages'),
    path('api/admin/prop-packages/create/', create_prop_trading_package, name='api-create-prop-package'),
    path('api/admin/prop-requests/<int:request_id>/approve/', approve_prop_request, name='api-approve-prop-request'),
    path('api/admin/prop-requests/<int:request_id>/reject/', reject_prop_request, name='api-reject-prop-request'),
    
]


