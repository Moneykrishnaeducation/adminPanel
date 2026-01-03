from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def list_users(request):
    return Response({"message": "Users list"})

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def list_admins_managers(request):
    return Response({"message": "Admins and managers list"})

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def get_admin_manager_details(request, user_id):
    return Response({"message": f"Admin/Manager {user_id} details"})

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def trading_accounts_list(request):
    return Response({"message": "Trading accounts list"})

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def get_trading_accounts(request, user_id):
    return Response({"message": f"Trading accounts for user {user_id}"})