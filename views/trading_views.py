
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
    page_size = 100
    page_size_query_param = 'page_size'
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
        logger.info(f"[trading_accounts_list] user={request.user.username}, status={user_status}, is_admin={is_admin}")
        
        if is_admin:
            trading_accounts = TradingAccount.objects.all()
        else:
            # For managers, only show trading accounts of their clients (created_by or parent_ib)
            # This ensures managers can see accounts of users they manage
            trading_accounts = TradingAccount.objects.filter(
                Q(user__created_by=request.user) | Q(user__parent_ib=request.user)
            )
        
        logger.info(f"[trading_accounts_list] Initial queryset count: {trading_accounts.count()}")
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

        # Filter by active/inactive/all clients
        if request.query_params.get('active') is not None:
            trading_accounts = trading_accounts.filter(balance__gte=10)
        elif request.query_params.get('inactive') is not None:
            trading_accounts = trading_accounts.filter(balance__lt=10)
        # If neither active nor inactive, default to all (or filtered by account_type below)

        # Filter by account_type. Always default to only 'standard' accounts.
        # Only show other types if explicitly requested via account_type or all parameters.
        account_type = request.query_params.get('account_type', None)
        all_types = request.query_params.get('all', None)
        
        # Always filter to standard accounts UNLESS explicitly requesting all types
        if not all_types:
            # Default: Only show standard accounts
            if account_type and account_type.strip().lower() == 'all':
                # User explicitly requested all types
                pass  # Don't filter by type
            elif account_type:
                # User requested a specific type
                trading_accounts = trading_accounts.filter(account_type__iexact=account_type.strip())
            else:
                # Default: standard accounts only
                trading_accounts = trading_accounts.filter(account_type__iexact='standard')
        # else: if all_types is present, return all account types (no filtering)
        
        # Apply sorting
        sort_by = request.query_params.get('sortBy', '-created_at')
        if sort_by:
            trading_accounts = trading_accounts.order_by(sort_by)
        # Apply pagination
        paginator = TradingAccountsPagination()
        page = paginator.paginate_queryset(trading_accounts, request)
        # Serialize the data
        serializer = TradingAccountSerializer(page, many=True)
        # Add alias to each result if available (example: alias from account_name or another field)
        data = serializer.data
        from adminPanel.models import TradeGroup
        for item in data:
            group_alias = ""
            group_name = item.get("group_name")
            if group_name:
                try:
                    group_obj = TradeGroup.objects.filter(name=group_name).first()
                    if group_obj and group_obj.alias:
                        group_alias = group_obj.alias
                except Exception:
                    group_alias = ""
            item["alias"] = group_alias or ""
        # Return paginated response
        return paginator.get_paginated_response(data)
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
        logger.info(f"[get_trading_accounts] Found user: {user.username}, created_by={getattr(user, 'created_by', None)}")
        
        # Check manager permissions (only if user is Manager, not Admin or superuser)
        # Managers can only access trading accounts of their direct clients (parent IB only)
        is_manager_only = (
            not request.user.is_superuser and 
            user_status and 'Manager' in user_status and 'Admin' not in user_status
        )
        
        if is_manager_only:
            user_created_by = getattr(user, 'created_by', None)
            logger.info(f"[get_trading_accounts] Manager check: user.created_by={user_created_by}, request.user={request.user}")
            
            # Check if this user is a client of the manager (created by them)
            # Also check if user is IB parent (parent_ib field) associated with manager
            is_manager_client = (user_created_by == request.user)
            parent_ib = getattr(user, 'parent_ib', None)
            is_parent_ib_client = (parent_ib == request.user)
            
            logger.info(f"[get_trading_accounts] is_manager_client={is_manager_client}, is_parent_ib_client={is_parent_ib_client}")
            
            if not (is_manager_client or is_parent_ib_client):
                logger.warning(f"Manager {request.user.username} ({request.user.user_id}) denied access to user {user.username} ({user.user_id}). User created_by: {user_created_by}, parent_ib: {parent_ib}")
                return Response(
                    {
                        "error": "You don't have permission to view this user's trading accounts",
                        "detail": "Managers can only access accounts of their direct clients"
                    },
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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_non_demo_accounts(request):
    """
    API View to fetch all non-demo trading accounts (live, MAM, and investment accounts)
    for admin internal transfers. Excludes demo and CENT accounts.
    Optimized for fast loading - uses DB balance primarily.
    Supports search by account_id and user_email.
    """
    try:
        from django.core.cache import cache
        from adminPanel.models import TradeGroup
        
        # Check if user has admin permissions
        user_status = getattr(request.user, 'manager_admin_status', None)
        is_admin = (
            getattr(request.user, 'is_superuser', False) or
            (user_status and 'Admin' in user_status)
        )
        
        if not is_admin:
            logger.warning(f"Non-admin user {request.user.email} attempted to access admin non-demo accounts")
            return Response({
                'error': 'Permission denied. Admin access required.'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get search parameter
        search = (request.GET.get('search') or '').strip()
        
        # Create cache key based on search
        cache_key = f"admin_non_demo_accounts_{search}" if search else "admin_non_demo_accounts_all"
        
        # Return cached payload if available (5 second cache for faster response)
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            logger.debug(f"Returning cached admin non-demo accounts (search: '{search}')")
            return Response(cached_payload, status=status.HTTP_200_OK)
        
        # Pre-fetch all TradeGroup aliases for faster lookup
        trade_groups = {tg.name: tg.alias for tg in TradeGroup.objects.all() if tg.alias}
        
        # Get non-demo accounts from database with optimized query
        # Filter for standard (live), mam, and mam_investment accounts only
        db_accounts_query = TradingAccount.objects.filter(
            account_type__in=['standard', 'mam', 'mam_investment'],
            balance__isnull=False  # Only accounts with balance data
        ).exclude(
            Q(account_type__iexact='demo') |
            Q(group_name__icontains='demo')
        ).select_related('user').only(
            'account_id', 'account_name', 'account_type', 'balance', 
            'group_name', 'user__email', 'user__first_name', 'user__last_name'
        )
        
        # Apply search filter if provided
        if search:
            db_accounts_query = db_accounts_query.filter(
                Q(account_id__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search)
            )
        
        # Remove limit when searching, or increase limit significantly for all accounts
        if search:
            db_accounts = db_accounts_query  # No limit for search results
        else:
            db_accounts = db_accounts_query[:2000]  # Higher limit for all accounts (increased from 500)
        
        # Process accounts quickly without MT5 sync
        accounts_data = []
        
        for db_account in db_accounts:
            # Get group_alias from pre-fetched dict
            group_alias = trade_groups.get(db_account.group_name, '')
            
            # Skip CENT accounts
            is_cent = False
            if group_alias and group_alias.upper() == 'CENT':
                is_cent = True
            elif db_account.group_name:
                group_lower = db_account.group_name.lower()
                if 'cent' in group_lower or '-c-' in group_lower:
                    is_cent = True
            
            if is_cent:
                continue
            
            account_data = {
                'account_id': db_account.account_id,
                'account_name': db_account.account_name or '',
                'account_type': db_account.account_type,
                'balance': db_account.balance or 0,
                'group_name': db_account.group_name or '',
                'group_alias': group_alias,
                'user_email': db_account.user.email if db_account.user else '',
                'user_name': f"{db_account.user.first_name} {db_account.user.last_name}".strip() if db_account.user else ''
            }
            
            accounts_data.append(account_data)
        
        # Sort by account_id
        accounts_data.sort(key=lambda x: x['account_id'])
        
        payload = accounts_data
        
        # Cache for 5 seconds for faster repeated access
        cache.set(cache_key, payload, 5)
        
        logger.info(f"Returning {len(accounts_data)} admin non-demo accounts (search: '{search}')")
        return Response(payload, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error fetching admin non-demo accounts: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return Response({
            'error': 'Failed to fetch accounts',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
