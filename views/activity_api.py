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
        logs = ActivityLog.objects.filter(activity_category='management').order_by('-timestamp')[:200]
        serializer = ActivityLogSerializer(logs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAdminOrManager])
def activity_logs_client(request):
    try:
        logs = ActivityLog.objects.filter(activity_category='client').order_by('-timestamp')[:200]
        serializer = ActivityLogSerializer(logs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)