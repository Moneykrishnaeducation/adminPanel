
from django.shortcuts import redirect
from django.urls import resolve
from django.conf import settings
from adminPanel.roles import is_admin, is_manager, is_client

class RoleBasedAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip authentication for public paths, static files, well-known paths and favicon
        if (request.path.startswith('/static/') or 
            request.path.startswith('/.well-known/') or 
            request.path == '/favicon.ico' or
            any(request.path.startswith(path) for path in settings.PUBLIC_PATHS)):
            return self.get_response(request)

        # Skip authentication for API endpoints that use JWT authentication
        # These endpoints will be handled by DRF's authentication classes
        api_endpoints = [
            '/client/api/',          # API namespace endpoints
            '/client/user-info/',    # Direct API endpoints
            '/client/recent-transactions/',
            '/client/stats-overview/',
            '/client/validate-token/',
            '/client/user-trading-accounts/',
            '/client/user-accounts/',
            '/client/user-demo-accounts/',
            '/client/getmydetails/',
            '/client/user-transactions/',
            '/client/pending-transactions/',
            '/client/notifications/',  # Notification endpoints
            '/client/packages/',
            '/client/ib/',
            '/client/manual-deposit/',
            '/client/cheezepay-',    # CheezePay payment initiation
            '/client/cheezepay-notify/',  # CheezePay webhook notification (MUST be anonymous)
            '/client/usdt-deposit/',
            '/client/withdraw-',
            '/client/user/',
            '/client/change-request/',
            '/client/bank-details',
            '/client/crypto-details',
            '/client/account-settings/',
            '/client/update-',
            '/client/toggle-',
            '/client/create-',
            '/client/reset-',
            '/client/change-',
            '/client/tickets/',
            '/client/getmydetails/',
            '/client/prop-trading-requests/',
            '/client/my-requests/',
            '/client/cancel-request/',
            '/client/open-positions/',
            '/client/get-trading-positions/',
            '/client/transactions',
            '/client/forgot-password/',
            '/client/verify-otp/',
            '/client/reset-password/',
            '/client/ib-request/',
            '/client/mam-',
            '/client/available-',
            '/client/pause-copying/',
            '/client/start-copying/',
            '/client/stats-overview',
            '/client/internal-transfer',
            '/client/get-usd-inr-rate/',
            '/client/validate-token/',
            '/admin/api/',           # Admin API endpoints (legacy)
            '/admin-api/',           # Admin API endpoints (current)
            '/api/admin/',          # New admin API endpoints for pending requests
            '/api/login/',          # Authentication endpoints
            '/api/logout/',
            '/api/validate-token/',
            '/api/commissioning-profiles/',  # Commissioning profiles endpoint
        ]
        if any(request.path.startswith(endpoint) for endpoint in api_endpoints):
            return self.get_response(request)

        # Check if user is authenticated for non-public paths
        if not request.user.is_authenticated:
            if '/admin/' in request.path:
                return redirect('/admin/login/')
            elif '/client/' in request.path:
                return redirect('/client/login/')
            return self.get_response(request)

        # Get the requested static path
        path = request.path.strip('/')

        # Handle role-based access
        if path.startswith('static/admin/admin/') and not is_admin(request.user):
            return redirect('unauthorized')
        elif path.startswith('static/admin/manager/') and not is_manager(request.user):
            return redirect('unauthorized')
        elif path.startswith('static/client/') and not is_client(request.user):
            return redirect('unauthorized')

        return self.get_response(request)
