
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q
from adminPanel.models import TradingAccount, CustomUser
from adminPanel.serializers import TradingAccountSerializer
import logging

logger = logging.getLogger(__name__)

class TradingAccountsPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'pageSize'
    max_page_size = 1000

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def trading_accounts_list(request):
    import traceback
    try:
        # Get base queryset based on user role - handle superuser and status strings like 'Admin Level 1'
        user_status = getattr(request.user, 'manager_admin_status', None)
        is_admin = (
            getattr(request.user, 'is_superuser', False) or
            (user_status and 'Admin' in user_status)
        )
        if is_admin:
            trading_accounts = TradingAccount.objects.all()
        else:
            # For managers, only show trading accounts of their clients (created_by)
            trading_accounts = TradingAccount.objects.filter(user__created_by=request.user)
        # Apply search if provided (server-side).
        # Frontend sends `query`, while some clients may use `search`.
        search = (request.query_params.get('query') or request.query_params.get('search') or '').strip()
        if search:
            # Support searching across account_id, account_name, user email, username and user_id
            search_q = (
                Q(account_id__icontains=search) |
                Q(account_name__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__username__icontains=search) |
                Q(user__user_id__icontains=search)
            )
            trading_accounts = trading_accounts.filter(search_q)

        # Filter by account_type. Default to only 'standard' accounts when not specified.
        # If `account_type=all` is provided, return all types (no filtering).
        account_type = request.query_params.get('account_type', None)
        if account_type:
            at = account_type.strip()
            if at and at.lower() != 'all':
                trading_accounts = trading_accounts.filter(account_type__iexact=at)
        else:
            # Default behavior: list only standard accounts
            trading_accounts = trading_accounts.filter(account_type__iexact='standard')
        # Apply sorting
        sort_by = request.query_params.get('sortBy', '-created_at')
        if sort_by:
            trading_accounts = trading_accounts.order_by(sort_by)
        # Apply pagination
        paginator = TradingAccountsPagination()
        page = paginator.paginate_queryset(trading_accounts, request)
        # Serialize the data
        serializer = TradingAccountSerializer(page, many=True)
        # Return paginated response in frontend-expected format
        total = paginator.page.paginator.count if hasattr(paginator, 'page') and hasattr(paginator.page, 'paginator') else trading_accounts.count()
        return Response({
            "data": serializer.data,
            "total": total,
            "count": total,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link()
        })
    except Exception as e:
        return Response({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "code": "server_error"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)    


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_trading_accounts(request, user_id):
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"[get_trading_accounts] Called with user_id={user_id}, request.user={request.user}")
        
        # Check user role - handle superuser and status strings like 'Admin Level 1', 'Manager Level 1'
        user_status = getattr(request.user, 'manager_admin_status', None)
        is_admin_or_manager = (
            getattr(request.user, 'is_superuser', False) or
            (user_status and ('Admin' in user_status or 'Manager' in user_status))
        )
        
        logger.info(f"[get_trading_accounts] user_status={user_status}, is_admin_or_manager={is_admin_or_manager}")
        
        if not is_admin_or_manager:
            logger.warning(f"Permission denied for user {request.user.username} with status: {user_status}")
            return Response(
                {"error": "You don't have permission to access this resource"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Verify the user exists
        user = CustomUser.objects.get(user_id=user_id)
        logger.info(f"[get_trading_accounts] Found user: {user.username}")
        
        # Check manager permissions (only if user is Manager, not Admin or superuser)
        if (not request.user.is_superuser and 
            user_status and 'Manager' in user_status and 'Admin' not in user_status and 
            getattr(user, 'created_by', None) != request.user):
            logger.warning(f"Manager {request.user.username} denied access to user {user.username}")
            return Response(
                {"error": "You don't have permission to view this user's trading accounts"},
                status=status.HTTP_403_FORBIDDEN
            )
            
        trading_accounts = TradingAccount.objects.filter(user=user)

        # Exclude demo accounts by default (frontend removes 'demo' from filter options)
        trading_accounts = trading_accounts.exclude(account_type__iexact='demo')

        # Allow filtering by account_type via query param (e.g. account_type=standard)
        account_type = request.query_params.get('account_type', '').strip()
        if account_type and account_type.lower() != 'all':
            trading_accounts = trading_accounts.filter(account_type__iexact=account_type)
        
        logger.info(f"[get_trading_accounts] Found {trading_accounts.count()} trading accounts")
            
        try:
            serializer = TradingAccountSerializer(trading_accounts, many=True)
            serializer_data = serializer.data
            logger.info(f"[get_trading_accounts] Serialized {len(serializer_data)} accounts")
        except Exception as e:
            logger.error(f"Serializer failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            serializer_data = []
        
        return Response({
            "message": f"Trading accounts for user {user_id}", 
            "data": serializer_data,
            "debug": {
                "user_id": user_id,
                "user_found": user.username,
                "user_email": user.email,
                "accounts_count": trading_accounts.count(),
                "serialized_count": len(serializer_data),
                "request_user": request.user.username,
                "request_user_role": getattr(request.user, 'manager_admin_status', 'N/A')
            }
        })
    except CustomUser.DoesNotExist:
        logger.error(f"User {user_id} not found")
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error getting trading accounts for user {user_id}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return Response({"error": str(e), "type": type(e).__name__}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
