from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from ..models import Ticket, ActivityLog
from ..serializers import TicketSerializer, TicketWithMessagesSerializer
from ..permissions import IsAdmin, IsManager, OrPermission
from .views import get_client_ip
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

class TicketView(APIView):
    permission_classes = [OrPermission(IsAdmin, IsManager)]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def get(self, request):
        try:
            # Support server-side filtering by user id or username when provided
            # Accept several query param names for user id for compatibility with different clients
            user_param = (
                request.query_params.get('userid') or
                request.query_params.get('userId')
            )
            username_param = (
                request.query_params.get('username') or
                request.query_params.get('user_name')
            )
            status_param = request.query_params.get('status')

            if user_param or username_param:
                # Resolve the target user
                from django.contrib.auth import get_user_model
                User = get_user_model()
                target_user = None
                if user_param:
                    try:
                        target_user = User.objects.get(id=int(user_param))
                    except (User.DoesNotExist, ValueError):
                        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
                else:
                    try:
                        target_user = User.objects.get(username=username_param)
                    except User.DoesNotExist:
                        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

                # Admins may view any user's tickets; managers may view their own or their clients' tickets
                if request.user.manager_admin_status == 'Admin':
                    tickets = Ticket.objects.filter(created_by=target_user)
                else:
                    # For managers: allow if target_user is them or one of their clients
                    from django.db.models import Q
                    if target_user == request.user or getattr(target_user, 'created_by', None) == request.user:
                        tickets = Ticket.objects.filter(created_by=target_user)
                    else:
                        return Response({"error": "You don't have permission to view this user's tickets"}, status=status.HTTP_403_FORBIDDEN)
            else:
                # Default behavior: Admins see all tickets; managers/clients see their own and their clients'
                if request.user.manager_admin_status == 'Admin':
                    tickets = Ticket.objects.all()
                else:
                    from django.db.models import Q
                    tickets = Ticket.objects.filter(
                        Q(created_by=request.user) |  # Tickets they created
                        Q(created_by__created_by=request.user)  # Tickets from their clients
                    )

            # Filter by status if provided
            if status_param:
                tickets = tickets.filter(status=status_param)
                serializer = TicketWithMessagesSerializer(tickets, many=True, context={'request': request})
                return Response(serializer.data)

            # Group tickets by status
            grouped_tickets = {
                'open': [],
                'pending': [],
                'closed': [],
            }

            serializer = TicketWithMessagesSerializer(tickets, many=True, context={'request': request})
            for ticket_data in serializer.data:
                status_key = ticket_data.get('status', 'open')
                grouped_tickets[status_key].append(ticket_data)

            return Response(grouped_tickets)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        # Extract only subject and description, ignore extra fields like 'documents'
        data = {
            'subject': request.data.get('subject'),
            'description': request.data.get('description'),
        }
        
        serializer = TicketSerializer(data=data)
        if serializer.is_valid():
            ticket = serializer.save(created_by=request.user)

            # Save any uploaded files as messages attached to the ticket
            from ..models import Message
            files = request.FILES.getlist('documents') if hasattr(request, 'FILES') else []
            for f in files:
                Message.objects.create(ticket=ticket, sender=request.user, file=f)
            
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
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def get(self, request, ticket_id):
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            
            # Check manager permissions
            if request.user.manager_admin_status == 'Manager' and getattr(ticket.created_by, 'created_by', None) != request.user:
                return Response(
                    {"error": "You don't have permission to view this ticket"},
                    status=status.HTTP_403_FORBIDDEN
                )
                
            serializer = TicketWithMessagesSerializer(ticket, context={'request': request})
            return Response(serializer.data)
        except Ticket.DoesNotExist:
            return Response(
                {"error": "Ticket not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def patch(self, request, ticket_id):
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            
            # Check manager permissions
            if request.user.manager_admin_status == 'Manager':
                # Manager can update only their own tickets or their clients' tickets
                if ticket.created_by != request.user and getattr(ticket.created_by, 'created_by', None) != request.user:
                    return Response(
                        {"error": "You don't have permission to update this ticket"},
                        status=status.HTTP_403_FORBIDDEN
                    )
            
            # Update status if provided
            if 'status' in request.data:
                new_status = request.data.get('status')
                ticket.status = new_status
                
                # If closing the ticket, set closed_by and closed_at
                if new_status == 'closed':
                    ticket.closed_by = request.user
                    ticket.closed_at = timezone.now()
                
                ticket.save()
            
            # Handle comment as a message if provided
            if 'comment' in request.data and request.data.get('comment'):
                from ..models import Message
                Message.objects.create(
                    ticket=ticket,
                    sender=request.user,
                    content=request.data.get('comment')
                )

            # Handle uploaded files in patch as message attachments
            if hasattr(request, 'FILES') and request.FILES:
                from ..models import Message
                files = request.FILES.getlist('documents')
                for f in files:
                    Message.objects.create(ticket=ticket, sender=request.user, file=f)
            
            serializer = TicketSerializer(ticket)
            return Response(serializer.data)
        except Ticket.DoesNotExist:
            return Response(
                {"error": "Ticket not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)