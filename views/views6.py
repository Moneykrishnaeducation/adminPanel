from django.core.mail import EmailMessage
from rest_framework.pagination import PageNumberPagination
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from django.db.models import Q
from adminPanel.permissions import IsAdmin, IsManager, OrPermission, IsAuthenticatedUser
from rest_framework.response import Response
from rest_framework.views import APIView
from .views import get_client_ip
from ..models import (
    CustomUser,
    Transaction,
    TradingAccount,
    DemoAccount,
    Ticket,
    IBRequest,
    PropTradingRequest,
    ActivityLog
)
from ..serializers import (
    UserSerializer,
    TransactionSerializer,
    TradingAccountSerializer,
    IBUserSerializer
)
from ..EmailSender import EmailSender
import logging

logger = logging.getLogger(__name__)

@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def deposit_transactions(request):
    """
    Fetch deposit transactions with pagination, sorting, and searching.
    """
    try:
        user = request.user
        search_query = request.GET.get('search', '')  # Searching text
        sort_by = request.GET.get('sortBy', 'created_at')  # Default sorting by created_at
        sort_order = request.GET.get('sortOrder', 'desc')  # Default descending order
        page = int(request.GET.get('page', 1))  # Current page
        page_size = int(request.GET.get('pageSize', 10))  # Records per page

        # Apply sorting (Django uses '-' for descending)
        sort_by = f"-{sort_by}" if sort_order == "desc" else sort_by

        # **Admin & Manager Level 1** → Can see all deposits
        if user.manager_admin_status in ['Admin', 'Manager']:
            deposits = Transaction.objects.filter(
                transaction_type='deposit_trading'
            ).exclude(status='pending')

        else:
            deposits = Transaction.objects.none()  # No access

        # Apply search filter (Search in username, trading_account_id, or reference id)
        if search_query:
            deposits = deposits.filter(
                Q(user__username__icontains=search_query) |
                Q(user__trading_account_id__icontains=search_query) |
                Q(id__icontains=search_query)
            )

        # Apply Sorting
        deposits = deposits.order_by(sort_by)

        # Pagination Logic (Manual)
        total_count = deposits.count()
        start = (page - 1) * page_size
        end = start + page_size
        deposits = deposits[start:end]

        # Serialize & Return Data
        serializer = TransactionSerializer(deposits, many=True)
        return Response({
            "total": total_count,
            "results": serializer.data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def credit_out_history(request):
    """
    Fetch Credit-Out Transactions with Pagination, Sorting, and Searching.
    """
    try:
        user = request.user
        search_query = request.GET.get('search', '')  # Search query
        sort_by = request.GET.get('sortBy', 'created_at')  # Default sorting field
        sort_order = request.GET.get('sortOrder', 'desc')  # Default sort order
        page = int(request.GET.get('page', 1))  # Current page
        page_size = int(request.GET.get('pageSize', 10))  # Records per page

        # Apply sorting (`-` for descending in Django)
        sort_by = f"-{sort_by}" if sort_order == "desc" else sort_by

        # Filter data based on role
        if user.manager_admin_status in ['Admin', 'Manager']:
            credit_out_transactions = Transaction.objects.filter(
                transaction_type='credit_out'
            ).exclude(status='pending')

        else:
            credit_out_transactions = Transaction.objects.none()

        # Apply search query
        if search_query:
            credit_out_transactions = credit_out_transactions.filter(
                Q(user__username__icontains=search_query) |
                Q(user__email__icontains=search_query) |
                Q(trading_account_id__icontains=search_query) |
                Q(id__icontains=search_query)
            )

        # Apply sorting
        credit_out_transactions = credit_out_transactions.order_by(sort_by)

        # Apply pagination
        total_count = credit_out_transactions.count()
        start = (page - 1) * page_size
        end = start + page_size
        credit_out_transactions = credit_out_transactions[start:end]

        # Serialize and return
        serializer = TransactionSerializer(credit_out_transactions, many=True)
        return Response({
            "total": total_count,
            "results": serializer.data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def credit_in_history(request):
    """
    Fetch Credit-In Transactions with Pagination, Sorting, and Searching.
    """
    try:
        user = request.user
        search_query = request.GET.get('search', '')  # Search query
        sort_by = request.GET.get('sortBy', 'created_at')  # Default sorting field
        sort_order = request.GET.get('sortOrder', 'desc')  # Default sort order
        page = int(request.GET.get('page', 1))  # Current page
        page_size = int(request.GET.get('pageSize', 10))  # Records per page

        # Apply sorting (`-` for descending in Django)
        sort_by = f"-{sort_by}" if sort_order == "desc" else sort_by

        # Filter data based on role
        if user.manager_admin_status in ['Admin', 'Manager']:
            credit_in_transactions = Transaction.objects.filter(
                transaction_type='credit_in'
            ).exclude(status='pending')

        else:
            credit_in_transactions = Transaction.objects.none()

        # Apply search query
        if search_query:
            credit_in_transactions = credit_in_transactions.filter(
                Q(user__username__icontains=search_query) |
                Q(user__email__icontains=search_query) |
                Q(trading_account_id__icontains=search_query) |
                Q(id__icontains=search_query)
            )

        # Apply sorting
        credit_in_transactions = credit_in_transactions.order_by(sort_by)

        # Apply pagination
        total_count = credit_in_transactions.count()
        start = (page - 1) * page_size
        end = start + page_size
        credit_in_transactions = credit_in_transactions[start:end]

        # Serialize and return
        serializer = TransactionSerializer(credit_in_transactions, many=True)
        return Response({
            "total": total_count,
            "results": serializer.data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def list_trading_accounts(request):
    """
    API view to list all trading accounts based on user permissions.
    """
    try:
        if request.user.manager_admin_status in ['Admin', 'Manager']:
            
            trading_accounts = TradingAccount.objects.select_related('user').all()
        else:
            
            trading_accounts = TradingAccount.objects.none()

        serializer = TradingAccountSerializer(trading_accounts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)




@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def pending_transactions(request):
    """
    API view to list all pending transactions with sorting, searching, and pagination.
    """
    try:
        if request.user.manager_admin_status in ['Admin', 'Manager']:
            pending_transactions = Transaction.objects.filter(status='pending').exclude(source="CheesePay")
        else:
            pending_transactions = Transaction.objects.none()

        search_query = request.GET.get('search', '')
        print(request.GET)
        if search_query:
            pending_transactions = pending_transactions.filter(
                Q(user__email__icontains=search_query) |
                Q(user__username__icontains=search_query) |
                Q(transaction_type__icontains=search_query) |
                Q(trading_account__account_id__icontains=search_query) |
                Q(trading_account__account_name__icontains=search_query) |
                Q(source__icontains=search_query) |
                Q(status__icontains=search_query)
            ).exclude(source="CheesePay")

        sort_by = request.GET.get('sortBy', 'created_at')
        sort_order = request.GET.get('sortOrder', 'asc')
        if sort_order == 'desc':
            sort_by = f'-{sort_by}'
        pending_transactions = pending_transactions.order_by(sort_by)

        # Pagination
        paginator = PageNumberPagination()
        paginator.page_size = request.GET.get('pageSize', 10)
        paginated_transactions = paginator.paginate_queryset(pending_transactions, request)

        # Serialize and return the response
        serializer = TransactionSerializer(paginated_transactions, many=True)
        return paginator.get_paginated_response(serializer.data)

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def dashboard_stats_view(request):
    """
    View to return dummy dashboard statistics.
    """
    user_now = request.user
    if user_now.manager_admin_status == "Manager":
        dummy_data = [
            {"label": "Total Users", "value": CustomUser.objects.filter(created_by=user_now).count(), "icon": "fa fa-users", "color": "#3498db"},
            {"label": "Pending Transactions", "value": Transaction.objects.filter(status='pending', trading_account__user__created_by=user_now ).count(), "icon": "fa fa-money-bill-wave", "color": "#f39c12"},
            {"label": "Pending Tickets", "value": Ticket.objects.filter(status='pending', created_by__created_by=user_now).count(), "icon": "fa fa-ticket-alt", "color": "#d35400"},
            {"label": "Pending IB Requests", "value": IBRequest.objects.filter(status='pending',  user__created_by=user_now).count(), "icon": "fa fa-network-wired", "color": "#3498db"},
            {"label": "Pending Prop Requests", "value": PropTradingRequest.objects.filter(status='pending',  user__created_by=user_now).count(), "icon": "fa fa-building", "color": "#f39c12"},
            {"label": "Active MAM Accounts", "value": TradingAccount.objects.filter(account_type='mam', user__created_by=user_now).count(), "icon": "fa fa-user-tie", "color": "#16a085"},
            {"label": "Total Trading Accounts","value": TradingAccount.objects.filter(account_type="standard", user__created_by=user_now).count(),"icon": "fa fa-wallet","color": "#2ecc71"},
            {"label": "Total Demo Accounts","value": DemoAccount.objects.filter(user__created_by=user_now).count(),"icon": "fa fa-book","color": "#3498db"},
            {"label": "MAM Investor Accounts","value": TradingAccount.objects.filter(account_type="mam_investment", user__created_by=user_now).count(),"icon": "fa fa-handshake","color": "#9b59b6"},
            {"label": "Total Prop Accounts","value": TradingAccount.objects.filter(account_type="prop",  user__created_by=user_now).count(),"icon": "fa fa-briefcase","color": "#1abc9c"},
            ]
    else:      
        dummy_data = [
        {"label": "Total Users", "value": CustomUser.objects.count(), "icon": "fa fa-users", "color": "#3498db"},
        {"label": "Pending Transactions", "value": Transaction.objects.filter(status='pending').count(), "icon": "fa fa-money-bill-wave", "color": "#f39c12"},
        {"label": "Pending Tickets", "value": Ticket.objects.filter(status='pending').count(), "icon": "fa fa-ticket-alt", "color": "#d35400"},
        {"label": "Pending IB Requests", "value": IBRequest.objects.filter(status='pending').count(), "icon": "fa fa-network-wired", "color": "#3498db"},
        {"label": "Pending Prop Requests", "value": PropTradingRequest.objects.filter(status='pending').count(), "icon": "fa fa-building", "color": "#f39c12"},
        {"label": "Active MAM Accounts", "value": TradingAccount.objects.filter(account_type='mam').count(), "icon": "fa fa-user-tie", "color": "#16a085"},
        {"label": "Total Trading Accounts","value": TradingAccount.objects.filter(account_type="standard").count(),"icon": "fa fa-wallet","color": "#2ecc71"},
        {"label": "Total Demo Accounts","value": DemoAccount.objects.all().count(),"icon": "fa fa-book","color": "#3498db"},
        {"label": "MAM Investor Accounts","value": TradingAccount.objects.filter(account_type="mam_investment").count(),"icon": "fa fa-handshake","color": "#9b59b6"},
        {"label": "Total Prop Accounts","value": TradingAccount.objects.filter(account_type="prop").count(),"icon": "fa fa-briefcase","color": "#1abc9c"},
        ]
    
    return Response(dummy_data, status=status.HTTP_200_OK)



@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_recent_withdrawals(request):
    """
    API view to list the most recent withdrawal transactions based on user permissions.
    """
    try:
        if request.user.manager_admin_status in ['Admin', 'Manager']:
            
            recent_withdrawals = (
                Transaction.objects
                .filter(transaction_type='withdraw_trading')
                .order_by('-created_at')[:5]
            )
        else:
            
            recent_withdrawals = Transaction.objects.none()

        serializer = TransactionSerializer(recent_withdrawals, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_recent_internal_transfers(request):
    """
    API view to list the most recent internal transfer transactions based on user permissions.
    """
    try:
        if request.user.manager_admin_status in ['Admin', 'Manager']:
            
            recent_transfers = (
                Transaction.objects
                .filter(transaction_type='internal_transfer')
                .order_by('-created_at')[:5]
            )
        else:
            
            recent_transfers = Transaction.objects.none()

        serializer = TransactionSerializer(recent_transfers, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_recent_deposits(request):
    """
    API view to list the most recent deposit transactions based on user permissions.
    """
    try:
        if request.user.manager_admin_status in ['Admin', 'Manager']:
            
            recent_deposits = (
                Transaction.objects
                .filter(transaction_type='deposit_trading')
                .order_by('-created_at')[:5]
            )
        else:
            
            recent_deposits = Transaction.objects.none()

        serializer = TransactionSerializer(recent_deposits, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(['GET'])
@permission_classes([IsAdmin])
def list_admins_managers(request):
    try:
        users = CustomUser.objects.exclude(manager_admin_status='None')
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAdmin])
def get_admin_manager_details(request, user_id):
    try:
        user = CustomUser.objects.get(user_id=user_id)
        serializer = UserSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAdmin])
def update_admin_manager_role(request, email):
    """
    View to update the role of an admin or manager using their email address.
    """
    try:
        user = CustomUser.objects.get(email=email)
        new_role = request.data.get('role')
        
        if new_role not in ['None', 'Admin', 'Manager']:
            return Response({'error': 'Invalid role specified'}, status=status.HTTP_400_BAD_REQUEST)

        user.manager_admin_status = new_role
        user.save()

        ActivityLog.objects.create(
            user=request.user,
            activity=f"Updated role for user with email {email} to {new_role}",
            ip_address=get_client_ip(request),
            endpoint=request.path,
            activity_type="update",
            activity_category="management",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=user.id,
            related_object_type="Admin/Manager"
        )

        return Response({'message': 'Role successfully updated'}, status=status.HTTP_200_OK)
        
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def user_registration_view(request):
    user_email = request.data.get("email")
    registration_data = {
        "first_name": request.data.get("firstName", ""),
        "last_name": request.data.get("lastName", ""),
        "phone_number": str(request.data.get("mobile", "")),
        "email": request.data.get("email", ""),
        "address": request.data.get("address", ""),
        "city": request.data.get("city", ""),
        "zip_code": request.data.get("zipCode", ""),
        "state": request.data.get("state", ""),
        "country": request.data.get("country", ""),
        "IB_status": request.data.get("IB_status", False),
        "MAM_manager_status": request.data.get("MAM_manager_status", False),
        "manager_admin_status": request.data.get("manager_admin_status", 'None'),
        "is_active": True,
        "password": request.data.get("password"),  
    }

    serializer = UserSerializer(data=registration_data)
    if serializer.is_valid():
        user = serializer.save()

        # Send welcome email
        try:
            logger.info(f"Attempting to send welcome email to new user {user_email}")
            welcome_email_sent = EmailSender.send_welcome_email(user_email, user.first_name)
            if not welcome_email_sent:
                logger.warning(f"Failed to send welcome email to {user_email}")
        except Exception as e:
            logger.error(f"Error sending welcome email to {user_email}: {str(e)}")
            # We don't want to rollback the registration if email fails
            pass

        ActivityLog.objects.create(
            user=request.user,
            activity=f"Registered new user with email {user_email}",
            ip_address=get_client_ip(request),
            endpoint=request.path,
            activity_type="create",
            activity_category="management",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=user.id,
            related_object_type="User Registration"
        )
        return Response({"message": "User registered successfully"}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ListIBUsersView(APIView):
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def get(self, request):
        try:
            ib_users = CustomUser.objects.filter(IB_status=True)

            search_query = request.GET.get('search', '').strip()
            if search_query:
                ib_users = ib_users.filter(
                    Q(first_name__icontains=search_query) |
                    Q(last_name__icontains=search_query) |
                    Q(email__icontains=search_query) |
                    Q(country__icontains=search_query)
                )

            sort_by = request.GET.get('user_id', 'user_id')
            sort_order = request.GET.get('sortOrder', 'asc')
            if sort_order == 'desc':
                sort_by = f'-{sort_by}'
            ib_users = ib_users.order_by(sort_by)

            paginator = PageNumberPagination()
            paginator.page_size = request.GET.get('pageSize', 10)
            paginated_users = paginator.paginate_queryset(ib_users, request)

            serializer = IBUserSerializer(paginated_users, many=True)
            return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            print(e)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def list_users(request):
    try:
        if request.user.manager_admin_status == 'Admin':
            users = CustomUser.objects.all()
        else:
            # For managers, only show their assigned clients (created_by)
            users = CustomUser.objects.filter(created_by=request.user)
        
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Public test views for dashboard testing (no authentication required)

@api_view(['GET'])
@permission_classes([])
def dashboard_stats_view_public(request):
    """
    Public view to return mock dashboard statistics without authentication.
    For testing dashboard functionality.
    """
    mock_data = [
        {"label": "Live Trading Accounts", "value": "1,247", "icon": "fa fa-chart-line", "color": "#28a745"},
        {"label": "Demo Accounts", "value": "3,891", "icon": "fa fa-play-circle", "color": "#007bff"},
        {"label": "Real Balance (USD)", "value": "$2,847,392", "icon": "fa fa-dollar-sign", "color": "#ffc107"},
        {"label": "Total Clients (IB)", "value": "892", "icon": "fa fa-users", "color": "#6f42c1"},
        {"label": "Overall Deposits", "value": "$4,231,847", "icon": "fa fa-arrow-down", "color": "#20c997"},
        {"label": "MAM Funds Invested", "value": "$1,847,329", "icon": "fa fa-handshake", "color": "#fd7e14"},
        {"label": "MAM Managed Funds", "value": "$984,847", "icon": "fa fa-user-tie", "color": "#e83e8c"},
        {"label": "IB Earnings", "value": "$84,729", "icon": "fa fa-coins", "color": "#17a2b8"},
        {"label": "Withdrawable Commission", "value": "$42,847", "icon": "fa fa-money-bill-wave", "color": "#dc3545"}
    ]
    
    return Response(mock_data, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([])
def recent_transactions_view_public(request):
    """
    Public view to return mock recent transactions without authentication.
    For testing dashboard functionality.
    """
    return Response([], status=status.HTTP_200_OK)