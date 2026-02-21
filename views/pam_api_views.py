from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q
import traceback

from clientPanel.models import PAMAccount, PAMInvestment
from clientPanel.serializers import PAMAccountSerializer, PAMInvestmentSerializer
from decimal import Decimal
from adminPanel.permissions import IsAdminOrManager
import json


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pam_accounts_list(request):
    try:
        user_status = getattr(request.user, 'manager_admin_status', None)
        is_admin = (
            getattr(request.user, 'is_superuser', False) or
            (user_status and 'Admin' in user_status)
        )

        if is_admin:
            qs = PAMAccount.objects.all()
        else:
            qs = PAMAccount.objects.filter(manager=request.user)

        # Search
        search = (request.query_params.get('query') or request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(manager__username__icontains=search) |
                Q(manager__email__icontains=search)
            )

        # Sorting
        sort_by = request.query_params.get('sortBy', '-created_at')
        qs = qs.order_by(sort_by)

        # Pagination
        try:
            from adminPanel.pagination import MamAccountsPagination
        except Exception:
            from rest_framework.pagination import PageNumberPagination
            class MamAccountsPagination(PageNumberPagination):
                page_size = 25

        paginator = MamAccountsPagination()
        page = paginator.paginate_queryset(qs, request)

        serializer = PAMAccountSerializer(page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        # Patch next/previous to be relative if needed
        if hasattr(response, 'data'):
            for key in ("next", "previous"):
                url = response.data.get(key)
                if url and url.startswith("http"):
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    response.data[key] = parsed.path + ("?" + parsed.query if parsed.query else "")
        return response

    except Exception as e:
        return Response({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "code": "server_error"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pam_investors_list(request):
    try:
        user_status = getattr(request.user, 'manager_admin_status', None)
        is_admin = (
            getattr(request.user, 'is_superuser', False) or
            (user_status and 'Admin' in user_status)
        )

        if is_admin:
            qs = PAMInvestment.objects.select_related('investor', 'pam_account')
        else:
            # Managers see investments for their PAM accounts
            qs = PAMInvestment.objects.filter(pam_account__manager=request.user).select_related('investor', 'pam_account')

        # Search
        search = (request.query_params.get('query') or request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                Q(investor__username__icontains=search) |
                Q(investor__email__icontains=search) |
                Q(pam_account__name__icontains=search)
            )

        # Filter by PAM account id
        pamm_id = request.query_params.get('pamm_id') or request.query_params.get('pam_id')
        if pamm_id:
            qs = qs.filter(pam_account__id=pamm_id)

        # Sorting
        sort_by = request.query_params.get('sortBy', '-created_at')
        qs = qs.order_by(sort_by)

        # Pagination
        try:
            from adminPanel.pagination import InvestorAccountsPagination
        except Exception:
            from rest_framework.pagination import PageNumberPagination
            class InvestorAccountsPagination(PageNumberPagination):
                page_size = 25

        paginator = InvestorAccountsPagination()
        page = paginator.paginate_queryset(qs, request)

        serializer = PAMInvestmentSerializer(page, many=True)
        if page is not None:
            response = paginator.get_paginated_response(serializer.data)
            if hasattr(response, 'data'):
                for key in ("next", "previous"):
                    url = response.data.get(key)
                    if url and url.startswith("http"):
                        from urllib.parse import urlparse
                        parsed = urlparse(url)
                        response.data[key] = parsed.path + ("?" + parsed.query if parsed.query else "")
            return response
        else:
            return Response({"count": 0, "next": None, "previous": None, "results": []}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "code": "server_error"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PATCH', 'PUT'])
@permission_classes([IsAuthenticated])
def pam_update_manager_capital(request, mt5_login):
    """Update or increment the manager_capital for a PAM account identified by mt5_login.
    Request JSON:
      { "amount": "100.00", "operation": "set" }  # operation: 'set' or 'increment'
    """
    try:
        pam = PAMAccount.objects.filter(mt5_login=str(mt5_login)).first()
        if not pam:
            return Response({"error": "PAM account not found"}, status=status.HTTP_404_NOT_FOUND)

        # Permission: admins can update any, managers only their own
        user_status = getattr(request.user, 'manager_admin_status', None)
        is_admin = (getattr(request.user, 'is_superuser', False) or (user_status and 'Admin' in user_status))
        if not is_admin and getattr(pam, 'manager', None) != request.user:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        try:
            payload = request.data if isinstance(request.data, dict) else json.loads(request.body or '{}')
        except Exception:
            payload = {}

        amount = payload.get('amount')
        operation = (payload.get('operation') or 'set').lower()
        if amount is None:
            return Response({"error": "amount is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            dec_amt = Decimal(str(amount))
        except Exception:
            return Response({"error": "invalid amount"}, status=status.HTTP_400_BAD_REQUEST)

        if operation == 'increment' or operation == 'add':
            # -------------------------------------------------------
            # MANAGER DEPOSIT — preserve every investor's current_amount.
            # Simply incrementing manager_capital increases initial_pool,
            # shrinking each investor's allocation_percentage and reducing
            # their current_amount (distorting P/L).
            # Use the same C_i re-scaling formula as views9.py.
            # -------------------------------------------------------
            M = dec_amt
            old_pool = Decimal(str(pam.pool_balance))
            old_initial = Decimal(str(pam.initial_pool))
            old_mc = Decimal(str(pam.manager_capital or 0))
            new_mc = old_mc + M
            old_mgr_val = (old_pool * old_mc / old_initial) if old_initial > 0 else old_pool
            new_mgr_val = old_mgr_val + M

            if new_mgr_val > 0:
                investments = list(PAMInvestment.objects.filter(pam_account=pam))
                for inv in investments:
                    C_i = (old_pool * Decimal(str(inv.amount)) / old_initial) if old_initial > 0 else Decimal('0')
                    # Use 6 d.p. to avoid cascaded rounding errors in current_amount
                    inv.amount = (C_i * new_mc / new_mgr_val).quantize(Decimal('0.000000'))
                if investments:
                    PAMInvestment.objects.bulk_update(investments, ['amount'])

            pam.manager_capital = new_mc
            # Update pool ledger so pool_balance reflects the deposit
            if pam._pool_balance_ledger is not None:
                pam._pool_balance_ledger = Decimal(str(pam._pool_balance_ledger)) + M
        else:
            pam.manager_capital = dec_amt

        pam.save()
        return Response(PAMAccountSerializer(pam).data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e), "traceback": traceback.format_exc()}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
