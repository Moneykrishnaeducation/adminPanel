"""
Manager-to-Admin chat views for HTTP API endpoints.
Manages real-time messaging between managers and admins.
"""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from adminPanel.permissions import IsAdminOrManager, IsManager
from adminPanel.models import ChatMessage, CustomUser
from adminPanel.serializers import ChatMessageSerializer
from django.contrib.auth import get_user_model
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([])
def get_manager_messages(request):
    """
    Retrieve all messages between manager and admins.
    Manager-specific endpoint that returns all manager-admin conversations.
    Does NOT automatically mark messages as read - manager must explicitly open chat.
    """
    try:
        user = request.user
        last_id = int(request.GET.get('last_id', 0))
        limit = int(request.GET.get('limit', 50))
        
        logger.info(f"[Manager Chat API] Getting messages for user {user.id} (email: {user.email})")
        logger.info(f"[Manager Chat API] User manager_admin_status: {getattr(user, 'manager_admin_status', 'NOT SET')}")
        
        # Get all messages where:
        # 1. Manager is the sender (to any admin)
        # 2. Any admin is the sender and manager is the recipient
        # This creates a unified conversation between manager and all admins
        messages_queryset = ChatMessage.objects.filter(
            Q(sender=user, sender_type='manager') |  # Messages from this manager
            Q(recipient=user, sender_type='admin')  # Messages to this manager from admins
        ).filter(id__gt=last_id).order_by('created_at')
        
        logger.info(f"[Manager Chat API] Found {messages_queryset.count()} messages for user {user.id}")
        
        # Get the last ID before slicing
        last_message_id = messages_queryset.values_list('id', flat=True).last() if messages_queryset.exists() else last_id
        
        # Now slice to get the limit
        messages = messages_queryset[:limit]
        
        serializer = ChatMessageSerializer(messages, many=True)
        
        logger.info(f"[Manager Chat API] Returning {len(serializer.data)} messages")
        
        return Response({
            'status': 'success',
            'messages': serializer.data,
            'last_id': last_message_id,
            'count': len(serializer.data)
        })
        
    except Exception as e:
        logger.error(f'Error retrieving manager messages: {e}')
        return Response(
            {'status': 'error', 'message': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([])
def mark_manager_messages_as_read(request):
    """
    Mark all unread admin messages to this manager as read.
    Called when the manager explicitly opens the chat.
    """
    try:
        user = request.user
        logger.info(f"[Manager Chat API] Manager {user.id} opened chat, marking messages as read")
        
        # Mark all unread admin messages to this manager as read
        updated_count = ChatMessage.objects.filter(
            recipient=user,
            sender_type='admin',
            is_read=False
        ).update(is_read=True)
        
        logger.info(f"[Manager Chat API] Marked {updated_count} messages as read for manager {user.id}")
        
        return Response({
            'status': 'success',
            'marked_as_read': updated_count
        })
    except Exception as e:
        logger.error(f'Error marking manager messages as read: {e}')
        return Response(
            {'status': 'error', 'message': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
@throttle_classes([])
def get_admin_manager_messages(request):
    """
    Admin endpoint to retrieve all messages between admin and managers.
    Admin-specific endpoint that returns all admin-manager conversations.
    Manager messages are broadcast to all admins (recipient=None).
    
    Query Parameters:
    - last_id: For pagination
    - limit: Number of messages to return
    - manager_id: Optional manager ID to mark that manager's messages as read
    """
    try:
        user = request.user
        last_id = int(request.GET.get('last_id', 0))
        limit = int(request.GET.get('limit', 50))
        manager_id = request.GET.get('manager_id')
        
        logger.info(f"[Admin Chat API] Getting manager messages for admin {user.id} (email: {user.email})")
        
        # Get all messages where:
        # 1. Admin is the sender (to any manager)
        # 2. Manager is the sender (broadcast to all admins - recipient=None)
        messages_queryset = ChatMessage.objects.filter(
            Q(sender=user, sender_type='admin') |  # Messages from this admin
            Q(sender_type='manager', recipient__isnull=True)  # Broadcast messages from managers to all admins
        ).filter(id__gt=last_id).order_by('created_at')
        
        logger.info(f"[Admin Chat API] Found {messages_queryset.count()} manager messages for admin {user.id}")
        
        # Mark messages from specific manager as read if manager_id is provided
        if manager_id:
            try:
                manager_id = int(manager_id)
                # Mark all unread messages from this manager as read
                updated_count = ChatMessage.objects.filter(
                    sender_id=manager_id,
                    sender_type='manager',
                    is_read=False
                ).update(is_read=True)
                
                if updated_count > 0:
                    logger.info(f"[Admin Chat API] Marked {updated_count} messages from manager {manager_id} as read")
            except (ValueError, TypeError):
                logger.warning(f"[Admin Chat API] Invalid manager_id provided: {manager_id}")
        
        # Get the last ID before slicing
        last_message_id = messages_queryset.values_list('id', flat=True).last() if messages_queryset.exists() else last_id
        
        # Now slice to get the limit
        messages = messages_queryset[:limit]
        
        serializer = ChatMessageSerializer(messages, many=True)
        
        logger.info(f"[Admin Chat API] Returning {len(serializer.data)} manager messages")
        
        return Response({
            'status': 'success',
            'messages': serializer.data,
            'last_id': last_message_id,
            'count': len(serializer.data)
        })
        
    except Exception as e:
        logger.error(f'[Admin Chat API] Error retrieving manager messages: {e}')
        return Response(
            {'status': 'error', 'message': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_manager_message(request):
    """
    Manager endpoint to send messages to admins (supports text and/or image).
    Messages from manager are broadcast to all admins.
    """
    try:
        data = request.data
        message_text = data.get('message', '').strip()
        image_file = request.FILES.get('image')
        
        logger.info(f"[Manager Chat API] Sending message from user {request.user.id} (email: {request.user.email})")
        
        # Allow message with text, image, or both
        if not message_text and not image_file:
            logger.warning("[Manager Chat API] Message or image is required but none provided")
            return Response(
                {'status': 'error', 'message': 'Message or image is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Deep-validate image attachment if provided
        if image_file:
            try:
                from clientPanel.views.views import validate_upload_file
            except Exception:
                validate_upload_file = None
            
            if validate_upload_file is not None:
                is_valid, err = validate_upload_file(image_file, max_size_mb=10)
                if not is_valid:
                    logger.error(f"[Manager Chat API] Invalid image: {err}")
                    return Response(
                        {'status': 'error', 'message': f'Invalid image: {err}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            else:
                try:
                    logger.warning('validate_upload_file not available; skipping deep image validation')
                except Exception:
                    pass
        
        # Create the chat message - manager to admins (no specific recipient)
        chat_message = ChatMessage.objects.create(
            sender=request.user,
            recipient=None,  # Manager messages are to all admins
            message=message_text,
            image=image_file if image_file else None,
            sender_type='manager',
            admin_sender_name=None  # Manager is always identified by sender
        )
        
        logger.info(f"[Manager Chat API] Message created with ID {chat_message.id}")
        
        serializer = ChatMessageSerializer(chat_message)
        
        return Response({
            'status': 'success',
            'message_id': chat_message.id,
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f'[Manager Chat API] Error sending manager message: {e}')
        return Response(
            {'status': 'error', 'message': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_admin_reply_to_manager(request):
    """
    Admin endpoint to send messages/replies to managers.
    Admins can reply to manager messages in the admin chat interface.
    Accepts manager_id as query parameter or in request body.
    """
    try:
        data = request.data
        message_text = data.get('message', '').strip()
        # Accept manager_id from both query params and request body
        manager_id = request.GET.get('manager_id') or data.get('manager_id')
        image_file = request.FILES.get('image')
        
        logger.info(f"[Admin Reply API] Admin {request.user.id} (email: {request.user.email}) sending reply to manager {manager_id}")
        
        # Allow message with text, image, or both
        if not message_text and not image_file:
            logger.warning("[Admin Reply API] Message or image is required but none provided")
            return Response(
                {'status': 'error', 'message': 'Message or image is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get the manager
        if manager_id:
            try:
                manager = get_user_model().objects.get(id=manager_id)
            except get_user_model().DoesNotExist:
                logger.error(f"[Admin Reply API] Manager {manager_id} not found")
                return Response(
                    {'status': 'error', 'message': 'Manager not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            logger.error("[Admin Reply API] Manager ID not provided")
            return Response(
                {'status': 'error', 'message': 'Manager ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Deep-validate image attachment if provided
        if image_file:
            try:
                from clientPanel.views.views import validate_upload_file
            except Exception:
                validate_upload_file = None
            
            if validate_upload_file is not None:
                is_valid, err = validate_upload_file(image_file, max_size_mb=10)
                if not is_valid:
                    logger.error(f"[Admin Reply API] Invalid image: {err}")
                    return Response(
                        {'status': 'error', 'message': f'Invalid image: {err}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
        
        # Get admin's display name
        admin_sender_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.email
        
        # Create the chat message - admin to specific manager
        chat_message = ChatMessage.objects.create(
            sender=request.user,
            recipient=manager,
            message=message_text,
            image=image_file if image_file else None,
            sender_type='admin',
            admin_sender_name=admin_sender_name
        )
        
        logger.info(f"[Admin Reply API] Reply message created with ID {chat_message.id}")
        
        serializer = ChatMessageSerializer(chat_message)
        
        return Response({
            'status': 'success',
            'message_id': chat_message.id,
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f'[Admin Reply API] Error sending admin reply to manager: {e}')
        return Response(
            {'status': 'error', 'message': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_manager_message(request, message_id):
    """
    Delete a manager message by ID.
    Only the original sender can delete their message.
    """
    try:
        try:
            message = ChatMessage.objects.get(id=message_id)
        except ChatMessage.DoesNotExist:
            return Response(
                {'status': 'error', 'message': 'Message not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Only allow deletion by sender
        if message.sender != request.user:
            return Response(
                {'status': 'error', 'message': 'Unauthorized to delete this message'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        message.delete()
        
        return Response({
            'status': 'success',
            'message': 'Message deleted successfully'
        })
        
    except Exception as e:
        logger.error(f'Error deleting manager message: {e}')
        return Response(
            {'status': 'error', 'message': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_manager_messages_as_read(request):
    """
    Mark all unread messages in manager-admin chat as read.
    """
    try:
        # Mark all unread messages where this user is the recipient as read
        updated_count = ChatMessage.objects.filter(
            recipient=request.user,
            is_read=False
        ).update(is_read=True)
        
        return Response({
            'status': 'success',
            'message': f'Marked {updated_count} messages as read'
        })
        
    except Exception as e:
        logger.error(f'Error marking manager messages as read: {e}')
        return Response(
            {'status': 'error', 'message': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_admin_manager_messages_as_read(request):
    """
    Mark all unread admin reply messages to a specific manager as read.
    Admin endpoint to mark messages they sent to a manager as read.
    """
    try:
        manager_id = request.data.get('manager_id')
        
        if not manager_id:
            return Response(
                {'status': 'error', 'message': 'manager_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Mark all unread messages from this manager as read
        updated_count = ChatMessage.objects.filter(
            sender_id=manager_id,
            sender_type='manager',
            is_read=False
        ).update(is_read=True)
        
        logger.info(f"[Manager Chat API] Admin {request.user.id} marked {updated_count} messages to manager {manager_id} as read")
        
        return Response({
            'status': 'success',
            'message': f'Marked {updated_count} messages as read'
        })
        
    except Exception as e:
        logger.error(f'Error marking admin manager messages as read: {e}')
        return Response(
            {'status': 'error', 'message': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
