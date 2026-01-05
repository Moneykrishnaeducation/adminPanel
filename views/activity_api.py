from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from ..models import ActivityLog
from ..serializers import ActivityLogSerializer
from ..permissions import IsAdminOrManager
from ..permissions import IsAdmin
from adminPanel.permissions import IsAdminOrManager
from rest_framework.permissions import IsAuthenticated

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
        
        # Validate pagination params
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 10
        if page_size > 100:
            page_size = 100  # Max 100 per page
        
        # Get total count
        total = ActivityLog.objects.filter(activity_category='client').count()
        
        # Calculate offset
        offset = (page - 1) * page_size
        
        # Get paginated results
        logs = ActivityLog.objects.filter(activity_category='client').order_by('-timestamp')[offset:offset + page_size]
        serializer = ActivityLogSerializer(logs, many=True)
        
        return Response({
            'data': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)