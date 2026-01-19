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
        # Support both 'pageSize' (camelCase from frontend) and 'page_size' (snake_case)
        page_size = int(request.GET.get('pageSize') or request.GET.get('page_size') or 100)
        
        # Validate pagination params
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 10
        if page_size > 100:
            page_size = 100  # Max 100 per page
        
        # Get total count - show ALL management logs EXCEPT login errors and database errors
        total = ActivityLog.objects.filter(activity_category='management').exclude(
            Q(status_code__gte=400) & (
                (Q(activity__icontains='login') | Q(endpoint__icontains='login')) |
                (Q(activity__icontains='database') | Q(activity__icontains='db') | Q(activity__icontains='connection') | Q(activity__icontains='unavailable'))
            )
        ).count()
        
        # Calculate offset
        offset = (page - 1) * page_size
        
        # Get paginated results - ALL management logs EXCEPT login and database errors
        logs = ActivityLog.objects.filter(activity_category='management').exclude(
            Q(status_code__gte=400) & (
                (Q(activity__icontains='login') | Q(endpoint__icontains='login')) |
                (Q(activity__icontains='database') | Q(activity__icontains='db') | Q(activity__icontains='connection') | Q(activity__icontains='unavailable'))
            )
        ).order_by('-timestamp')[offset:offset + page_size]
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
        # Support both 'pageSize' (camelCase from frontend) and 'page_size' (snake_case)
        page_size = int(request.GET.get('pageSize') or request.GET.get('page_size') or 100)
        query = request.GET.get('query', '').strip()
        
        # Validate pagination params
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 10
        if page_size > 100:
            page_size = 100  # Max 100 per page
        
        # Build base queryset - filtered by client category, showing ALL logs EXCEPT login and database errors
        # Login and database errors will only appear in Error Logs tab
        queryset = ActivityLog.objects.filter(
            activity_category='client'
        ).exclude(
            Q(status_code__gte=400) & (
                (Q(activity__icontains='login') | Q(endpoint__icontains='login')) |
                (Q(activity__icontains='database') | Q(activity__icontains='db') | Q(activity__icontains='connection') | Q(activity__icontains='unavailable'))
            )
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
@permission_classes([IsAdminOrManager])
def error_activity_logs(request):
    """
    Get login attempt error logs (status codes 4xx and 5xx) from both admin and client logs.
    Also includes related success logs from the same users to show context.
    
    This shows ONLY login-related failures (failed login attempts, wrong credentials, etc.)
    Plus related successful login activities from affected users.
    
    Query Parameters:
    - page: Page number (default: 1)
    - page_size: Number of records per page (default: 50)
    - query: Search query to filter logs
    """
    try:
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
        
        # Step 1: Get LOGIN and DATABASE-RELATED error logs (status >= 400)
        # This includes: failed login attempts, wrong credentials, database connection errors, service unavailable
        # Excludes: OTP errors, update/delete operation errors, etc.
        error_queryset = ActivityLog.objects.filter(
            Q(status_code__gte=400) & (
                (Q(activity__icontains='login') | Q(endpoint__icontains='login')) |
                (Q(activity__icontains='database') | Q(activity__icontains='db') | Q(activity__icontains='connection') | Q(activity__icontains='unavailable'))
            )
        )
        
        # Apply search filter to error logs if query provided
        if query:
            error_queryset = error_queryset.filter(
                Q(user__username__icontains=query) |
                Q(user__email__icontains=query) |
                Q(activity__icontains=query) |
                Q(ip_address__icontains=query) |
                Q(user_agent__icontains=query)
            )
        
        # Step 2: This is the only queryset we need - ONLY login and database errors
        # Do not include other errors from users with login errors
        combined_queryset = error_queryset
        
        # Apply search filter to combined queryset if query provided
        if query:
            combined_queryset = combined_queryset.filter(
                Q(user__username__icontains=query) |
                Q(user__email__icontains=query) |
                Q(activity__icontains=query) |
                Q(ip_address__icontains=query) |
                Q(user_agent__icontains=query)
            )
        
        # Get total count after filtering
        total = combined_queryset.count()
        
        # Calculate offset
        offset = (page - 1) * page_size
        
        # Get paginated results ordered by most recent
        logs = combined_queryset.order_by('-timestamp')[offset:offset + page_size]
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
        
        # Build queryset for IB clients' activity logs - all types
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