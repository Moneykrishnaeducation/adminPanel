"""
Notification API Views
Handles notification CRUD operations and real-time updates
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.utils import timezone
from adminPanel.models_notification import Notification
from rest_framework.permissions import IsAuthenticated
from adminPanel.permissions import IsAdminOrManager


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_notifications(request):
    """
    Get all notifications for the authenticated user
    Supports filtering by type and status
    """
    # Check authentication
    if not request.user or not request.user.is_authenticated:
        return Response({
            'success': False,
            'error': 'Authentication required'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    user = request.user
    
    # Get query parameters
    notification_type = request.GET.get('type', None)
    notification_status = request.GET.get('status', None)
    unread_only = request.GET.get('unread_only', 'false').lower() == 'true'
    limit = int(request.GET.get('limit', 50))
    
    # Build query
    queryset = Notification.objects.filter(user=user)
    
    if notification_type and notification_type != 'all':
        queryset = queryset.filter(notification_type=notification_type)
    
    if notification_status and notification_status != 'all':
        queryset = queryset.filter(status=notification_status)
    
    if unread_only:
        queryset = queryset.filter(is_read=False)
    
    # Limit results
    notifications = queryset[:limit]
    
    # Serialize data
    notification_data = []
    for notif in notifications:
        notification_data.append({
            'id': notif.id,
            'notification_type': notif.notification_type,
            'status': notif.status,
            'title': notif.title,
            'message': notif.message,
            'action_url': notif.action_url,
            'is_read': notif.is_read,
            'read_at': notif.read_at.isoformat() if notif.read_at else None,
            'created_at': notif.created_at.isoformat(),
            'metadata': notif.metadata,
        })
    
    # Get unread count
    unread_count = Notification.get_unread_count(user)
    
    return Response({
        'success': True,
        'notifications': notification_data,
        'unread_count': unread_count,
        'total_count': queryset.count()
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_notification_read(request, notification_id):
    """
    Mark a specific notification as read
    """
    # Check authentication
    if not request.user or not request.user.is_authenticated:
        return Response({
            'success': False,
            'error': 'Authentication required'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    user = request.user
    
    try:
        notification = Notification.objects.get(id=notification_id, user=user)
        notification.mark_as_read()
        
        return Response({
            'success': True,
            'message': 'Notification marked as read',
            'unread_count': Notification.get_unread_count(user)
        })
    except Notification.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Notification not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_all_notifications_read(request):
    """
    Mark all notifications as read for the authenticated user
    """
    # Check authentication
    if not request.user or not request.user.is_authenticated:
        return Response({
            'success': False,
            'error': 'Authentication required'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    user = request.user
    
    Notification.mark_all_read(user)
    
    return Response({
        'success': True,
        'message': 'All notifications marked as read',
        'unread_count': 0
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_notification(request, notification_id):
    """
    Delete a specific notification
    """
    # Check authentication
    if not request.user or not request.user.is_authenticated:
        return Response({
            'success': False,
            'error': 'Authentication required'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    user = request.user
    
    try:
        notification = Notification.objects.get(id=notification_id, user=user)
        notification.delete()
        
        return Response({
            'success': True,
            'message': 'Notification deleted',
            'unread_count': Notification.get_unread_count(user)
        })
    except Notification.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Notification not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_unread_count(request):
    """
    Get count of unread notifications for the authenticated user
    """
    # Check authentication
    if not request.user or not request.user.is_authenticated:
        return Response({
            'success': False,
            'error': 'Authentication required'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    user = request.user
    unread_count = Notification.get_unread_count(user)
    
    return Response({
        'success': True,
        'unread_count': unread_count
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_notification(request):
    """
    Create a new notification (admin only or system-triggered)
    This can be used for testing or admin-initiated notifications
    """
    # Check authentication
    if not request.user or not request.user.is_authenticated:
        return Response({
            'success': False,
            'error': 'Authentication required'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    user = request.user
    
    # Get data from request
    notification_type = request.data.get('notification_type')
    status_value = request.data.get('status', 'created')
    title = request.data.get('title')
    message = request.data.get('message')
    action_url = request.data.get('action_url', None)
    target_user_id = request.data.get('target_user_id', None)
    
    # Validate required fields
    if not all([notification_type, title, message]):
        return Response({
            'success': False,
            'error': 'Missing required fields: notification_type, title, message'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Determine target user
    from adminPanel.models import CustomUser
    if target_user_id and (user.role == 'admin' or user.is_staff):
        try:
            target_user = CustomUser.objects.get(id=target_user_id)
        except CustomUser.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Target user not found'
            }, status=status.HTTP_404_NOT_FOUND)
    else:
        target_user = user
    
    # Create notification
    notification = Notification.create_notification(
        user=target_user,
        notification_type=notification_type,
        status=status_value,
        title=title,
        message=message,
        action_url=action_url,
        metadata=request.data.get('metadata', {})
    )
    
    return Response({
        'success': True,
        'message': 'Notification created successfully',
        'notification_id': notification.id
    }, status=status.HTTP_201_CREATED)
