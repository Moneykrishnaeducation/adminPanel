from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from adminPanel.models import CommissionTransaction, CustomUser
from django.db.models import Sum


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def commission_details_view(request, user_id):
    """
    Returns commission details and admin-style commission transactions for the specified IB user.
    Query params: level, start_date, end_date

    Response shape:
    {
      "details": [...],            # legacy detail objects built from model instances
      "total": <float>,
      "total_earnings": <float>,
      "transactions": [...]        # admin/client-shaped transaction list (position_id, client_user, amount, ...)
    }
    """
    level = request.GET.get('level')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    # Prepare optional filters from query params (level and date range)
    extra_filters = {}
    if level:
        try:
            extra_filters['ib_level'] = int(level)
        except Exception:
            pass
    if start_date:
        extra_filters['created_at__gte'] = start_date
    if end_date:
        extra_filters['created_at__lte'] = end_date

    import logging
    logger = logging.getLogger('commission_details_debug')

    # Resolve IB user: prefer external user_id, fallback to PK
    ib_user = None
    try:
        ib_user = CustomUser.objects.filter(user_id=user_id).first()
    except Exception:
        ib_user = None

    if not ib_user:
        try:
            ib_user = CustomUser.objects.get(pk=user_id)
        except CustomUser.DoesNotExist:
            logger.warning(f'[DEBUG] commission_details_view IB user not found: {user_id}')
            return Response({"error": "IB user not found"}, status=404)

    # Handle pagination parameters (server-side paging)
    try:
        page = int(request.GET.get('page', 1))
        if page < 1:
            page = 1
    except Exception:
        page = 1
    try:
        per_page = int(request.GET.get('per_page', 10))
        if per_page <= 0:
            per_page = 10
    except Exception:
        per_page = 10

    # Exclude demo account commissions
    base_qs = CommissionTransaction.objects.filter(
        ib_user=ib_user, **extra_filters
    ).exclude(
        client_trading_account__account_type='demo'
    ).order_by('-created_at')
    total_count = base_qs.count()


    # Calculate slice for this page (Django queryset slicing is efficient)
    offset = (page - 1) * per_page
    tx_page_qs = base_qs[offset: offset + per_page]

    details = []
    total = 0.0
    try:
        tx_ids_preview = list(base_qs.values_list('id', flat=True)[:5])

    except Exception:
        logger.warning('[DEBUG] commission_details_view could not preview transaction ids')

    # Only iterate the sliced page queryset to avoid loading all rows
    for tx in tx_page_qs:
        details.append({
            'symbol': getattr(tx, 'position_symbol', ''),
            'position_id': getattr(tx, 'position_id', ''),
            'created_at': str(getattr(tx, 'created_at', '')),
            'position_type': getattr(tx, 'position_type', 0),
            'commission': float(getattr(tx, 'commission_to_ib', 0) or 0),
            'level': getattr(tx, 'ib_level', ''),
            'client_email': getattr(getattr(tx, 'client_user', None), 'email', ''),
            'profile': getattr(tx, 'commission_profile_name', ''),
            'lot_size': getattr(tx, 'lot_size', 0),
            'profit': float(getattr(tx, 'profit', 0) or 0),
        })
        try:
            total += float(getattr(tx, 'commission_to_ib', 0) or 0)
        except Exception:
            pass

    # Calculate total_earnings using aggregates (respecting the same filters)
    try:
        agg = base_qs.aggregate(
            sum_comm_to_ib=Sum('commission_to_ib'),
            sum_total_commission=Sum('total_commission')
        )
        total_earnings_sum = agg.get('sum_comm_to_ib') or agg.get('sum_total_commission') or 0
        # ensure numeric
        total_earnings_sum = float(total_earnings_sum or 0)
        if not total_earnings_sum:
            total_earnings_sum = float(total or 0)
    except Exception as e:
        logger.warning(f'[DEBUG] Error calculating total_earnings_sum: {e}')
        total_earnings_sum = float(total or 0)

    # Calculate filtered volume (respecting filters) and overall aggregates (no filters)
    try:
        vol_agg = base_qs.aggregate(sum_volume=Sum('lot_size'))
        filtered_volume_sum = float(vol_agg.get('sum_volume') or 0)
    except Exception as e:
        logger.warning(f'[DEBUG] Error calculating filtered_volume_sum: {e}')
        filtered_volume_sum = 0.0

    try:
        overall_agg = CommissionTransaction.objects.filter(
            ib_user=ib_user
        ).exclude(
            client_trading_account__account_type='demo'
        ).aggregate(
            overall_volume=Sum('lot_size'),
            overall_commission=Sum('commission_to_ib')
        )
        overall_volume = float(overall_agg.get('overall_volume') or 0)
        overall_commission = float(overall_agg.get('overall_commission') or 0)
    except Exception as e:
        logger.warning(f'[DEBUG] Error calculating overall aggregates: {e}')
        overall_volume = 0.0
        overall_commission = 0.0

    # Build admin/client-shaped transactions list (values() for speed)
    try:
        trans_vals = base_qs.values(
            'position_id', 'client_user__email', 'client_trading_account__account_id',
            'position_symbol', 'total_commission', 'commission_to_ib', 'created_at', 'lot_size', 'profit'
        )
        # slice values queryset for page
        trans_page = trans_vals[offset: offset + per_page]
        transactions = [
            {
                'position_id': t.get('position_id'),
                'client_user': t.get('client_user__email'),
                'client_trading_account': t.get('client_trading_account__account_id'),
                'position_symbol': t.get('position_symbol'),
                'total_commission': float(t.get('total_commission') or 0),
                'amount': float(t.get('commission_to_ib') or 0),
                'created_at': t.get('created_at'),
                'lot_size': float(t.get('lot_size') or 0),
                'profit': float(t.get('profit') or 0),
            }
            for t in trans_page
        ]
    except Exception as e:
        logger.warning(f'[DEBUG] Error building transactions list: {e}')
        transactions = []


    return Response({
        'details': details,
        'total': float(total),
        'total_earnings': float(total_earnings_sum),
        # filtered / page-level volume and totals
        'total_volume': float(filtered_volume_sum),
        'filtered_volume': float(filtered_volume_sum),
        'overall_volume': float(overall_volume),
        'overall_commission': float(overall_commission),
        'transactions': transactions,
        'page': page,
        'per_page': per_page,
        'total_count': total_count,
    })
