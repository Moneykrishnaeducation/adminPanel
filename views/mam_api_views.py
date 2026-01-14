from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q
import traceback

from adminPanel.models import TradingAccount
from adminPanel.serializers import TradingAccountSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def mam_accounts_list(request):
    try:
        user_status = getattr(request.user, 'manager_admin_status', None)
        is_admin = (
            getattr(request.user, 'is_superuser', False) or
            (user_status and 'Admin' in user_status)
        )

        if is_admin:
            mam_accounts = TradingAccount.objects.filter(account_type='mam')
        else:
            # Managers see only accounts created by them
            mam_accounts = TradingAccount.objects.filter(account_type='mam', user__created_by=request.user)

        # Search
        search = (request.query_params.get('query') or request.query_params.get('search') or '').strip()
        if search:
            mam_accounts = mam_accounts.filter(
                Q(account_id__icontains=search) |
                Q(account_name__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__username__icontains=search)
            )

        # Status filter (optional)
        status_param = request.query_params.get('status')
        if status_param and status_param.lower() != 'all':
            mam_accounts = mam_accounts.filter(status__iexact=status_param)

        # Sorting
        sort_by = request.query_params.get('sortBy', '-created_at')
        mam_accounts = mam_accounts.order_by(sort_by)

        # Pagination
        try:
            from adminPanel.pagination import MamAccountsPagination
        except Exception:
            # Fallback: simple pagination using DRF PageNumberPagination if custom pagination missing
            from rest_framework.pagination import PageNumberPagination
            class MamAccountsPagination(PageNumberPagination):
                page_size = 25

        paginator = MamAccountsPagination()
        page = paginator.paginate_queryset(mam_accounts, request)

        serializer = TradingAccountSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    except Exception as e:
        return Response({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "code": "server_error"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def investor_accounts_list(request):
    try:
        user_status = getattr(request.user, 'manager_admin_status', None)
        is_admin = (
            getattr(request.user, 'is_superuser', False) or
            (user_status and 'Admin' in user_status)
        )

        if is_admin:
            investor_accounts = TradingAccount.objects.filter(account_type='mam_investment')
        else:
            # Managers see investors under their MAM or created by them
            investor_accounts = TradingAccount.objects.filter(account_type='mam_investment', user__created_by=request.user)

        # Search
        search = (request.query_params.get('query') or request.query_params.get('search') or '').strip()
        if search:
            investor_accounts = investor_accounts.filter(
                Q(account_id__icontains=search) |
                Q(account_name__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__username__icontains=search) |
                Q(mam_master_account__account_id__icontains=search)
            )

        # Filter by MAM account
        mam_id = request.query_params.get('mam_id')
        if mam_id:
            investor_accounts = investor_accounts.filter(mam_account__mam_id=mam_id)

        # Sorting
        sort_by = request.query_params.get('sortBy', '-created_at')
        investor_accounts = investor_accounts.order_by(sort_by)

        # Pagination
        try:
            from adminPanel.pagination import InvestorAccountsPagination
        except Exception:
            from rest_framework.pagination import PageNumberPagination
            class InvestorAccountsPagination(PageNumberPagination):
                page_size = 25

        paginator = InvestorAccountsPagination()
        page = paginator.paginate_queryset(investor_accounts, request)

        serializer = TradingAccountSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    except Exception as e:
        return Response({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "code": "server_error"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
