from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q, Sum, Count
from django.core.management import call_command
from django.http import HttpResponse, Http404
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from adminPanel.models import CustomUser
from adminPanel.models import MonthlyTradeReport, ReportGenerationSchedule
from adminPanel.serializers.monthly_reports import (
    MonthlyTradeReportSerializer,
    ReportGenerationScheduleSerializer,
    MonthlyReportListSerializer,
    GenerateReportRequestSerializer,
    BulkReportGenerationSerializer
)
from adminPanel.permissions import IsAdmin, IsManager, OrPermission
from adminPanel.services.monthly_report_generator import MonthlyTradeReportGenerator
from adminPanel.services.monthly_report_email_service import MonthlyReportEmailService
import logging
import os
from io import StringIO
import sys
from rest_framework.permissions import IsAuthenticated

logger = logging.getLogger(__name__)


class MonthlyReportPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def monthly_reports_list(request):
    """
    List all monthly trade reports with filtering and pagination
    """
    try:
        queryset = MonthlyTradeReport.objects.select_related('user').order_by('-report_month', '-generated_at')
        
        # Filtering
        user_id = request.GET.get('user_id')
        status_filter = request.GET.get('status')
        month_filter = request.GET.get('month')  # YYYY-MM format
        year_filter = request.GET.get('year')
        
        if user_id:
            queryset = queryset.filter(user__user_id=user_id)
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        if month_filter:
            try:
                month_date = datetime.strptime(month_filter, '%Y-%m').date().replace(day=1)
                queryset = queryset.filter(report_month=month_date)
            except ValueError:
                return Response({'error': 'Invalid month format. Use YYYY-MM'}, 
                              status=status.HTTP_400_BAD_REQUEST)
        
        if year_filter:
            try:
                year = int(year_filter)
                queryset = queryset.filter(report_month__year=year)
            except ValueError:
                return Response({'error': 'Invalid year format'}, 
                              status=status.HTTP_400_BAD_REQUEST)
        
        # Pagination
        paginator = MonthlyReportPagination()
        page = paginator.paginate_queryset(queryset, request)
        
        if page is not None:
            serializer = MonthlyReportListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = MonthlyReportListSerializer(queryset, many=True)
        return Response(serializer.data)
        
    except Exception as e:
        logger.error(f"Error listing monthly reports: {str(e)}")
        return Response({'error': 'Failed to fetch reports'}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def monthly_report_detail(request, report_id):
    """
    Get detailed information about a specific monthly report
    """
    try:
        report = get_object_or_404(MonthlyTradeReport, id=report_id)
        serializer = MonthlyTradeReportSerializer(report)
        return Response(serializer.data)
        
    except Exception as e:
        logger.error(f"Error fetching monthly report detail: {str(e)}")
        return Response({'error': 'Failed to fetch report details'}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAdmin])
