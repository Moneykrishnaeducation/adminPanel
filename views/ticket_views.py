from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from ..models import Ticket, ActivityLog
from ..serializers import TicketSerializer
from ..permissions import IsAdmin, IsManager, OrPermission
from .views import get_client_ip
from rest_framework.permissions import IsAuthenticated

class TicketView(APIView):
    permission_classes = [OrPermission(IsAdmin, IsManager)]
    
    def get(self, request):
        try:
            if request.user.manager_admin_status == 'Admin':
                tickets = Ticket.objects.all()
            else:
                # For managers, only show tickets from their assigned clients (created_by)
                tickets = Ticket.objects.filter(
                    created_by__created_by=request.user
                )
            
            serializer = TicketSerializer(tickets, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        serializer = TicketSerializer(data=request.data)
        if serializer.is_valid():
            ticket = serializer.save(created_by=request.user)
            
            # Create activity log
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Created ticket #{ticket.id}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=ticket.id,
                related_object_type="Ticket"
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class TicketDetailView(APIView):
    permission_classes = [OrPermission(IsAdmin, IsManager)]
    
    def get(self, request, ticket_id):
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            
            # Check manager permissions
            if request.user.manager_admin_status == 'Manager' and getattr(ticket.created_by, 'created_by', None) != request.user:
                return Response(
                    {"error": "You don't have permission to view this ticket"},
                    status=status.HTTP_403_FORBIDDEN
                )
                
            serializer = TicketSerializer(ticket)
            return Response(serializer.data)
        except Ticket.DoesNotExist:
            return Response(
                {"error": "Ticket not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)