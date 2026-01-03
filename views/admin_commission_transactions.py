from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from adminPanel.models import CommissionTransaction, CustomUser


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_commission_transactions_view(request, user_id):
    """
    Simple admin endpoint returning a list of commission transaction dicts for the given IB user.
    Matches the admin frontend's expectation of an array of objects.
    """
    # Resolve IB user: try external user_id first, then pk
    ib_user = CustomUser.objects.filter(user_id=user_id).first()
    if not ib_user:
        try:
            ib_user = CustomUser.objects.get(pk=user_id)
        except CustomUser.DoesNotExist:
            return Response({'error': 'IB user not found'}, status=404)

    # Optional query params for paging are ignored here; admin frontend currently expects full list
    qs = CommissionTransaction.objects.filter(ib_user=ib_user).order_by('-created_at')
    try:
        items = list(qs.values(
            'position_id', 'client_user__email', 'client_trading_account__account_id', 'position_symbol',
            'total_commission', 'commission_to_ib', 'created_at', 'lot_size', 'profit', 'position_type', 'ib_level', 'position_direction'
        ))
        # Normalize fields for admin frontend
        out = []
        for t in items:
            out.append({
                'position_id': t.get('position_id'),
                'client_user': t.get('client_user__email'),
                'client_trading_account': t.get('client_trading_account__account_id'),
                'position_symbol': t.get('position_symbol'),
                'total_commission': float(t.get('total_commission') or 0),
                'amount': float(t.get('commission_to_ib') or 0),
                # Use Z-terminated ISO string for broader JS Date parsing compatibility
                'created_at': (t.get('created_at').isoformat().replace('+00:00', 'Z') if t.get('created_at') else None),
                'lot_size': float(t.get('lot_size') or 0),
                'profit': float(t.get('profit') or 0),
                'position_type': t.get('position_type'),
                'ib_level': t.get('ib_level'),
                'position_direction': t.get('position_direction'),
            })
        return Response(out)
    except Exception as e:
        return Response({'error': 'Failed to fetch transactions', 'details': str(e)}, status=500)
