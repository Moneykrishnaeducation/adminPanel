from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from ..models import ActivityLog
from ..serializers import ActivityLogSerializer
from ..permissions import IsAdminOrManager
from ..permissions import IsAdmin
from adminPanel.permissions import IsAdminOrManager
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from datetime import datetime

@api_view(['GET'])
@permission_classes([IsAdmin])
def activity_logs_staff(request):
    try:
        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        
        # Validate pagination params
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 10
        if page_size > 100:
            page_size = 100  # Max 100 per page
        
        # Get total count
        total = ActivityLog.objects.filter(activity_category='management').count()
        
        # Calculate offset
        offset = (page - 1) * page_size
        
        # Get paginated results
        logs = ActivityLog.objects.filter(activity_category='management').order_by('-timestamp')[offset:offset + page_size]
        serializer = ActivityLogSerializer(logs, many=True)
        
        return Response({
            'data': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAdminOrManager])
def activity_logs_client(request):
    try:
        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        query = request.GET.get('query', '').strip()
        
        # Validate pagination params
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 10
        if page_size > 100:
            page_size = 100  # Max 100 per page
        
        # Build base queryset - filtered by client category
        queryset = ActivityLog.objects.filter(activity_category='client')
        
        # Apply search filter if query provided
        if query:
            queryset = queryset.filter(
                Q(user__username__icontains=query) |
                Q(user__email__icontains=query) |
                Q(activity__icontains=query) |
                Q(ip_address__icontains=query) |
                Q(user_agent__icontains=query)
            )
        
        # Get total count after filtering
        total = queryset.count()
        
        # Calculate offset
        offset = (page - 1) * page_size
        
        # Get paginated results ordered by most recent
        logs = queryset.order_by('-timestamp')[offset:offset + page_size]
        serializer = ActivityLogSerializer(logs, many=True)
        
        return Response({
            'data': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
def ib_clients_activity_logs(request):
    """
    Get activity logs only for clients under the authenticated IB parent.
    This endpoint filters activity logs based on the client's parent_ib field.
    
    Query Parameters:
    - page: Page number (default: 1)
    - page_size: Number of records per page (default: 50)
    - query: Search query to filter logs
    """
    try:
        # Get the authenticated user
        authenticated_user = request.user
        
        # Check if the user is an IB (has clients)
        if not hasattr(authenticated_user, 'clients') or authenticated_user.clients.count() == 0:
            return Response({
                "error": "User is not an IB parent or has no clients",
                "user": authenticated_user.username,
                "ib_status": getattr(authenticated_user, 'IB_status', False)
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get all clients under this IB parent
        ib_clients = authenticated_user.clients.all()
        client_ids = ib_clients.values_list('id', flat=True)
        
        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))
        query = request.GET.get('query', '').strip()
        
        # Validate pagination params
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 50
        if page_size > 100:
            page_size = 100  # Max 100 per page
        
        # Build queryset for IB clients' activity logs
        queryset = ActivityLog.objects.filter(
            user_id__in=client_ids,
            activity_category='client'
        )
        
        # Apply search filter if query provided
        if query:
            queryset = queryset.filter(
                Q(user__username__icontains=query) |
                Q(user__email__icontains=query) |
                Q(activity__icontains=query) |
                Q(ip_address__icontains=query) |
                Q(user_agent__icontains=query)
            )
        
        # Get total count after filtering
        total = queryset.count()
        
        # Calculate offset and get paginated results
        offset = (page - 1) * page_size
        logs = queryset.order_by('-timestamp')[offset:offset + page_size]
        serializer = ActivityLogSerializer(logs, many=True)
        
        return Response({
            'data': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size,
            'clients_count': client_ids.count(),
            'ib_username': authenticated_user.username
        }, status=status.HTTP_200_OK)
    except ValueError as e:
        return Response({
            "error": "Invalid pagination parameters",
            "details": str(e)
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({
            "error": "Internal server error",
            "details": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)