def generate_monthly_report(request):
    """
    Generate a monthly report for a specific user
    """
    try:
        serializer = GenerateReportRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        user = get_object_or_404(CustomUser, user_id=data['user_id'])
        
        # Capture command output
        output = StringIO()
        
        # Run the management command
        call_command(
            'generate_monthly_reports',
            user_id=data['user_id'],
            month=data['report_month'].strftime('%Y-%m'),
            no_email=not data['send_email'],
            force=data['force_regenerate'],
            stdout=output
        )
        
        # Get the generated report
        report = MonthlyTradeReport.objects.filter(
            user=user,
            report_month=data['report_month']
        ).first()
        
        if report:
            serializer = MonthlyTradeReportSerializer(report)
            return Response({
                'success': True,
                'message': 'Report generated successfully',
                'report': serializer.data,
                'command_output': output.getvalue()
            })
        else:
            return Response({
                'success': False,
                'message': 'Report generation failed',
                'command_output': output.getvalue()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except Exception as e:
        logger.error(f"Error generating monthly report: {str(e)}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAdmin])
def bulk_generate_reports(request):
    """
    Generate monthly reports for multiple users or all eligible users
    """
    try:
        serializer = BulkReportGenerationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        
        # Capture command output
        output = StringIO()
        
        # Prepare command arguments
        cmd_args = [
            'generate_monthly_reports',
            f'--month={data["report_month"].strftime("%Y-%m")}'
        ]
        
        if not data['send_email']:
            cmd_args.append('--no-email')
        
        if data['force_regenerate']:
            cmd_args.append('--force')
        
        # If specific user IDs provided, generate individual reports
        if data.get('user_ids'):
            results = []
            for user_id in data['user_ids']:
                try:
                    call_command(
                        'generate_monthly_reports',
                        user_id=user_id,
                        month=data['report_month'].strftime('%Y-%m'),
                        no_email=not data['send_email'],
                        force=data['force_regenerate'],
                        stdout=output
                    )
                    results.append({'user_id': user_id, 'success': True})
                except Exception as e:
                    results.append({'user_id': user_id, 'success': False, 'error': str(e)})
            
            return Response({
                'success': True,
                'message': f'Bulk generation completed for {len(data["user_ids"])} users',
                'results': results,
                'command_output': output.getvalue()
            })
        else:
            # Generate for all eligible users
            call_command(*cmd_args, stdout=output)
            
            return Response({
                'success': True,
                'message': 'Bulk generation completed for all eligible users',
                'command_output': output.getvalue()
            })
            
    except Exception as e:
        logger.error(f"Error in bulk report generation: {str(e)}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def resend_report_email(request, report_id):
    """
    Resend email for an existing monthly report
    """
    try:
        report = get_object_or_404(MonthlyTradeReport, id=report_id)
        
        if not report.encrypted_pdf_file:
            return Response({
                'success': False,
                'error': 'Report PDF file not found'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get PDF file path
        pdf_path = report.encrypted_pdf_file.path
        password = report.get_password()
        
        # Send email
        success = MonthlyReportEmailService.send_monthly_report(
            report.user, report, pdf_path, password
        )
        
        if success:
            return Response({
                'success': True,
                'message': 'Email sent successfully'
            })
        else:
            return Response({
                'success': False,
                'error': 'Failed to send email'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except Exception as e:
        logger.error(f"Error resending report email: {str(e)}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def download_report_pdf(request, report_id):
    """
    Download the encrypted PDF report (for admin use)
    """
    try:
        report = get_object_or_404(MonthlyTradeReport, id=report_id)
        
        if not report.encrypted_pdf_file:
            raise Http404("Report PDF file not found")
        
        # Check if file exists
        if not os.path.exists(report.encrypted_pdf_file.path):
            raise Http404("Report PDF file not found on disk")
        
        # Return file response
        with open(report.encrypted_pdf_file.path, 'rb') as pdf_file:
            response = HttpResponse(pdf_file.read(), content_type='application/pdf')
            filename = f"monthly_report_{report.report_month.strftime('%Y%m')}_{report.user.user_id}.pdf"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
            
    except Exception as e:
        logger.error(f"Error downloading report PDF: {str(e)}")
        raise Http404("Report file not available")


@api_view(['DELETE'])
@permission_classes([IsAdmin])
def delete_monthly_report(request, report_id):
    """
    Delete a monthly report and its associated files
    """
    try:
        report = get_object_or_404(MonthlyTradeReport, id=report_id)
        
        # Delete PDF file if exists
        if report.encrypted_pdf_file and os.path.exists(report.encrypted_pdf_file.path):
            os.remove(report.encrypted_pdf_file.path)
        
        # Delete report record
        report.delete()
        
        return Response({
            'success': True,
            'message': 'Report deleted successfully'
        })
        
    except Exception as e:
        logger.error(f"Error deleting monthly report: {str(e)}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def report_generation_schedules(request):
    """
    List all report generation schedules
    """
    try:
        schedules = ReportGenerationSchedule.objects.select_related('user').order_by('user__first_name')
        serializer = ReportGenerationScheduleSerializer(schedules, many=True)
        return Response(serializer.data)
        
    except Exception as e:
        logger.error(f"Error fetching report schedules: {str(e)}")
        return Response({'error': 'Failed to fetch schedules'}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST', 'PUT'])
@permission_classes([IsAdmin])
def manage_report_schedule(request, user_id=None):
    """
    Create or update a report generation schedule for a user
    """
    try:
        if user_id:
            # Update existing schedule
            user = get_object_or_404(CustomUser, user_id=user_id)
            schedule, created = ReportGenerationSchedule.objects.get_or_create(user=user)
            serializer = ReportGenerationScheduleSerializer(schedule, data=request.data, partial=True)
        else:
            # Create new schedule
            serializer = ReportGenerationScheduleSerializer(data=request.data)
        
        if serializer.is_valid():
            serializer.save()
            return Response({
                'success': True,
                'message': 'Schedule saved successfully',
                'data': serializer.data
            })
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        logger.error(f"Error managing report schedule: {str(e)}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def report_statistics(request):
    """
    Get statistics about monthly reports
    """
    try:
        # Get current month and previous months
        today = date.today()
        current_month = today.replace(day=1)
        last_month = current_month - relativedelta(months=1)
        last_year = current_month - relativedelta(years=1)
        
        stats = {
            'total_reports': MonthlyTradeReport.objects.count(),
            'reports_this_month': MonthlyTradeReport.objects.filter(
                report_month=current_month
            ).count(),
            'reports_last_month': MonthlyTradeReport.objects.filter(
                report_month=last_month
            ).count(),
            'reports_this_year': MonthlyTradeReport.objects.filter(
                report_month__year=today.year
            ).count(),
            'pending_reports': MonthlyTradeReport.objects.filter(
                status='generating'
            ).count(),
            'failed_reports': MonthlyTradeReport.objects.filter(
                status='failed'
            ).count(),
            'users_with_schedules': ReportGenerationSchedule.objects.filter(
                is_enabled=True
            ).count(),
            'total_users': CustomUser.objects.filter(role='client', is_active=True).count()
        }
        
        # Monthly breakdown for the last 12 months
        monthly_stats = []
        for i in range(12):
            month = current_month - relativedelta(months=i)
            count = MonthlyTradeReport.objects.filter(report_month=month).count()
            monthly_stats.append({
                'month': month.strftime('%Y-%m'),
                'month_name': month.strftime('%B %Y'),
                'count': count
            })
        
        stats['monthly_breakdown'] = monthly_stats
        
        return Response(stats)
        
    except Exception as e:
        logger.error(f"Error fetching report statistics: {str(e)}")
        return Response({'error': 'Failed to fetch statistics'}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)
