from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from adminPanel.models import CustomUser

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_ib_commission_balance(request, user_id):
    user = CustomUser.objects.filter(user_id=user_id, IB_status=True).first()
    if not user:
        return Response({'error': 'IB user not found'}, status=404)
    commission_balance = float(user.total_earnings - user.total_commission_withdrawals)
    return Response({'commission_balance': commission_balance})
