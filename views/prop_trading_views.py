from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
import json
from ..decorators import role_required
from ..roles import UserRole
from rest_framework.permissions import IsAuthenticated
from adminPanel.permissions import IsAdminOrManager

# Mock data stores (in production, these would be database models)
PACKAGES_STORE = [
    {
        'id': 1,
        'name': 'Platinum',
        'bonus': 90000,
        'price': 10000,
        'tradable': 100000,
        'leverage': 100,
        'cutoff': 20000,
        'target': 20000,
        'time': 30,
        'share': 70,
        'status': True,
        'created_at': '2025-01-01T00:00:00Z'
    },
    {
        'id': 2,
        'name': 'Gold Plus',
        'bonus': 9000,
        'price': 1000,
        'tradable': 10000,
        'leverage': 100,
        'cutoff': 2000,
        'target': 2000,
        'time': 30,
        'share': 80,
        'status': True,
        'created_at': '2025-01-01T00:00:00Z'
    },
    {
        'id': 3,
        'name': 'Gold Challenge',
        'bonus': 4500,
        'price': 500,
        'tradable': 5000,
        'leverage': 100,
        'cutoff': 1000,
        'target': 1000,
        'time': 30,
        'share': 80,
        'status': True,
        'created_at': '2025-01-01T00:00:00Z'
    }
]

TRADERS_STORE = []

REQUESTS_STORE = []

@api_view(['GET'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def package_list_view(request):
    """Get list of prop trading packages, traders, and requests"""
    data_type = request.GET.get('type', 'packages')
    
    if data_type == 'packages':
        return Response({'packages': PACKAGES_STORE})
    elif data_type == 'traders':
        return Response({'traders': TRADERS_STORE})
    elif data_type == 'requests':
        return Response({'requests': REQUESTS_STORE})
    else:
        return Response({
            'packages': PACKAGES_STORE,
            'traders': TRADERS_STORE,
            'requests': REQUESTS_STORE
        })

@api_view(['POST'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def create_prop_trading_package(request):
    """Create a new prop trading package"""
    try:
        data = request.data
        
        # Generate new ID
        new_id = max([pkg['id'] for pkg in PACKAGES_STORE], default=0) + 1
        
        # Create new package
        new_package = {
            'id': new_id,
            'name': data.get('name', ''),
            'bonus': float(data.get('bonus', 0)),
            'price': float(data.get('price', 0)),
            'tradable': float(data.get('tradable', 0)),
            'leverage': int(data.get('leverage', 1)),
            'cutoff': float(data.get('cutoff', 0)),
            'target': float(data.get('target', 0)),
            'time': int(data.get('time', 0)),
            'share': float(data.get('share', 0)),
            'status': bool(data.get('status', True)),
            'created_at': timezone.now().isoformat()
        }
        
        # Add to store
        PACKAGES_STORE.append(new_package)
        
        return Response({
            'message': 'Package created successfully',
            'package': new_package
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        return Response({
            'error': 'Failed to create package',
            'details': str(e)
        }, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def approve_prop_request(request, request_id):
    """Approve a prop trading request"""
    try:
        # Find request
        req = None
        for r in REQUESTS_STORE:
            if r['id'] == request_id:
                req = r
                break
        
        if not req:
            return Response({'error': 'Request not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Update request status
        req['status'] = 'approved'
        req['handledBy'] = request.user.username if hasattr(request, 'user') else 'Admin'
        req['handledAt'] = timezone.now().isoformat()
        
        return Response({'message': 'Request approved successfully'})
        
    except Exception as e:
        return Response({
            'error': 'Failed to approve request',
            'details': str(e)
        }, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def reject_prop_request(request, request_id):
    """Reject a prop trading request"""
    try:
        # Find request
        req = None
        for r in REQUESTS_STORE:
            if r['id'] == request_id:
                req = r
                break
        
        if not req:
            return Response({'error': 'Request not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Update request status
        req['status'] = 'rejected'
        req['handledBy'] = request.user.username if hasattr(request, 'user') else 'Admin'
        req['handledAt'] = timezone.now().isoformat()
        
        return Response({'message': 'Request rejected successfully'})
        
    except Exception as e:
        return Response({
            'error': 'Failed to reject request',
            'details': str(e)
        }, status=status.HTTP_400_BAD_REQUEST)