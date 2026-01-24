# User detail API view to return all user fields including created_by_email and parent_ib_email
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from adminPanel.serializers import UserSerializer

class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        try:
            user = CustomUser.objects.get(user_id=user_id)
            serializer = UserSerializer(user)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

    def patch(self, request, user_id):
        try:
            user = CustomUser.objects.get(user_id=user_id)
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        data = request.data.copy()
        debug_info = {"incoming_data": dict(data)}
        errors = {}

        # Clean up empty fields to avoid validation errors
        for field in ['last_name', 'first_name', 'dob', 'phone_number', 'address']:
            if field in data and (data[field] == '' or data[field] is None):
                # For date fields that are empty, just remove them from the update
                if field == 'dob':
                    data.pop(field, None)
                    continue
                
                # For string fields, allow empty strings
                if isinstance(data[field], str):
                    data[field] = ''
        
        # Handle created_by and parent_ib as user IDs if present
        for rel_field in ["created_by", "parent_ib"]:
            if rel_field in data and data[rel_field]:
                try:
                    related_user = CustomUser.objects.get(user_id=data[rel_field])
                    data[rel_field] = related_user.id  # Set to PK for serializer
                    debug_info[f"resolved_{rel_field}_pk"] = related_user.id
                except CustomUser.DoesNotExist:
                    debug_info[f"resolved_{rel_field}_pk"] = None
                    error_msg = f"User with ID '{data[rel_field]}' not found for {rel_field.replace('_', ' ').title()} field."
                   
                    errors[rel_field] = error_msg
            elif rel_field in data and not data[rel_field]:
                # For empty relation fields, set to None
                data[rel_field] = None

        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


        
        # Use partial=True to update only the provided fields
        serializer = UserSerializer(user, data=data, partial=True)
        
        if serializer.is_valid():
            try:
                updated_user = serializer.save()
 
                
                # Get a fresh serialized response with all fields including method fields
                response_serializer = UserSerializer(updated_user, context={'request': request})
                return Response(response_serializer.data, status=status.HTTP_200_OK)
            except Exception as e:

                return Response({"error": f"Failed to save changes: {str(e)}"}, 
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    def delete(self, request, user_id):
        """
        Delete a user. Only allowed for admins/superusers.
        Supports fallback to PK when `user_id` lookup fails.
        """
        try:
            # Permission check: only superuser or admin manager_admin_status
            if not (request.user.is_superuser or (hasattr(request.user, 'manager_admin_status') and request.user.manager_admin_status and 'admin' in request.user.manager_admin_status.lower())):
                return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

            try:
                user = CustomUser.objects.get(user_id=user_id)
            except CustomUser.DoesNotExist:
                # Fallback to primary key
                user = CustomUser.objects.get(pk=user_id)

            user.delete()
            return Response({"success": True}, status=status.HTTP_200_OK)
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
from django.utils.timezone import now
from adminPanel.mt5.services import MT5ManagerActions
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, CharField, TextField
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from adminPanel.permissions import *
from rest_framework.response import Response
from rest_framework.views import APIView
from adminPanel.models import *
from adminPanel.serializers import *
from adminPanel.permissions import *
from .views import get_client_ip
from django.core.paginator import Paginator
from django.db.models import Q



class ListPropTradingPackagesView(APIView):
    """
    API View to fetch all prop trading packages with pagination, sorting, and searching.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        # Get query parameters
        page = int(request.GET.get("page", 1))
        page_size = int(request.GET.get("pageSize", 5))
        search_query = request.GET.get("search", "").strip()
        sort_by = request.GET.get("sortBy", "id")  # Default sorting by ID
        sort_order = request.GET.get("sortOrder", "asc")  # Default to ascending order

        # Apply search filter
        packages = Package.objects.all()
        if search_query:
            packages = packages.filter(Q(name__icontains=search_query))

        # Apply sorting
        if sort_order == "desc":
            sort_by = f"-{sort_by}"
        packages = packages.order_by(sort_by)

        # Apply pagination
        paginator = Paginator(packages, page_size)
        paginated_packages = paginator.get_page(page)

        # Serialize data
        serializer = PackageSerializer(paginated_packages, many=True)

        return Response(
            {
                "results": serializer.data,
                "count": paginator.count,
            },
            status=status.HTTP_200_OK
        )
    

class PropTradingRequestListView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        try:
            status_filter = request.query_params.get('status', None)
            search_query = request.query_params.get('search', '').strip()
            page = int(request.query_params.get('page', 1))  
            page_size = int(request.query_params.get('pageSize', 5))
            sort_by = request.query_params.get('sortBy', 'created_at')
            sort_order = request.query_params.get('sortOrder', 'asc') 

            requests = PropTradingRequest.objects.all()

            if status_filter:
                if status_filter == "pending":
                    requests = requests.filter(status="pending")
                else:
                    requests = requests.exclude(status="pending")  # Get non-pending requests

            if search_query:
                requests = requests.filter(
                    Q(user__username__icontains=search_query) |
                    Q(user__email__icontains=search_query) |
                    Q(package__name__icontains=search_query) |
                    Q(status__icontains=search_query)
                )

            if sort_order == 'asc':
                requests = requests.order_by(sort_by)
            else:
                requests = requests.order_by(f'-{sort_by}')

            paginator = PageNumberPagination()
            paginator.page_size = page_size
            paginated_requests = paginator.paginate_queryset(requests, request)

            serializer = PropTradingRequestSerializer(paginated_requests, many=True)

            return paginator.get_paginated_response(serializer.data)    
        except Exception as e:
            logging.error(f"Error fetching Prop Trading Requests: {str(e)}")
    
class PropTradingRequestDetailView(APIView):
    """
    API View to fetch details of a specific Prop Trading Request.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def get(self, request, pk):
        prop_request = get_object_or_404(PropTradingRequest, pk=pk)
        payment_proof_url = request.build_absolute_uri(prop_request.proof_of_payment.url) if prop_request.proof_of_payment else None
        
        return Response({
            "id": prop_request.id,
            "user_email": prop_request.user.email,
            "package_name": prop_request.package.name,
            "status": prop_request.status,
            "proof_of_payment": payment_proof_url,
            "created_at": prop_request.created_at,
            "handled_at": prop_request.handled_at,
        })
        

class OpenTicketsView(APIView):
    """
    View to get all tickets with status 'open', including features for search, sorting, and pagination.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, *args, **kwargs):
        try:
            # Role-Based Filtering
            if request.user.manager_admin_status in ['Admin', 'Manager']:
                queryset = Ticket.objects.filter(status='open')
            else:
                queryset = Ticket.objects.none()

            search_query = request.query_params.get('search', '')  # Search query
            sort_by = request.query_params.get('sortBy', 'created_at')  # Default sorting field
            sort_order = request.query_params.get('sortOrder', 'asc')  # Default sort order

            # Apply sorting (`-` for descending in Django)
            sort_by = f"-{sort_by}" if sort_order == "desc" else sort_by

            # Apply search query dynamically
            if search_query:
                search_fields = [f.name for f in Ticket._meta.fields if isinstance(f, (CharField, TextField))]
                queries = [Q(**{f"{field}__icontains": search_query}) for field in search_fields]
                combined_query = queries.pop()
                for query in queries:
                    combined_query |= query  # Combine search queries using OR

                queryset = queryset.filter(combined_query).order_by(sort_by)

            # Apply pagination
            paginator = PageNumberPagination()
            paginator.page_size = int(request.query_params.get('pageSize', 10))
            paginator.max_page_size = 100
            result_page = paginator.paginate_queryset(queryset, request)

            # Serialize and return
            serializer = TicketSerializer(result_page, many=True)
            return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
class ClosedTicketsView(APIView):
    """
    View to retrieve all tickets with status 'closed', supporting pagination, sorting, and search.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, *args, **kwargs):
        try:
            # Role-Based Filtering
            if request.user.manager_admin_status in ['Admin', 'Manager']:
                queryset = Ticket.objects.filter(status='closed')
            else:
                queryset = Ticket.objects.none()

            search_query = request.query_params.get('search', '')  # Search query
            sort_by = request.query_params.get('sortBy', 'created_at')  # Default sorting field
            sort_order = request.query_params.get('sortOrder', 'asc')  # Default sort order

            # Apply sorting (`-` for descending in Django)
            sort_by = f"-{sort_by}" if sort_order == "desc" else sort_by

            # Apply search query dynamically
            if search_query:
                search_fields = [f.name for f in Ticket._meta.fields if isinstance(f, (CharField, TextField))]
                queries = [Q(**{f"{field}__icontains": search_query}) for field in search_fields]
                combined_query = queries.pop()
                for query in queries:
                    combined_query |= query  # Combine search queries using OR

                queryset = queryset.filter(combined_query).order_by(sort_by)

            # Apply pagination
            paginator = PageNumberPagination()
            paginator.page_size = int(request.query_params.get('pageSize', 10))
            paginator.max_page_size = 100
            result_page = paginator.paginate_queryset(queryset, request)

            # Serialize and return
            serializer = TicketSerializer(result_page, many=True)
            return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

