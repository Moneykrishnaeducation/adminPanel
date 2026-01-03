from rest_framework import serializers
from adminPanel.models import MonthlyTradeReport, ReportGenerationSchedule


class MonthlyTradeReportSerializer(serializers.ModelSerializer):
    """Serializer for monthly trade reports"""
    
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_id = serializers.CharField(source='user.user_id', read_only=True)
    report_month_display = serializers.CharField(source='report_month', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    pdf_file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = MonthlyTradeReport
        fields = [
            'id', 'user_name', 'user_email', 'user_id',
            'report_month', 'report_month_display',
            'generated_at', 'status', 'status_display',
            'total_trades', 'total_volume', 'total_commission', 'profit_loss',
            'email_sent_at', 'email_attempts', 'email_error',
            'password_hint', 'pdf_file_url'
        ]
        read_only_fields = [
            'id', 'generated_at', 'email_sent_at', 'email_attempts', 'email_error'
        ]
    
    def get_pdf_file_url(self, obj):
        """Get PDF file URL if available"""
        if obj.encrypted_pdf_file:
            return obj.encrypted_pdf_file.url
        return None


class ReportGenerationScheduleSerializer(serializers.ModelSerializer):
    """Serializer for report generation schedules"""
    
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_id = serializers.CharField(source='user.user_id', read_only=True)
    last_generated_display = serializers.SerializerMethodField()
    
    class Meta:
        model = ReportGenerationSchedule
        fields = [
            'id', 'user', 'user_name', 'user_email', 'user_id',
            'is_enabled', 'generation_day', 'email_enabled',
            'last_generated_month', 'last_generated_display',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_last_generated_display(self, obj):
        """Get formatted last generation date"""
        if obj.last_generated_month:
            return obj.last_generated_month.strftime('%B %Y')
        return 'Never'


class MonthlyReportListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing reports"""
    
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    report_month_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = MonthlyTradeReport
        fields = [
            'id', 'user_name', 'user_email',
            'report_month', 'report_month_display',
            'generated_at', 'status', 'status_display',
            'total_trades', 'total_commission',
            'email_sent_at'
        ]
    
    def get_report_month_display(self, obj):
        """Get formatted report month"""
        return obj.report_month.strftime('%B %Y')


class GenerateReportRequestSerializer(serializers.Serializer):
    """Serializer for report generation requests"""
    
    user_id = serializers.IntegerField(required=True)
    report_month = serializers.DateField(required=True, input_formats=['%Y-%m-%d', '%Y-%m'])
    send_email = serializers.BooleanField(default=True)
    force_regenerate = serializers.BooleanField(default=False)
    
    def validate_report_month(self, value):
        """Ensure report month is first day of month"""
        return value.replace(day=1)
    
    def validate_user_id(self, value):
        """Validate user exists and is a client"""
        from adminPanel.models import CustomUser
        try:
            user = CustomUser.objects.get(user_id=value, role='client')
            return value
        except CustomUser.DoesNotExist:
            raise serializers.ValidationError("User not found or is not a client")


class BulkReportGenerationSerializer(serializers.Serializer):
    """Serializer for bulk report generation"""
    
    report_month = serializers.DateField(required=True, input_formats=['%Y-%m-%d', '%Y-%m'])
    user_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
        help_text="List of user IDs. If empty, generates for all eligible users."
    )
    send_email = serializers.BooleanField(default=True)
    force_regenerate = serializers.BooleanField(default=False)
    
    def validate_report_month(self, value):
        """Ensure report month is first day of month"""
        return value.replace(day=1)
