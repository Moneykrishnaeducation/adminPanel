from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

class UnauthorizedView(APIView):
    permission_classes = []  # Allow unauthenticated access
    
    def get(self, request):
        return Response({
            'error': 'You do not have permission to access this resource',
            'status': 'unauthorized'
        }, status=status.HTTP_403_FORBIDDEN)