class PendingTicketsView(APIView):
    """
    View to retrieve all tickets with status 'pending', supporting pagination, sorting, and search.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, *args, **kwargs):
        try:
            # Role-Based Filtering
            if request.user.manager_admin_status in ['Admin', 'Manager']:
                queryset = Ticket.objects.filter(status='pending')
            else:
                queryset = Ticket.objects.none()

            search_query = request.query_params.get('search', '')  # Search query
            sort_by = request.query_params.get('sortBy', 'created_at')  # Default sorting field
            sort_order = request.query_params.get('sortOrder', 'asc')  # Default sort order

            # Apply sorting (`-` for descending in Django)
            sort_by = f"-{sort_by}" if sort_order == "desc" else sort_by

            # Apply search query dynamically
            if search_query:
                search_fields = [f.name for f in Ticket._meta.fields if isinstance(f, (CharField, TextField))]
                queries = [Q(**{f"{field}__icontains": search_query}) for field in search_fields]
                combined_query = queries.pop()
                for query in queries:
                    combined_query |= query  # Combine search queries using OR

                queryset = queryset.filter(combined_query).order_by(sort_by)

            # Apply pagination
            paginator = PageNumberPagination()
            paginator.page_size = int(request.query_params.get('pageSize', 10))
            paginator.max_page_size = 100
            result_page = paginator.paginate_queryset(queryset, request)

            # Serialize and return
            serializer = TicketSerializer(result_page, many=True)
            return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    
class TicketMessagesView(APIView):
    """
    View to retrieve and post messages for a specific ticket.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, ticket_id):
        """
        Retrieve all messages for a specific ticket.
        """
        try:
            messages = Message.objects.filter(ticket_id=ticket_id).order_by("created_at")
            if not messages.exists():
                return Response({"message": "No messages found for this ticket."}, status=status.HTTP_200_OK)
            serializer = MessageSerializer(messages, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            
            return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request, ticket_id):
        """
        Post a new message to a specific ticket.
        """
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            content = request.data.get("content", "").strip()
            file = request.FILES.get("file", None)

            if not content and not file:
                return Response(
                    {"error": "Either content or a file must be provided."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            message = Message(
                ticket=ticket,
                sender=request.user,
                content=content,
                file=file
            )
            message.full_clean()  
            message.save()
            serializer = MessageSerializer(message)
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Posted a new message to ticket ID {ticket_id}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=ticket_id,
                related_object_type="Ticket"
            )

            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class TicketStatusLogView(APIView):
    """
    View to log or retrieve status changes for a specific ticket.
    """
    def get(self, request, ticket_id):
        try:
            status_logs = TicketStatusLog.objects.filter(ticket_id=ticket_id)
            serializer = TicketStatusLogSerializer(status_logs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found."}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request, ticket_id):
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            data = request.data
            data['ticket'] = ticket.id  
            data['changed_by'] = request.user.id  
            serializer = TicketStatusLogSerializer(data=data)
            if serializer.is_valid():
                status_log = serializer.save()
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Logged a new status change for ticket ID {ticket_id}: {data.get('status')}",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=now(),
                    related_object_id=status_log.id,
                    related_object_type="TicketStatusLog"
                )
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found."}, status=status.HTTP_404_NOT_FOUND)
        
class CreateTicketView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        serializer = CreateTicketSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            ticket = serializer.save()

            
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Created a new ticket: (ID: {ticket.id})",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=ticket.id,
                related_object_type="Ticket"
            )

            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserTicketsView(APIView):
    """
    View to list all tickets created by the logged-in user.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        
        tickets = Ticket.objects.filter(created_by=request.user)
        serializer = TicketSerializer(tickets, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    

class ManagementActivityLogView(APIView):
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def get(self, request, *args, **kwargs):
        try:
            search_query = request.GET.get('search', '')  # Search query
            sort_by = request.GET.get('sortBy', 'timestamp')  # Default sorting field
            sort_order = request.GET.get('sortOrder', 'desc')  # Default sort order
            page = int(request.GET.get('page', 1))  # Current page
            page_size = int(request.GET.get('pageSize', 10))  # Records per page

            # Apply sorting (`-` for descending in Django)
            sort_by = f"-{sort_by}" if sort_order == "desc" else sort_by

            logs = ActivityLog.objects.filter(activity_category='management')

            # Apply search query
            if search_query:
                logs = logs.filter(
                    Q(user__username__icontains=search_query) |
                    Q(activity__icontains=search_query) |
                    Q(activity_type__icontains=search_query) |
                    Q(ip_address__icontains=search_query) |
                    Q(endpoint__icontains=search_query) |
                    Q(user_agent__icontains=search_query) |
                    Q(related_object_id__icontains=search_query) |
                    Q(related_object_type__icontains=search_query)
                )

            # Apply sorting
            logs = logs.order_by(sort_by)

            # Apply pagination
            total_count = logs.count()
            start = (page - 1) * page_size
            end = start + page_size
            logs = logs[start:end]

            # Serialize and return
            serializer = ActivityLogSerializer(logs, many=True)
            return Response({
                "total": total_count,
                "results": serializer.data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AvailableGroupsView(APIView):
    """
    Fetch available trading groups dynamically from MT5 manager.
    """
    permission_classes = [IsAdmin]
    
    def get(self, request):
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            mt5_actions = MT5ManagerActions()
            
            # Get detailed group configurations instead of just names
            groups_config = mt5_actions.get_all_group_configurations()
            
            # Get current configuration from database
            try:
                from adminPanel.models import TradeGroup
                db_groups = TradeGroup.objects.all()
                
                # Create a mapping of group names to database settings
                db_settings = {}
                for db_group in db_groups:
                    db_settings[db_group.name] = {
                        'is_active': getattr(db_group, 'is_active', False),
                        'type': getattr(db_group, 'type', None),
                        'description': getattr(db_group, 'description', '') or '',
                        'alias': getattr(db_group, 'alias', '') or '',
                        'is_alias': getattr(db_group, 'is_alias', False),
                        'is_default': getattr(db_group, 'is_default', False),
                        'is_demo_default': getattr(db_group, 'is_demo_default', False),
                    }
                
            except Exception as e:
                logger.warning(f"Could not load database group settings: {e}")
                db_settings = {}
            
            if groups_config:
                # Format groups with detailed information for frontend consumption
                formatted_groups = []
                
                
                for group in groups_config:
                    group_name = group['name']
                    
                    # Skip database-only groups that shouldn't be shown
                    if not group_name or group_name.startswith('MT5_Group_'):
                        logger.debug(f"Skipping database-only group: {group_name}")
                        continue
                    
                    db_info = db_settings.get(group_name, {})
                    
                    formatted_groups.append({
                        "id": group_name,  # Use name as ID for consistency
                        "value": group_name,
                        "label": f"{group_name} (Max Leverage: 1:{group.get('leverage_max', 1000)})",
                        "name": group_name,
                        "is_demo": group.get('is_demo', False),
                        "is_live": group.get('is_live', True),
                        "is_default": db_info.get('is_default', False),
                        "is_demo_default": db_info.get('is_demo_default', False),
                        "enabled": db_info.get('is_active', False),
                        "leverage_max": group.get('leverage_max', 1000),
                        "leverage_min": group.get('leverage_min', 1),
                        "currency": group.get('currency', 'USD'),
                        "deposit_min": group.get('deposit_min', 0),
                        "description": group.get('description', 'Trading group'),
                        "alias": db_info.get('alias', '') or '',
                        "group_type": "MT5"  # Mark as MT5 group
                    })
                
                
                return Response({
                    "groups": formatted_groups,  # Changed from "available_groups" to "groups"
                    "available_groups": formatted_groups,  # Keep both for compatibility
                    "source": "mt5_groups_detailed",
                    "success": True,
                    "total_groups": len(formatted_groups),
                    "demo_groups": len([g for g in formatted_groups if g['is_demo']]),
                    "live_groups": len([g for g in formatted_groups if g['is_live']])
                }, status=status.HTTP_200_OK)
            
            else:
                # Try basic group list if detailed config fails
                real_groups = mt5_actions.get_group_list('real')
                demo_groups = mt5_actions.get_group_list('demo')
                available_groups = real_groups + demo_groups
                
                if available_groups:
                    # Format groups for frontend consumption
                    formatted_groups = []
                    for i, group in enumerate(available_groups):
                        formatted_groups.append({
                            "id": group,  # Use group name as ID
                            "value": group,
                            "label": group,
                            "name": group,
                            "is_demo": "demo" in group.lower(),
                            "is_live": "demo" not in group.lower(),
                            "is_default": False,  # Default to false, user can set
                            "is_demo_default": False,  # Default to false, user can set
                            "enabled": False,  # Default to false, user can enable
                            "leverage_max": 1000,  # Default assumption
                            "leverage_min": 1,     # Default assumption
                            "currency": "USD",
                            "deposit_min": 0,
                            "description": f"{'Demo' if 'demo' in group.lower() else 'Live'} trading group",
                            "alias": ""  # Empty alias by default
                        })
                    
                    return Response({
                        "groups": formatted_groups,  # Changed from "available_groups" to "groups"
                        "available_groups": formatted_groups,  # Keep both for compatibility
                        "source": "mt5_groups_basic",
                        "success": True,
                        "total_groups": len(formatted_groups),
                        "warning": "Using basic group information - detailed config unavailable"
                    }, status=status.HTTP_200_OK)
                
                else:
                    # Fallback to default groups from group_config.json if MT5 returns empty
                    fallback_groups = [

                    ]
                    
                    return Response({
                        "groups": fallback_groups,  # Changed from "available_groups" to "groups"
                        "available_groups": fallback_groups,  # Keep both for compatibility
                        "source": "config_fallback",
                        "success": True,
                        "total_groups": len(fallback_groups),
                        "warning": "Using configured fallback trading groups - MT5 returned no groups"
                    }, status=status.HTTP_200_OK)
                
        except Exception as e:
            # Fallback groups in case of MT5 connection error
            logger.error(f"Error fetching groups from MT5: {str(e)}")
            fallback_groups = [
                {
                    "id": "Group1",
                    "value": "Group1", 
                    "label": "Group1 (Max Leverage: 1:100)", 
                    "name": "Group1",
                    "is_demo": False, 
                    "is_live": True,
                    "is_default": True,  # Set as default
                    "is_demo_default": False,
                    "enabled": True,  # Enable by default
                    "leverage_max": 100,
                    "leverage_min": 1,
                    "currency": "USD",
                    "deposit_min": 100,
                    "description": "Standard live trading group",
                    "alias": "Standard"
                },
                {
                    "id": "Group2",
                    "value": "Group2", 
                    "label": "Group2 (Max Leverage: 1:200)", 
                    "name": "Group2",
                    "is_demo": False, 
                    "is_live": True,
                    "is_default": False,
                    "is_demo_default": False,
                    "enabled": True,  # Enable by default
                    "leverage_max": 200,
                    "leverage_min": 1,
                    "currency": "USD",
                    "deposit_min": 50,
                    "description": "Standard live trading group with higher leverage",
                    "alias": "High Leverage"
                },
                {
                    "id": "Group3",
                    "value": "Group3", 
                    "label": "Group3 (Max Leverage: 1:500)", 
                    "name": "Group3",
                    "is_demo": False, 
                    "is_live": True,
                    "is_default": False,
                    "is_demo_default": False,
                    "enabled": False,  # Disabled by default
                    "leverage_max": 500,
                    "leverage_min": 1,
                    "currency": "USD",
                    "deposit_min": 25,
                    "description": "High leverage live trading group",
                    "alias": "Pro"
                },
                {
                    "id": "Demo",
                    "value": "Demo", 
                    "label": "Demo (Max Leverage: 1:1000)", 
                    "name": "Demo",
                    "is_demo": True, 
                    "is_live": False,
                    "is_default": False,
                    "is_demo_default": True,  # Set as demo default
                    "enabled": True,  # Enable by default
                    "leverage_max": 1000,
                    "leverage_min": 1,
                    "currency": "USD",
                    "deposit_min": 0,
                    "description": "Demo trading account",
                    "alias": "Demo"
                }
            ]
            
            return Response({
                "groups": fallback_groups,  # Changed from "available_groups" to "groups"
                "available_groups": fallback_groups,  # Keep both for compatibility
                "source": "error_fallback",
                "success": True,
                "total_groups": len(fallback_groups),
                "error": str(e),
                "message": "Using fallback groups due to MT5 connectivity issues"
            }, status=status.HTTP_200_OK)
  
        
class CreateTradingAccountGroupView(APIView):
    """
    Create a new TradingAccountGroup instance.
    """
    permission_classes = [IsAdmin]

    def post(self, request):
        try:
            data = request.data
            serializer = TradingAccountGroupSerializer(data=data)
            if serializer.is_valid():
                trading_account_group = serializer.save(created_by=request.user)
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Created a new trading account group: {str(trading_account_group)}",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=now(),
                    related_object_id=trading_account_group.id,
                    related_object_type="TradingAccountGroup"
                )
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SystemActivityLogView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, *args, **kwargs):
        logs = ActivityLog.objects.filter(activity_type='system').order_by('-timestamp')
        serializer = ActivityLogSerializer(logs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class ActivityLogView(APIView):
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def get(self, request):
        try:
            sort_by = request.GET.get('sortBy', 'timestamp')  
            sort_order = request.GET.get('sortOrder', 'desc')  
            if sort_order == 'desc':
                sort_by = f'-{sort_by}'

            activity_logs = ActivityLog.objects.all().order_by(sort_by)
                
            # Apply search filter if provided
            search_query = request.GET.get('search', '')
            if search_query:
                activity_logs = activity_logs.filter(
                    Q(user__username__icontains=search_query) |
                    Q(user__email__icontains=search_query) |
                    Q(activity__icontains=search_query) |
                    Q(activity_type__icontains=search_query)
                )

            paginator = PageNumberPagination()
            paginator.page_size = request.GET.get('pageSize', 10)
            result_page = paginator.paginate_queryset(activity_logs, request)
            serializer = ActivityLogSerializer(result_page, many=True)
            return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SingleActivityLogView(APIView):
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def get(self, request, user_id):
        try:
            user = CustomUser.objects.get(user_id=user_id)
            activity_logs = ActivityLog.objects.filter(user=user).order_by('-timestamp')
            serializer = ActivityLogSerializer(activity_logs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class EmailHandlerView(APIView):
    """
    API view to handle fetching email addresses and sending emails.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def get(self, request):
        """
        Retrieve email addresses of all active users.
        """
        try:
            emails = CustomUser.objects.filter(is_active=True).values_list('email', flat=True)
            return Response({"status": "success", "emails": list(emails)}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"status": "error", "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def post(self, request, *args, **kwargs):
        """
        Send an email to the provided email addresses with subject and body.
        """
        try:
            recipients = request.data.get('to', [])
            subject = request.data.get('subject', '')
            body = request.data.get('body', '')
            is_html = request.data.get('is_html', False)

            if not recipients or not subject or not body:
                return Response(
                    {"status": "error", "message": "Missing required fields: 'to', 'subject', or 'body'"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            from EmailSender import send_email
            send_email(
                subject=subject,
                message=body if not is_html else None,
                from_email='your_email@example.com',  
                recipient_list=recipients,
                html_message=body if is_html else None
            )
            
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Sent an email with subject '{subject}' to {len(recipients)} recipient(s).",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now()
            )

            return Response(
                {"status": "success", "message": "Email sent successfully!"},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"status": "error", "message": f"Failed to send email: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class ActivityLogListView(APIView):

    permission_classes = [IsAuthenticatedUser] 
    """
    API View to fetch activity logs for a specific user using email address.
    """

    def get(self, request, email):
        """
        Fetch all activity logs for the specified email address.
        """
        try:
            
            user = CustomUser.objects.get(email=email)
            activity_logs = ActivityLog.objects.filter(user=user).order_by('-timestamp')

            if not activity_logs.exists():
                return Response(
                    {"message": "No activity logs found for this user."},
                    status=status.HTTP_200_OK
                )

            serializer = ActivityLogSerializer(activity_logs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "User not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
class AdminManagerDetailView(APIView):
    permission_classes = [IsAdmin]
    """
    API View to fetch details of a specific admin/manager using email address.
    """

    def get(self, request, email):
        """
        Retrieve the details of the specified admin/manager by email.
        """
        try:
            user = CustomUser.objects.get(email=email)
            serializer = UserSerializer(user)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "User not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class TicketStatusChangeView(APIView):
    """
    API View to handle ticket status updates (Open, Pending, Closed, Reopened).
    """
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, ticket_id):
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            new_status = request.data.get("status")
            if new_status not in ['open', 'pending', 'closed']:
                return Response(
                    {"error": "Invalid status. Allowed values: open, pending, closed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            previous_status = ticket.status
            is_creator = ticket.created_by == request.user
            if is_creator and ticket.status == 'open' and new_status == 'pending':
                return Response(
                    {"error": "The creator cannot change an open ticket's status to pending."},
                    status=status.HTTP_200_OK,
                )
            if new_status == 'closed' and ticket.status in ['open', 'pending']:
                ticket.status = 'closed'
                ticket.closed_by = request.user
                ticket.closed_at = timezone.now()
            elif new_status == 'open' and ticket.status == 'closed':
                ticket.status = 'open'
                ticket.reopened_at = timezone.now()
            elif new_status == 'pending' and not is_creator:
                ticket.status = 'pending'
            else:
                return Response(
                    {"error": f"Cannot transition from {ticket.status} to {new_status}."},
                    status=status.HTTP_200_OK,
                )
            ticket.save()
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Changed ticket #{ticket.id} status from {previous_status} to {ticket.status}.",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=ticket.id,
                related_object_type="Ticket"
            )
            
            return Response(
                {"message": f"Ticket status updated to {ticket.status}.", "status": True},
                status=status.HTTP_200_OK,
            )
        except Ticket.DoesNotExist:
            return Response(
                {"error": "Ticket not found."}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class UserTicketsMainView(APIView):
    """
    API endpoint to fetch tickets for a specific user.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, user_id):
        """
        Fetch tickets for the given user ID.
        """
        user = CustomUser.objects.get(user_id=user_id)
        tickets = Ticket.objects.filter(created_by=user)
        serializer = TicketSerializer(tickets, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class AvailableLeverageOptionsView(APIView):
    """
    Fetch available leverage options dynamically from MT5 configuration.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            
            # Try to get leverage options from MT5 group configurations
            mt5_actions = MT5ManagerActions()
            
            # Get all group configurations to determine available leverage ranges
            groups_config = mt5_actions.get_all_group_configurations()
            
            leverage_options = []
            
            if groups_config and len(groups_config) > 0:
                # Collect unique leverage values from all groups
                leverage_set = set()
                max_leverage = 1000  # Default max
                min_leverage = 1     # Default min
                
                for group in groups_config:
                    group_max = group.get('leverage_max', 1000)
                    group_min = group.get('leverage_min', 1)
                    max_leverage = max(max_leverage, group_max)
                    min_leverage = min(min_leverage, group_min)
                    
                    
                    # Add common leverage ratios up to the group's max
                    common_ratios = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000]
                    for ratio in common_ratios:
                        if group_min <= ratio <= group_max:
                            leverage_set.add(ratio)
                
                # Convert to formatted options
                for ratio in sorted(leverage_set):
                    leverage_options.append({
                        "value": f"1:{ratio}",
                        "label": f"1:{ratio}",
                        "numeric_value": ratio
                    })
                
                
                return Response({
                    "leverage_options": leverage_options,
                    "source": "mt5_groups",
                    "success": True,
                    "max_leverage": max_leverage,
                    "min_leverage": min_leverage,
                    "groups_analyzed": len(groups_config),
                    "total_options": len(leverage_options)
                }, status=status.HTTP_200_OK)
            
            else:
                # Fallback to standard MT5-compatible options
                leverage_options = [
                    {"value": "1:1", "label": "1:1", "numeric_value": 1},
                    {"value": "1:2", "label": "1:2", "numeric_value": 2},
                    {"value": "1:5", "label": "1:5", "numeric_value": 5},
                    {"value": "1:10", "label": "1:10", "numeric_value": 10},
                    {"value": "1:20", "label": "1:20", "numeric_value": 20},
                    {"value": "1:50", "label": "1:50", "numeric_value": 50},
                    {"value": "1:100", "label": "1:100", "numeric_value": 100},
                    {"value": "1:200", "label": "1:200", "numeric_value": 200},
                    {"value": "1:500", "label": "1:500", "numeric_value": 500},
                    {"value": "1:1000", "label": "1:1000", "numeric_value": 1000}
                ]
                
                return Response({
                    "leverage_options": leverage_options,
                    "source": "mt5_compatible",
                    "success": True,
                    "warning": "No MT5 groups found, using standard options",
                    "total_options": len(leverage_options)
                }, status=status.HTTP_200_OK)
            
        except Exception as e:
            # Fallback to basic options if MT5 connection fails
            logger.error(f"❌ Error fetching leverage options from MT5: {str(e)}")
            leverage_options = [
                {"value": "1:50", "label": "1:50", "numeric_value": 50},
                {"value": "1:100", "label": "1:100", "numeric_value": 100},
                {"value": "1:200", "label": "1:200", "numeric_value": 200},
                {"value": "1:500", "label": "1:500", "numeric_value": 500}
            ]
            
            return Response({
                "leverage_options": leverage_options,
                "source": "error_fallback",
                "success": True,
                "error": str(e),
                "warning": "Using fallback leverage options due to MT5 connection error",
                "total_options": len(leverage_options)
            }, status=status.HTTP_200_OK)
        

class PublicLeverageTestView(APIView):
    """
    Public test endpoint for leverage options (no authentication required).
    """
    permission_classes = []  # No authentication required
    
    def get(self, request):
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            
            # Try to get leverage options from MT5 group configurations
            mt5_actions = MT5ManagerActions()
            
            # Get all group configurations to determine available leverage ranges
            groups_config = mt5_actions.get_all_group_configurations()
            
            leverage_options = []
            
            if groups_config and len(groups_config) > 0:
                # Collect unique leverage values from all groups
                leverage_set = set()
                max_leverage = 1000  # Default max
                min_leverage = 1     # Default min
                
                for group in groups_config:
                    group_max = group.get('leverage_max', 1000)
                    group_min = group.get('leverage_min', 1)
                    max_leverage = max(max_leverage, group_max)
                    min_leverage = min(min_leverage, group_min)
                    
                    
                    # Add common leverage ratios up to the group's max
                    common_ratios = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000]
                    for ratio in common_ratios:
                        if group_min <= ratio <= group_max:
                            leverage_set.add(ratio)
                
                # Convert to formatted options
                for ratio in sorted(leverage_set):
                    leverage_options.append({
                        "value": f"1:{ratio}",
                        "label": f"1:{ratio}",
                        "numeric_value": ratio
                    })
                
                
                return Response({
                    "leverage_options": leverage_options,
                    "source": "mt5_groups",
                    "success": True,
                    "max_leverage": max_leverage,
                    "min_leverage": min_leverage,
                    "groups_analyzed": len(groups_config),
                    "total_options": len(leverage_options),
                    "groups_detail": groups_config  # Include full group details for debugging
                }, status=status.HTTP_200_OK)
            
            else:
                # Fallback to standard MT5-compatible options
                leverage_options = [
                    {"value": "1:50", "label": "1:50", "numeric_value": 50},
                    {"value": "1:100", "label": "1:100", "numeric_value": 100},
                    {"value": "1:200", "label": "1:200", "numeric_value": 200},
                    {"value": "1:500", "label": "1:500", "numeric_value": 500}
                ]
                
                return Response({
                    "leverage_options": leverage_options,
                    "source": "mt5_fallback",
                    "success": True,
                    "warning": "No MT5 groups found, using fallback options",
                    "total_options": len(leverage_options)
                }, status=status.HTTP_200_OK)
            
        except Exception as e:
            # Fallback to basic options if MT5 connection fails
            logger.error(f"❌ Error fetching leverage options from MT5: {str(e)}")
            leverage_options = [
                {"value": "1:50", "label": "1:50", "numeric_value": 50},
                {"value": "1:100", "label": "1:100", "numeric_value": 100},
                {"value": "1:200", "label": "1:200", "numeric_value": 200},
                {"value": "1:500", "label": "1:500", "numeric_value": 500}
            ]
            
            return Response({
                "leverage_options": leverage_options,
                "source": "error_fallback",
                "success": True,
                "error": str(e),
                "warning": "Using fallback leverage options due to MT5 connection error",
                "total_options": len(leverage_options)
            }, status=status.HTTP_200_OK)
        
class UpdateTradingGroupSettingsView(APIView):
    """
    Update individual trading group settings (enable/disable, alias, role)
    """
    permission_classes = [IsSuperuser]
    
    def post(self, request):
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            group_id = request.data.get('group_id')
            enabled = request.data.get('enabled')
            alias = request.data.get('alias', '')
            is_default = request.data.get('default', False)
            is_demo = request.data.get('demo', False)
            
            if not group_id:
                return Response({
                    'success': False, 
                    'message': 'group_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get or create the group in database
            from adminPanel.models import TradeGroup
            group, created = TradeGroup.objects.get_or_create(
                name=group_id,
                defaults={
                    'alias': alias or '',
                    'type': 'demo' if is_demo else 'real',
                    'is_active': bool(enabled)
                }
            )
            
            # Update group settings
            if enabled is not None:
                group.is_active = bool(enabled)
            
            if alias is not None:
                group.alias = alias or ''
            
            if is_default or is_demo:
                # Clear other default/demo settings if this is being set as default
                if is_default:
                    TradeGroup.objects.exclude(id=group.id).update(is_default=False)
                    group.is_default = True
                    group.type = 'real'
                    
                if is_demo:
                    TradeGroup.objects.exclude(id=group.id).update(is_demo_default=False)
                    group.is_demo_default = True
                    group.type = 'demo'
            
            group.save()
            
            return Response({
                'success': True,
                'message': f'Group {group_id} updated successfully'
            })
            
        except Exception as e:
            logger.error(f"Error updating group settings: {str(e)}", exc_info=True)
            return Response({
                'success': False,
                'message': f'Error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CurrentGroupConfigurationView(APIView):
    """
    Get current group configuration showing default, demo, and enabled groups
    """
    permission_classes = [IsSuperuser]
    
    def get(self, request):
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            from adminPanel.models import TradeGroup
            
            # Get current settings from database
            db_groups = TradeGroup.objects.all()
            
            # Find default and demo groups
            default_group = db_groups.filter(is_default=True, is_active=True).first()
            demo_group = db_groups.filter(is_demo_default=True, is_active=True).first()
            enabled_groups = db_groups.filter(is_active=True)
            
            # Format response
            configuration = {
                'default_group': {
                    'id': default_group.name if default_group else None,
                    'name': default_group.name if default_group else 'None selected',
                    'alias': default_group.alias if default_group and default_group.alias else ''
                },
                'demo_group': {
                    'id': demo_group.name if demo_group else None,
                    'name': demo_group.name if demo_group else 'None selected',
                    'alias': demo_group.alias if demo_group and demo_group.alias else ''
                },
                'enabled_groups': [
                    {
                        'id': group.name,
                        'name': group.name,
                        'type': group.type,
                        'alias': group.alias or ''
                    } for group in enabled_groups
                ],
                'last_updated': max([group.updated_at for group in db_groups]) if db_groups else None
            }
            
            return Response({
                'success': True,
                'configuration': configuration
            })
            
        except Exception as e:
            logger.error(f"Error retrieving group configuration: {str(e)}", exc_info=True)
            return Response({
                'success': False,
                'message': f'Error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
class TestAvailableGroupsView(APIView):
    """
    Test endpoint for available trading groups (no authentication required)
    """
    permission_classes = []  # No authentication required
    
    def get(self, request):
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            mt5_actions = MT5ManagerActions()
            
            # Get detailed group configurations instead of just names
            groups_config = mt5_actions.get_all_group_configurations()
            
            # Get current configuration from database
            try:
                from adminPanel.models import TradeGroup
                db_groups = TradeGroup.objects.all()
                
                # Create a mapping of group names to database settings
                db_settings = {}
                for db_group in db_groups:
                    db_settings[db_group.name] = {
                        'is_active': db_group.is_active,
                        'type': db_group.type,
                        'description': db_group.description or ''
                    }
                
            except Exception as e:
                logger.warning(f"Could not load database group settings: {e}")
                db_settings = {}
            
            if groups_config:
                # Format groups with detailed information for frontend consumption
                formatted_groups = []
                
                # Filter to only include actual MT5 groups, not database-only entries
                
                for group in groups_config:
                    group_name = group['name']
                    
                    # Skip database-only groups that shouldn't be shown
                    if not group_name or group_name.startswith('MT5_Group_'):
                        continue
                    
                    db_info = db_settings.get(group_name, {})
                    
                    formatted_groups.append({
                        "id": group_name,  # Use name as ID for consistency
                        "value": group_name,
                        "label": f"{group_name} (Max Leverage: 1:{group.get('leverage_max', 1000)})",
                        "name": group_name,
                        "is_demo": group.get('is_demo', False),
                        "is_live": group.get('is_live', True),
                        "is_default": db_info.get('is_default', False),
                        "is_demo_default": db_info.get('is_demo_default', False),
                        "enabled": db_info.get('is_active', False),
                        "leverage_max": group.get('leverage_max', 1000),
                        "leverage_min": group.get('leverage_min', 1),
                        "currency": group.get('currency', 'USD'),
                        "deposit_min": group.get('deposit_min', 0),
                        "description": group.get('description', 'Trading group'),
                        "alias": db_info.get('alias', '') or '',
                        "group_type": "MT5"  # Mark as MT5 group
                    })
                
                
                return Response({
                    "groups": formatted_groups,
                    "available_groups": formatted_groups,
                    "source": "mt5_groups_detailed_test",
                    "success": True,
                    "total_groups": len(formatted_groups),
                    "demo_groups": len([g for g in formatted_groups if g['is_demo']]),
                    "live_groups": len([g for g in formatted_groups if g['is_live']]),
                    "test": True
                }, status=status.HTTP_200_OK)
            
            else:
                logger.warning("⚠️ No MT5 groups found, using fallback test groups")
                return Response({
                    "groups": [],
                    "available_groups": [],
                    "source": "config_fallback_test",
                    "success": True,
                    "total_groups": 0,
                    "warning": "Using configured fallback trading groups - MT5 returned no groups",
                    "test": True
                }, status=status.HTTP_200_OK)
                
        except Exception as e:
            logger.error(f"❌ Error fetching groups from MT5: {str(e)}", exc_info=True)

            return Response({
                "groups": [],
                "available_groups": [],
                "source": "error_fallback_test",
                "success": True,
                "total_groups": 0,
                "error": str(e),
                "message": "Using fallback groups due to MT5 connectivity issues",
                "test": True
            }, status=status.HTTP_200_OK)

