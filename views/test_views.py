from django.http import JsonResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def test_dashboard_stats_view(request):
    """
    Test view to return mock dashboard statistics without authentication.
    For testing dashboard functionality only.
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
@permission_classes([IsAuthenticated, IsAdminOrManager])
def test_recent_transactions_view(request):
    """
    Test view to return mock recent transactions without authentication.
    For testing dashboard functionality only.
    """
    mock_transactions = [
        {
            "transaction_type": "Deposit",
            "transaction_type_display": "Deposit",
            "amount": "5000.00",
            "created_at": "2025-05-29T16:45:00Z",
            "status": "completed"
        },
        {
            "transaction_type": "Withdrawal", 
            "transaction_type_display": "Withdrawal",
            "amount": "2500.00",
            "created_at": "2025-05-29T15:30:00Z",
            "status": "pending"
        },
        {
            "transaction_type": "Transfer",
            "transaction_type_display": "Internal Transfer", 
            "amount": "1000.00",
            "created_at": "2025-05-29T14:15:00Z",
            "status": "completed"
        },
        {
            "transaction_type": "Commission",
            "transaction_type_display": "IB Commission",
            "amount": "750.00", 
            "created_at": "2025-05-29T13:00:00Z",
            "status": "completed"
        },
        {
            "transaction_type": "Deposit",
            "transaction_type_display": "MAM Investment",
            "amount": "10000.00",
            "created_at": "2025-05-29T11:45:00Z", 
            "status": "completed"
        }
    ]
    
    return Response(mock_transactions, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def test_user_profile_view(request):
    """
    Test view to return mock user profile without authentication.
    For testing dashboard functionality only.
    """
    mock_profile = {
        "id": 1,
        "username": "admin_test",
        "email": "admin@example.com",
        "first_name": "Admin",
        "last_name": "User",
        "role": "Admin",
        "manager_admin_status": "Admin",
        "is_active": True,
        "date_joined": "2025-01-01T00:00:00Z"
    }
    
    return Response(mock_profile, status=status.HTTP_200_OK)
