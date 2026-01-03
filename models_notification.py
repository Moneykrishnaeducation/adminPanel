"""
Notification System Models
Handles user notifications for various events like IB requests, account creation, etc.
"""

from django.db import models
from django.conf import settings
from django.utils import timezone


class Notification(models.Model):
    """
    User notification model for tracking various system events and requests
    """
    
    NOTIFICATION_TYPES = [
        ('IB', 'IB Request'),
        ('BANK', 'Bank Transaction'),
        ('CRYPTO', 'Crypto Transaction'),
        ('PROFILE', 'Profile Change'),
        ('DOCUMENT', 'Document Upload'),
        ('ACCOUNT', 'Account Creation'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('created', 'Created'),
        ('completed', 'Completed'),
    ]
    
    # User who receives the notification
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    
    # Notification details
    notification_type = models.CharField(
        max_length=20,
        choices=NOTIFICATION_TYPES,
        db_index=True
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    
    title = models.CharField(max_length=255)
    message = models.TextField()
    
    # Optional action URL (e.g., link to view details)
    action_url = models.CharField(max_length=500, blank=True, null=True)
    
    # Read status
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(blank=True, null=True)
    
    # Metadata for linking to related objects
    related_object_id = models.IntegerField(blank=True, null=True)
    related_object_type = models.CharField(max_length=50, blank=True, null=True)
    
    # Additional data as JSON
    metadata = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_read', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.notification_type} - {self.title} ({self.user.email})"
    
    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
    
    @classmethod
    def create_notification(cls, user, notification_type, status, title, message, 
                          action_url=None, related_object_id=None, 
                          related_object_type=None, metadata=None):
        """
        Helper method to create a notification
        
        Args:
            user: User instance
            notification_type: Type of notification (IB, BANK, CRYPTO, etc.)
            status: Status of the notification (pending, approved, created, etc.)
            title: Notification title
            message: Notification message
            action_url: Optional URL for action
            related_object_id: ID of related object
            related_object_type: Type of related object
            metadata: Additional metadata as dict
            
        Returns:
            Notification instance
        """
        return cls.objects.create(
            user=user,
            notification_type=notification_type,
            status=status,
            title=title,
            message=message,
            action_url=action_url,
            related_object_id=related_object_id,
            related_object_type=related_object_type,
            metadata=metadata or {}
        )
    
    @classmethod
    def get_unread_count(cls, user):
        """Get count of unread notifications for a user"""
        return cls.objects.filter(user=user, is_read=False).count()
    
    @classmethod
    def mark_all_read(cls, user):
        """Mark all notifications as read for a user"""
        cls.objects.filter(user=user, is_read=False).update(
            is_read=True,
            read_at=timezone.now()
        )
    
    @classmethod
    def delete_old_read_notifications(cls, days=7):
        """Delete notifications that have been read for more than specified days"""
        from datetime import timedelta
        cutoff_date = timezone.now() - timedelta(days=days)
        deleted_count = cls.objects.filter(
            is_read=True,
            read_at__isnull=False,
            read_at__lt=cutoff_date
        ).delete()
        return deleted_count[0] if deleted_count else 0
