from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from ..permissions import *
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated

@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def deposit_transactions(request):
    return Response({'message': 'Deposit transactions history'})

@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def withdrawal_history(request, user_id):
    return Response({'message': f'Withdrawal history for user {user_id}'})

@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def internal_transfer_transactions(request):
    return Response({'message': 'Internal transfer history'})

@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def credit_in_history(request):
    return Response({'message': 'Credit in history'})

@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def credit_out_history(request):
    return Response({'message': 'Credit out history'})