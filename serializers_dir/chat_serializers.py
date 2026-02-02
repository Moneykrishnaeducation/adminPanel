"""
Serializers for Manager and Admin Chat functionality
"""
from rest_framework import serializers
from adminPanel.models import ChatMessage
from django.contrib.auth import get_user_model

CustomUser = get_user_model()


class ChatMessageSerializer(serializers.ModelSerializer):
    sender_email = serializers.CharField(source='sender.email', read_only=True)
    recipient_email = serializers.CharField(source='recipient.email', read_only=True, allow_null=True)
    admin_name_display = serializers.CharField(read_only=True)

    class Meta:
        model = ChatMessage
        fields = [
            'id',
            'sender',
            'sender_email',
            'recipient',
            'recipient_email',
            'message',
            'image',
            'sender_type',
            'admin_name_display',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'sender_type', 'admin_name_display']


class ManagerChatMessageListSerializer(serializers.Serializer):
    """Serializer for fetching chat messages with client info"""
    messages = ChatMessageSerializer(many=True)
    connected_clients = serializers.SerializerMethodField()

    def get_connected_clients(self, obj):
        """Return list of connected clients (online users)"""
        from adminPanel.models import ActivityLog
        from django.utils import timezone
        from datetime import timedelta
        
        # Get users who were active in the last 5 minutes
        five_minutes_ago = timezone.now() - timedelta(minutes=5)
        recent_users = CustomUser.objects.filter(
            role='client',
            last_login_at__gte=five_minutes_ago
        ).values('id', 'email').distinct()
        
        return list(recent_users)
