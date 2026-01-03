from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import IsAuthenticated
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from adminPanel.models import CustomUser
from adminPanel.serializers import UserSerializer

# Unified Pending Requests API
@csrf_exempt
@api_view(['GET'])
@authentication_classes([JWTAuthentication, TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def unified_pending_requests(request):
    """
    Returns all pending requests (IB, Bank, Profile, Crypto) with a 'request_type' field for frontend tab separation.
    """
    try:
        # IB Requests
        ib_requests = []
        if 'Admin' in getattr(request.user, 'manager_admin_status', '') or 'Manager' in getattr(request.user, 'manager_admin_status', '') or getattr(request.user, 'is_staff', False):
            for ib in IBRequest.objects.filter(status="PENDING"):
                ib_requests.append({
                    'id': ib.id,
                    'user_id': getattr(ib.user, 'user_id', None),
                    'username': getattr(ib.user, 'username', ''),
                    'email': getattr(ib.user, 'email', ''),
                    'commissioning_profile': getattr(ib, 'profile_name', ''),
                    'uploaded_at': ib.created_at.isoformat() if hasattr(ib, 'created_at') and ib.created_at else None,
                    'request_type': 'ib',
                })

        # Bank Details Requests
        bank_requests = []
        if 'Admin' in getattr(request.user, 'manager_admin_status', '') or 'Manager' in getattr(request.user, 'manager_admin_status', '') or getattr(request.user, 'is_staff', False):
            for bank in BankDetailsRequest.objects.filter(status="PENDING"):
                bank_requests.append({
                    'id': bank.id,
                    'user_id': getattr(bank.user, 'user_id', None),
                    'username': getattr(bank.user, 'username', ''),
                    'email': getattr(bank.user, 'email', ''),
                    'bank_name': getattr(bank, 'bank_name', ''),
                    'account_number': getattr(bank, 'account_number', ''),
                    'branch': getattr(bank, 'branch', ''),
                    'ifsc_code': getattr(bank, 'ifsc_code', ''),
                    'uploaded_at': bank.created_at.isoformat() if hasattr(bank, 'created_at') and bank.created_at else None,
                    'request_type': 'bank',
                })

        # Profile Change Requests
        profile_requests = []
        if 'Admin' in getattr(request.user, 'manager_admin_status', '') or 'Manager' in getattr(request.user, 'manager_admin_status', '') or getattr(request.user, 'is_staff', False):
            for profile in ChangeRequest.objects.filter(status="PENDING"):
                profile_requests.append({
                    'id': profile.id,
                    'user_id': getattr(profile.user, 'user_id', None),
                    'username': getattr(profile.user, 'username', ''),
                    'email': getattr(profile.user, 'email', ''),
                    'requested_changes': getattr(profile, 'requested_changes', ''),
                    'id_proof': getattr(profile, 'id_proof', ''),
                    'address_proof': getattr(profile, 'address_proof', ''),
                    'uploaded_at': profile.created_at.isoformat() if hasattr(profile, 'created_at') and profile.created_at else None,
                    'request_type': 'profile',
                })

        # Crypto Details Requests
        crypto_requests = []
        if 'Admin' in getattr(request.user, 'manager_admin_status', '') or 'Manager' in getattr(request.user, 'manager_admin_status', '') or getattr(request.user, 'is_staff', False):
            for crypto in CryptoDetails.objects.filter(status="pending"):
                crypto_requests.append({
                    'id': crypto.id,
                    'user_id': getattr(crypto.user, 'user_id', None),
                    'username': getattr(crypto.user, 'username', ''),
                    'email': getattr(crypto.user, 'email', ''),
                    'wallet_address': getattr(crypto, 'wallet_address', ''),
                    'exchange': getattr(crypto, 'exchange', ''),
                    'uploaded_at': crypto.created_at.isoformat() if hasattr(crypto, 'created_at') and crypto.created_at else None,
                    'request_type': 'crypto',
                })

        # Combine all
        all_requests = ib_requests + bank_requests + profile_requests + crypto_requests

        return Response({
            'pending_verifications': all_requests,
            'total_count': len(all_requests),
            'ib_count': len(ib_requests),
            'bank_count': len(bank_requests),
            'profile_count': len(profile_requests),
            'crypto_count': len(crypto_requests),
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
from rest_framework.pagination import PageNumberPagination
from django.utils.timezone import now
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from adminPanel.permissions import *
from rest_framework.response import Response
from rest_framework.views import APIView
from adminPanel.models import *
from adminPanel.serializers import *
from clientPanel.serializers import CryptoDetailsSerializer
from adminPanel.permissions import *
from .views import get_client_ip
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.conf import settings

class ActivityLogListView(APIView):
    """
    API View to fetch activity logs with filtering based on user role.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            if request.user.manager_admin_status == 'Admin':
                activity_logs = ActivityLog.objects.all()
            else:
                # For managers, only show activity logs of their assigned clients (created_by)
                activity_logs = ActivityLog.objects.filter(
                    Q(user__created_by=request.user) |  # Activities by their clients
                    Q(user=request.user)  # Activities by the manager themselves
                )

            search_query = request.GET.get('search', '')
            if search_query:
                activity_logs = activity_logs.filter(
                    Q(activity__icontains=search_query) |
                    Q(user__email__icontains=search_query) |
                    Q(activity_type__icontains=search_query)
                )

            paginator = PageNumberPagination()
            paginator.page_size = request.GET.get('pageSize', 10)
            paginated_logs = paginator.paginate_queryset(activity_logs.order_by('-timestamp'), request)

            serializer = ActivityLogSerializer(paginated_logs, many=True)
            return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AdminManagerDetailView(APIView):
    permission_classes = [IsAuthenticated]  
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
class IBRequestsView(APIView):
    """
    API View to handle fetching all pending IB requests.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def get(self, request):
        """
        Get all pending IB requests.
        """
        if request.user.manager_admin_status in ['Admin', 'Manager']:
            ib_requests = IBRequest.objects.filter(status="pending")
        else:
            ib_requests = IBRequest.objects.none()

        serializer = IBRequestSerializer(ib_requests, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class UpdateIBRequestView(APIView):
    """
    API View to handle updating the status of an IB request.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def patch(self, request, id):
        # IMMEDIATE DEBUG: return incoming data
        debug_info = {
            "received_data": dict(request.data),
            "method": request.method,
            "path": request.path,
            "id_param": id
        }
        return Response({"debug": debug_info}, status=200)
        
        try:
            ib_request = IBRequest.objects.get(id=id)
        except IBRequest.DoesNotExist:
            return Response(
                {"error": "IB Request not found."}, status=status.HTTP_404_NOT_FOUND
            )

        valid_statuses = ["approved", "rejected"]
        if "status" not in request.data or request.data["status"] not in valid_statuses:
            return Response(
                {"error": f"Invalid or missing status. Must be one of {valid_statuses}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Debug: return incoming data for debugging
        if request.data["status"] == "approved":
            new_profile = request.data.get("new_profile")
            debug_info = {
                "received_data": dict(request.data),
                "new_profile_exists": bool(new_profile),
                "new_profile_type": type(new_profile).__name__ if new_profile else None,
                "new_profile_content": new_profile if new_profile else None,
                "profile_name_exists": bool(request.data.get("profile_name")),
                "profile_name_value": request.data.get("profile_name")
            }
            return Response({"debug": debug_info}, status=200)
            
            # Only require profile_name if new_profile is not present or empty
            if not request.data.get("profile_name") and (not new_profile or not isinstance(new_profile, dict) or not new_profile.get("name")):
                return Response(
                    {"error": "Commissioning profile name or new_profile is required for approval."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        
        if request.data["status"] == "rejected":
            previous_status = ib_request.status
            ib_request.status = request.data["status"]
            ib_request.save()

            ActivityLog.objects.create(
                user=request.user,
                activity=(
                    f"Updated IB request #{ib_request.id} status from '{previous_status}' to '{ib_request.status}'."
                ),
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update", 
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=ib_request.id,
                related_object_type="IBRequest"
            )

            serializer = IBRequestSerializer(ib_request)
            return Response(serializer.data, status=status.HTTP_200_OK)

        try:
            previous_status = ib_request.status
            ib_request.status = request.data["status"]

            commissioning_profile = None
            if request.data["status"] == "approved":
                if "profile_name" in request.data:
                    profile_name = request.data.get('profile_name')
                    try:
                        commissioning_profile = CommissioningProfile.objects.get(name=profile_name)
                    except CommissioningProfile.DoesNotExist:
                        return Response(
                            {"error": f"Commissioning profile '{profile_name}' not found."},
                            status=status.HTTP_404_NOT_FOUND,
                        )
                elif "new_profile" in request.data:
                    from adminPanel.serializers import CommissioningProfileSerializer
                    serializer = CommissioningProfileSerializer(data=request.data["new_profile"])
                    if serializer.is_valid():
                        commissioning_profile = serializer.save()
                    else:
                        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                else:
                    return Response(
                        {"error": "Commissioning profile name or new_profile is required for approval."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                ib_request.user.commissioning_profile = commissioning_profile
                ib_request.user.IB_status = True
                ib_request.user.role = 'manager'
                # Set manager_admin_status to Manager Level 1 if not already a manager
                if not ib_request.user.manager_admin_status or ib_request.user.manager_admin_status == 'None':
                    ib_request.user.manager_admin_status = 'Manager Level 1'
            else:
                ib_request.user.IB_status = False

            ib_request.save()
            ib_request.user.save()
            # Update IB client assignments and stats
            try:
                from adminPanel.utils.client_manager_assignment import assign_ib_clients_to_manager
                assign_ib_clients_to_manager(ib_request.user, force_reassign=True)
            except Exception as e:
              logging.error(f"Error assigning IB clients to manager: {str(e)}")

            # Send email notification if request is approved
            if request.data["status"] == "approved":
                try:
                    from ..views.views import send_ib_approval_email
                    send_ib_approval_email(ib_request.user)
                except Exception as e:
                    logging.error(f"Error sending IB approval email: {str(e)}")

            activity_message = f"Updated IB request #{ib_request.id} status from '{previous_status}' to '{ib_request.status}'."
            if commissioning_profile:
                activity_message += f" Commissioning profile set to '{commissioning_profile.name}'."

            ActivityLog.objects.create(
                user=request.user,
                activity=activity_message,
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=ib_request.id,
                related_object_type="IBRequest"
            )

            serializer = IBRequestSerializer(ib_request)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
       

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

class GetMyDetailsView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, *args, **kwargs):
        """
        Returns the details of the currently authenticated user.
        """
        user = request.user
        serializer = UserSerializer(user)
        return Response(serializer.data, status=200)
    
class IBRequestsView(APIView):
    """
    API View to handle fetching all pending IB requests.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Get all pending IB requests.
        """
        # Only allow admin (case-insensitive) or is_staff
        user_status = getattr(request.user, 'manager_admin_status', '')
        is_admin = (
            request.user.is_staff or
            (user_status and 'admin' in user_status.lower())
        )
        if not is_admin:
            return Response(
                {'error': 'Admin access required'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # DEBUG: Add logging to see if this view is being called
        import logging
        logger = logging.getLogger(__name__)
       
        ib_requests = IBRequest.objects.filter(status="pending")

        serializer = IBRequestSerializer(ib_requests, many=True)
        
        return Response(serializer.data, status=status.HTTP_200_OK)

class UpdateIBRequestView(APIView):
    """
    API View to handle updating the status of an IB request.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        # Only allow admin (case-insensitive) or is_staff
        user_status = getattr(request.user, 'manager_admin_status', '')
        is_admin = (
            request.user.is_staff or
            (user_status and 'admin' in user_status.lower())
        )
        if not is_admin:
            return Response(
                {'error': 'Admin access required'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            ib_request = IBRequest.objects.get(id=id)
        except IBRequest.DoesNotExist:
            return Response(
                {"error": "IB Request not found."}, status=status.HTTP_404_NOT_FOUND
            )

        valid_statuses = ["approved", "rejected"]
        if "status" not in request.data or request.data["status"] not in valid_statuses:
            return Response(
                {"error": f"Invalid or missing status. Must be one of {valid_statuses}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
            
        # Fixed validation: check for either profile_name OR new_profile
        if request.data["status"] == "approved":
            new_profile = request.data.get("new_profile")
            if not request.data.get("profile_name") and (not new_profile or not isinstance(new_profile, dict) or not new_profile.get("name")):
                return Response(
                    {"error": "Commissioning profile name or new_profile is required for approval."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        
        if request.data["status"] == "rejected":
            previous_status = ib_request.status
            ib_request.status = request.data["status"]
            ib_request.save()

            ActivityLog.objects.create(
                user=request.user,
                activity=(
                    f"Updated IB request #{ib_request.id} status from '{previous_status}' to '{ib_request.status}'."
                ),
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update", 
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=ib_request.id,
                related_object_type="IBRequest"
            )

            serializer = IBRequestSerializer(ib_request)
            return Response(serializer.data, status=status.HTTP_200_OK)

        try:
            previous_status = ib_request.status
            ib_request.status = request.data["status"]
            
            if request.data["status"] == "approved":
                commissioning_profile = None
                profile_name = request.data.get('profile_name')
                new_profile = request.data.get('new_profile')
                
                if profile_name:
                    # Use existing profile
                    try:
                        commissioning_profile = CommissioningProfile.objects.get(name=profile_name)
                    except CommissioningProfile.DoesNotExist:
                        return Response(
                            {"error": f"Commissioning profile '{profile_name}' not found."},
                            status=status.HTTP_404_NOT_FOUND,
                        )
                elif new_profile and isinstance(new_profile, dict) and new_profile.get('name'):
                    # Create new profile
                    from adminPanel.serializers import CommissioningProfileSerializer
                    serializer = CommissioningProfileSerializer(data=new_profile)
                    if serializer.is_valid():
                        commissioning_profile = serializer.save()
                    else:
                        return Response(
                            {"error": "Invalid new profile data", "details": serializer.errors},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                else:
                    return Response(
                        {"error": "Commissioning profile name or new_profile is required for approval."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                
                ib_request.user.commissioning_profile = commissioning_profile
                ib_request.user.IB_status = True
            else:
                commissioning_profile = None
                ib_request.user.IB_status = False

            ib_request.save()
            ib_request.user.save()
            
            # Send email notification if request is approved
            if request.data["status"] == "approved":
                try:
                    from ..views.views import send_ib_approval_email
                    send_ib_approval_email(ib_request.user)
                except Exception as e:
                    # Log the error but continue with the process
                    logging.error(f"Error sending IB approval email: {str(e)}")
                
                # Create notification for user
                try:
                    from adminPanel.utils.notification_utils import create_ib_request_notification
                    create_ib_request_notification(user=ib_request.user, status='approved')
                except Exception as e:
                    logging.error(f"Error creating IB approval notification: {str(e)}")
            
            elif request.data["status"] == "rejected":
                # Create notification for rejected IB request
                try:
                    from adminPanel.utils.notification_utils import create_ib_request_notification
                    create_ib_request_notification(user=ib_request.user, status='rejected')
                except Exception as e:
                    logging.error(f"Error creating IB rejection notification: {str(e)}")

            activity_message = f"Updated IB request #{ib_request.id} status from '{previous_status}' to '{ib_request.status}'."
            if commissioning_profile:
                activity_message += f" Commissioning profile set to '{commissioning_profile.name}'."
                
            ActivityLog.objects.create(
                user=request.user,
                activity=activity_message,
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=ib_request.id,
                related_object_type="IBRequest"
            )

            serializer = IBRequestSerializer(ib_request)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:            
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class BankDetailsRequestsView(APIView):
    """
    API View to handle fetching all pending bank details requests.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        import logging
        logger = logging.getLogger(__name__)

        """
        Get all pending bank details requests with pagination.
        """
        if request.user.manager_admin_status in ['admin','manager','Admin', 'Manager'] or request.user.is_staff:
            # Use uppercase 'PENDING' to match the database
            requests = BankDetailsRequest.objects.filter(status__iexact="PENDING")
        else:
            requests = BankDetailsRequest.objects.none()

        sort_by = request.query_params.get('sortBy', 'created_at')
        sort_order = request.query_params.get('sortOrder', 'desc')
        if sort_order == 'asc':
            requests = requests.order_by(sort_by)
        else:
            requests = requests.order_by(f'-{sort_by}')

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get('pageSize', 10))
        paginated_requests = paginator.paginate_queryset(requests, request)

        serializer = BankDetailsRequestSerializer(paginated_requests, many=True)
        return paginator.get_paginated_response(serializer.data)


class ApproveBankDetailsRequestView(APIView):
    """
    API View to approve a bank details request.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f'[DEBUG] [ApproveBankDetailsRequestView.patch] User: {request.user}, id: {id}, Data: {request.data}')
        try:
            bank_request = BankDetailsRequest.objects.get(id=id)
            bank_request.status = 'approved'
            bank_request.save()

            # Also update the related user's BankDetails.status to 'approved'
            from clientPanel.models import BankDetails
            bank_details = BankDetails.objects.filter(user=bank_request.user).first()
            if bank_details:
                bank_details.status = 'approved'
                bank_details.save()

            # Create notification for user
            from adminPanel.utils.notification_utils import create_bank_details_notification
            create_bank_details_notification(user=bank_request.user, status='approved')

            return Response({'detail': 'Bank details request approved.'}, status=status.HTTP_200_OK)
        except BankDetailsRequest.DoesNotExist:
            return Response({'detail': 'Bank details request not found.'}, status=status.HTTP_404_NOT_FOUND)

class RejectBankDetailsRequestView(APIView):
    """
    API View to reject a bank details request.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f'[DEBUG] [RejectBankDetailsRequestView.patch] User: {request.user}, id: {id}, Data: {request.data}')
        try:
            bank_request = BankDetailsRequest.objects.get(id=id)
            reason = request.data.get('reason', '')
            bank_request.status = 'rejected'
            bank_request.rejection_reason = reason
            bank_request.save()
            return Response({'detail': 'Bank details request rejected.'}, status=status.HTTP_200_OK)
        except BankDetailsRequest.DoesNotExist:
            return Response({'detail': 'Bank details request not found.'}, status=status.HTTP_404_NOT_FOUND)

            ActivityLog.objects.create(
                user=request.user,
                activity=(
                    f"Rejected bank details request #{request_obj.id} for user "
                    f"{request_obj.user.email}."
                ),
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=request_obj.id,
                related_object_type="BankDetailsRequest"
            )

            return Response(
                {"message": "Bank details request rejected successfully."},
                status=status.HTTP_200_OK,
            )
        except BankDetailsRequest.DoesNotExist:
            return Response(
                {"error": "Bank details request not found or already processed."},
                status=status.HTTP_404_NOT_FOUND,
            )

class ProfileChangeRequestsView(APIView):
    """
    API View to fetch all pending profile change requests.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import logging
        logger = logging.getLogger(__name__)
        
        """
        Get all pending profile change requests and pending document verifications.
        """
        # Check if user is admin or manager (more flexible check)
        user_status = getattr(request.user, 'manager_admin_status', '').lower()
        is_admin_or_manager = (
            request.user.is_staff or 
            request.user.is_superuser or
            'admin' in user_status or 
            'manager' in user_status
        )
        
        if is_admin_or_manager:
            # Get actual ChangeRequest objects (exclude document-only requests)
            change_requests = ChangeRequest.objects.filter(status="PENDING")
            
            # Filter out requests that only have document verification (no profile data changes)
            filtered_requests = []
            for req in change_requests:
                requested_data = req.requested_data or {}
                # Check if the request has actual profile data changes (not just document verification flag)
                has_profile_changes = any(
                    key not in ['document_verification', 'document_type'] 
                    for key in requested_data.keys()
                )
                if has_profile_changes or not requested_data.get('document_verification'):
                    filtered_requests.append(req)
            
            # Serialize filtered change requests
            serializer = ChangeRequestSerializer(filtered_requests, many=True)
            results = list(serializer.data)
            
            logger.debug(f'[DEBUG] Found {len(results)} profile change requests (excluding document-only requests)')
        else:
            results = []
            logger.debug('[DEBUG] User does not have admin/manager permissions, returning empty list')

        return Response(results, status=status.HTTP_200_OK)
    
    def post(self, request):
        """
        Create a new profile change request (for personal info changes).
        """
        from adminPanel.models import ChangeRequest
        from adminPanel.serializers import ChangeRequestSerializer
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f'[DEBUG] [ProfileChangeRequestsView.post] User: {request.user}, Data: {request.data}')

        # Only allow for authenticated users (optionally: restrict to self or admin)
        user = request.user
        requested_changes = request.data.get('requested_changes')
        if not requested_changes or not isinstance(requested_changes, dict):
            return Response({'error': 'requested_changes must be provided as a dict.'}, status=400)

        # Prevent duplicate pending requests for the same user
        from django.db import IntegrityError
        try:
            change_request = ChangeRequest.objects.create(
                user=user,
                requested_data=requested_changes,
                status='PENDING'
            )
        except IntegrityError:
            return Response({'error': 'You already have a pending profile change request. Please wait for it to be reviewed before submitting another.'}, status=400)
        serializer = ChangeRequestSerializer(change_request)
        logger.debug(f'[DEBUG] Created ChangeRequest id={change_request.id} for user={user}')
        return Response(serializer.data, status=201)

class ApproveProfileChangeRequestView(APIView):
    """
    API View to approve a profile change request.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f'[DEBUG] [ApproveProfileChangeRequestView.patch] User: {request.user}, id: {id}, Data: {request.data}')
        
        # Handle regular ChangeRequest approval
        try:
            change_request = ChangeRequest.objects.get(id=id, status="PENDING")
            change_request.approve()

            ActivityLog.objects.create(
                user=request.user,
                activity=(
                    f"Approved profile change request #{change_request.id} for user "
                    f"{change_request.user.email}."
                ),
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=change_request.id,
                related_object_type="ChangeRequest"
            )

            # Create notification for the user
            from adminPanel.utils.notification_utils import create_profile_change_notification
            # Get the first changed field or use 'profile' as default
            change_type = list(change_request.requested_data.keys())[0] if change_request.requested_data else 'profile'
            create_profile_change_notification(
                user=change_request.user,
                change_type=change_type,
                status='approved'
            )

            return Response({"message": "Request approved successfully."}, status=status.HTTP_200_OK)
        except ChangeRequest.DoesNotExist:
            return Response({"error": "Request not found or already processed."}, status=status.HTTP_404_NOT_FOUND)

class RejectProfileChangeRequestView(APIView):
    """
    API View to reject a profile change request.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f'[DEBUG] [RejectProfileChangeRequestView.patch] User: {request.user}, id: {id}, Data: {request.data}')
        
        # Handle regular ChangeRequest rejection
        try:
            change_request = ChangeRequest.objects.get(id=id, status="PENDING")
            change_request.reject()

            ActivityLog.objects.create(
                user=request.user,
                activity=(
                    f"Rejected profile change request #{change_request.id} for user "
                    f"{change_request.user.email}."
                ),
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=change_request.id,
                related_object_type="ChangeRequest"
            )

            # Create notification for the user
            from adminPanel.utils.notification_utils import create_profile_change_notification
            # Get the first changed field or use 'profile' as default
            change_type = list(change_request.requested_data.keys())[0] if change_request.requested_data else 'profile'
            create_profile_change_notification(
                user=change_request.user,
                change_type=change_type,
                status='rejected'
            )

            return Response({"message": "Request rejected successfully."}, status=status.HTTP_200_OK)
        except ChangeRequest.DoesNotExist:
            return Response({"error": "Request not found or already processed."}, status=status.HTTP_404_NOT_FOUND)

class DocumentRequestsView(APIView):
    """
    API View to fetch all pending document verification requests.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import logging
        logger = logging.getLogger(__name__)
        
        """
        Get all pending document verification requests.
        """
        # Check if user is admin or manager
        user_status = getattr(request.user, 'manager_admin_status', '').lower()
        is_admin_or_manager = (
            request.user.is_staff or 
            request.user.is_superuser or
            'admin' in user_status or 
            'manager' in user_status
        )
        
        if is_admin_or_manager:
            from clientPanel.models import UserDocument
            from adminPanel.serializers import UserDocumentSerializer
            
            # Get pending UserDocument objects
            pending_documents = UserDocument.objects.filter(status='pending').select_related('user')
            
            # Serialize the documents
            serializer = UserDocumentSerializer(pending_documents, many=True)
            results = serializer.data
            
            logger.debug(f'[DEBUG] Found {len(results)} pending document requests')
        else:
            results = []
            logger.debug('[DEBUG] User does not have admin/manager permissions, returning empty list')

        return Response(results, status=status.HTTP_200_OK)

class ApproveDocumentRequestView(APIView):
    """
    API View to approve a document verification request.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f'[DEBUG] [ApproveDocumentRequestView.patch] User: {request.user}, id: {id}')
        
        try:
            from clientPanel.models import UserDocument
            user_document = UserDocument.objects.get(id=id, status='pending')

            # Approve the document
            user_document.status = 'approved'
            user_document.verified_at = now()
            user_document.save()

            # Create notification for user
            try:
                from adminPanel.utils.notification_utils import create_document_upload_notification
                create_document_upload_notification(
                    user=user_document.user, 
                    document_type=user_document.document_type,
                    status='approved'
                )
            except Exception as e:
                logger.error(f"Error creating document approval notification: {str(e)}")

            # Update legacy CustomUser fields for backward compatibility
            if user_document.document_type == 'identity':
                user_document.user.id_proof_verified = True
            elif user_document.document_type == 'residence':
                user_document.user.address_proof_verified = True
            user_document.user.save()

            # Only send KYC verified email if both documents are approved
            from adminPanel.EmailSender import EmailSender
            user = user_document.user
            user_name = user.get_full_name() if hasattr(user, 'get_full_name') else user.username
            login_url = 'https://client.vtindex.com'
            support_url = 'support@vtindex.com'
            current_year = now().year
            
            # Check both document statuses
            from clientPanel.models import UserDocument as UD
            identity_doc = UD.objects.filter(user=user, document_type='identity').first()
            residence_doc = UD.objects.filter(user=user, document_type='residence').first()
            
            if identity_doc and residence_doc:
                if identity_doc.status == 'approved' and residence_doc.status == 'approved':
                    logger.info(f"Triggering KYC verified email for user {user.email} (both docs approved)")
                    try:
                        result = EmailSender.send_kyc_verified_email(
                            user.email,
                            user_name,
                            login_url,
                            support_url,
                            current_year
                        )
                        logger.info(f"KYC verified email send result: {result}")
                    except Exception as email_error:
                        logger.error(f"Failed to send KYC verified email: {email_error}")

            ActivityLog.objects.create(
                user=request.user,
                activity=(
                    f"Approved {user_document.document_type} document for user "
                    f"{user_document.user.email}."
                ),
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=user_document.id,
                related_object_type="UserDocument"
            )

            return Response({"message": "Document approved successfully."}, status=status.HTTP_200_OK)

        except UserDocument.DoesNotExist:
            return Response({"error": "Document not found or already processed."}, status=status.HTTP_404_NOT_FOUND)

class RejectDocumentRequestView(APIView):
    """
    API View to reject a document verification request.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f'[DEBUG] [RejectDocumentRequestView.patch] User: {request.user}, id: {id}')
        
        try:
            from clientPanel.models import UserDocument
            user_document = UserDocument.objects.get(id=id, status='pending')
            
            # Reject the document
            user_document.status = 'rejected'
            user_document.verified_at = None
            user_document.save()

            # Send rejection email
            from adminPanel.EmailSender import EmailSender
            user = user_document.user
            user_name = user.get_full_name() if hasattr(user, 'get_full_name') else user.username
            login_url = 'https://client.vtindex.com'
            support_url = 'support@vtindex.com'
            current_year = now().year
            upload_url = login_url + '/profile/kyc-documents/'
            
            try:
                result = EmailSender.send_kyc_rejected_email(
                    user.email,
                    user_name,
                    upload_url,
                    support_url,
                    current_year
                )
                logger.info(f"KYC document rejected email send result: {result}")
            except Exception as email_error:
                logger.error(f"Failed to send KYC rejection email: {email_error}")

            ActivityLog.objects.create(
                user=request.user,
                activity=(
                    f"Rejected {user_document.document_type} document for user "
                    f"{user_document.user.email}."
                ),
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=user_document.id,
                related_object_type="UserDocument"
            )

            return Response({"message": "Document rejected successfully."}, status=status.HTTP_200_OK)
            
        except UserDocument.DoesNotExist:
            return Response({"error": "Document not found or already processed."}, status=status.HTTP_404_NOT_FOUND)

class PendingWithdrawalRequestsView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, *args, **kwargs):
        transactions = Transaction.objects.filter(
            status='pending', transaction_type='commission_withdrawal'
        )

        sort_by = request.query_params.get('sortBy', 'created_at')
        sort_order = request.query_params.get('sortOrder', 'desc')
        if sort_order == 'asc':
            transactions = transactions.order_by(sort_by)
        else:
            transactions = transactions.order_by(f'-{sort_by}')

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get('pageSize', 10))
        paginated_transactions = paginator.paginate_queryset(transactions, request)

        serializer = TransactionSerializer(paginated_transactions, many=True)
        return paginator.get_paginated_response(serializer.data)

class ApproveRejectTransactionView(APIView):
    """
    API View to approve or reject a transaction.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        try:
            transaction = Transaction.objects.get(pk=pk, status='pending', transaction_type='commission_withdrawal')
            if action == 'approve':
                transaction.status = 'approved'
                transaction.approved_by = request.user
                transaction.approved_at = now()
                transaction.save()

                # Create notification for user
                try:
                    from adminPanel.utils.notification_utils import create_bank_transaction_notification
                    create_bank_transaction_notification(
                        user=transaction.user,
                        transaction_type='withdrawal',
                        amount=transaction.amount,
                        status='approved'
                    )
                except Exception as e:
                    logging.error(f"Error creating transaction approval notification: {str(e)}")

                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Approved commission withdrawal transaction #{transaction.id}.",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="update",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=now(),
                    related_object_id=transaction.id,
                    related_object_type="Transaction"
                )

                return Response({'success': True, 'message': 'Transaction approved.'}, status=status.HTTP_200_OK)

            elif action == 'reject':
                transaction.status = 'rejected'
                transaction.approved_by = request.user
                transaction.approved_at = now()
                transaction.save()

                # Create notification for user
                try:
                    from adminPanel.utils.notification_utils import create_bank_transaction_notification
                    create_bank_transaction_notification(
                        user=transaction.user,
                        transaction_type='withdrawal',
                        amount=transaction.amount,
                        status='rejected'
                    )
                except Exception as e:
                    logging.error(f"Error creating transaction rejection notification: {str(e)}")

                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Rejected commission withdrawal transaction #{transaction.id}.",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="update",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=now(),
                    related_object_id=transaction.id,
                    related_object_type="Transaction"
                )

                return Response({'success': True, 'message': 'Transaction rejected.'}, status=status.HTTP_200_OK)

            else:
                return Response({'success': False, 'message': 'Invalid action.'}, status=status.HTTP_400_BAD_REQUEST)

        except Transaction.DoesNotExist:
            return Response({'success': False, 'message': 'Transaction not found or already processed.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'success': False, 'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
class DisablePropAccountView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, account_id):
        account = TradingAccount.objects.filter(account_id=account_id, account_type='prop').first()
        if account:
            account.is_enabled = False
            account.save()
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Disabled account ID {account_id}",
                ip_address=get_client_ip(request),
                activity_type='update',
                activity_category='management',
                endpoint=request.path,
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                related_object_id=account.account_id,
                related_object_type="Prop Account"
            )
            return Response({'status': 'success', 'message': 'Account disabled successfully'}, status=status.HTTP_200_OK)
        else:
            return Response({'status': 'failure', 'message': 'Account Not found'}, status=status.HTTP_200_OK)

@csrf_exempt
def disable_prop_account(request, account_id):
    if request.method == 'POST':
        account = TradingAccount.objects.filter(account_id=account_id, account_type='prop').first()
        if account:
            account.is_enabled = False
            account.status = "failed"
            account.save()
            ActivityLog.objects.create(
                user=account.user,
                activity=f"Disabled account ID {account_id}",
                ip_address=get_client_ip(request),
                activity_type='update',
                activity_category='management',
                endpoint=request.path,
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                related_object_id=account.account_id,
                related_object_type="Prop Account"
            )
            return JsonResponse({'status': 'success', 'message': 'Account disabled successfully'}, status=status.HTTP_200_OK)
        else:
            return JsonResponse({'status': 'failure', 'message': 'Account not found'}, status=status.HTTP_404_NOT_FOUND)
    else:
        return JsonResponse({'status': 'failure', 'message': 'Invalid request method'}, status=status.HTTP_400_BAD_REQUEST)

class CryptoDetailsRequestsView(APIView):
    """
    API View to fetch pending crypto details requests.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, *args, **kwargs):
        crypto_details = CryptoDetails.objects.filter(status='pending')

        sort_by = request.query_params.get('sortBy', 'created_at')
        sort_order = request.query_params.get('sortOrder', 'desc')
        if sort_order == 'asc':
            crypto_details = crypto_details.order_by(sort_by)
        else:
            crypto_details = crypto_details.order_by(f'-{sort_by}')

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get('pageSize', 10))
        paginated_crypto = paginator.paginate_queryset(crypto_details, request)

        serializer = CryptoDetailsSerializer(paginated_crypto, many=True)
        return paginator.get_paginated_response(serializer.data)

class ApproveCryptoDetailsView(APIView):
    """
    API View to approve crypto details request.
    """
    permission_classes = [IsAuthenticatedUser]

    def patch(self, request, id, *args, **kwargs):
        try:
            crypto_detail = CryptoDetails.objects.get(id=id, status='pending')
            crypto_detail.status = 'approved'
            crypto_detail.save()

            # Create notification for user
            try:
                from adminPanel.models_notification import Notification
                Notification.create_notification(
                    user=crypto_detail.user,
                    notification_type='CRYPTO',
                    status='approved',
                    title='Crypto Wallet Approved',
                    message='Your crypto wallet details have been approved and are now active.',
                    action_url='/crypto-wallets'
                )
            except Exception as e:
                import logging
                logging.error(f"Error creating crypto approval notification: {str(e)}")

            ActivityLog.objects.create(
                user=request.user,
                activity=f"Approved crypto details for user {crypto_detail.user.email}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=crypto_detail.id,
                related_object_type="CryptoDetails"
            )

            return Response({'success': True, 'message': 'Crypto details approved successfully'}, status=status.HTTP_200_OK)
        except CryptoDetails.DoesNotExist:
            return Response({'error': 'Crypto details request not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RejectCryptoDetailsView(APIView):
    """
    API View to reject crypto details request.
    """
    permission_classes = [IsAuthenticatedUser]

    def patch(self, request, id, *args, **kwargs):
        try:
            crypto_detail = CryptoDetails.objects.get(id=id, status='pending')
            reason = request.data.get('reason', '')
            crypto_detail.status = 'rejected'
            crypto_detail.rejection_reason = reason
            crypto_detail.save()

            # Create notification for user
            try:
                from adminPanel.models_notification import Notification
                Notification.create_notification(
                    user=crypto_detail.user,
                    notification_type='CRYPTO',
                    status='rejected',
                    title='Crypto Wallet Rejected',
                    message=f'Your crypto wallet details have been rejected. Reason: {reason}' if reason else 'Your crypto wallet details have been rejected.',
                    action_url='/crypto-wallets'
                )
            except Exception as e:
                import logging
                logging.error(f"Error creating crypto rejection notification: {str(e)}")

            ActivityLog.objects.create(
                user=request.user,
                activity=f"Rejected crypto details for user {crypto_detail.user.email}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=crypto_detail.id,
                related_object_type="CryptoDetails"
            )

            return Response({'success': True, 'message': 'Crypto details rejected'}, status=status.HTTP_200_OK)
        except CryptoDetails.DoesNotExist:
            return Response({'error': 'Crypto details request not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PendingDepositRequestsView(APIView):
    """
    API View to fetch pending deposit transactions (manual deposits).
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, *args, **kwargs):
        transactions = Transaction.objects.filter(
            status='pending', 
            transaction_type='deposit_trading'
        )

        sort_by = request.query_params.get('sortBy', 'created_at')
        sort_order = request.query_params.get('sortOrder', 'desc')
        if sort_order == 'asc':
            transactions = transactions.order_by(sort_by)
        else:
            transactions = transactions.order_by(f'-{sort_by}')

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get('pageSize', 10))
        paginated_transactions = paginator.paginate_queryset(transactions, request)

        serializer = TransactionSerializer(paginated_transactions, many=True)
        return paginator.get_paginated_response(serializer.data)

class PendingUSDTTransactionsView(APIView):
    """
    API View to fetch pending USDT transactions.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, *args, **kwargs):
        # Filter transactions that involve USDT/crypto
        transactions = Transaction.objects.filter(
            status='pending',
            source__icontains='crypto'
        ).union(
            Transaction.objects.filter(
                status='pending',
                source__icontains='usdt'
            )
        ).union(
            Transaction.objects.filter(
                status='pending',
                payout_to='crypto'
            )
        )

        sort_by = request.query_params.get('sortBy', 'created_at')
        sort_order = request.query_params.get('sortOrder', 'desc')
        if sort_order == 'asc':
            transactions = transactions.order_by(sort_by)
        else:
            transactions = transactions.order_by(f'-{sort_by}')

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get('pageSize', 10))
        paginated_transactions = paginator.paginate_queryset(transactions, request)

        serializer = TransactionSerializer(paginated_transactions, many=True)
        return paginator.get_paginated_response(serializer.data)

class ApproveTransactionView(APIView):
    """
    API View to approve a transaction.
    """
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, id, *args, **kwargs):
        from adminPanel.mt5.services import MT5ManagerActions
        from adminPanel.EmailSender import EmailSender
        try:
            transaction = Transaction.objects.get(id=id, status='pending')

            mt5_result = None
            mt5_error = None

            # Ensure we have a valid TradingAccount reference if provided
            try:
                trading_account = transaction.trading_account
                if not trading_account and hasattr(transaction, 'account_id') and transaction.account_id:
                    from adminPanel.models import TradingAccount
                    trading_account = TradingAccount.objects.get(account_id=transaction.account_id)
                    transaction.trading_account = trading_account
            except Exception as e:
                trading_account = None
                logger = logging.getLogger(__name__)
                logger.warning(f"Could not resolve trading account for transaction {transaction.id}: {e}")

            # Only perform MT5 balance update for deposit/withdraw or commission_withdrawal
            try:
                if transaction.transaction_type in ['deposit_trading', 'withdraw_trading'] and trading_account:
                    mt5 = MT5ManagerActions()
                    login_id = int(trading_account.account_id)
                    amount = float(transaction.amount)
                    comment = f"Admin approval TX#{transaction.id}"
                    if transaction.transaction_type == 'deposit_trading':
                        mt5_result = mt5.deposit_funds(login_id, amount, comment)
                        try:
                            user = transaction.user
                            EmailSender.send_deposit_confirmation(
                                user.email,
                                user.username,
                                trading_account.account_id,
                                transaction.amount,
                                transaction.id,
                                now().strftime('%Y-%m-%d %H:%M:%S')
                            )
                        except Exception:
                            pass
                    elif transaction.transaction_type == 'withdraw_trading':
                        mt5_result = mt5.withdraw_funds(login_id, amount, comment)
                        try:
                            user = transaction.user
                            EmailSender.send_withdrawal_confirmation(
                                user.email,
                                user.username,
                                trading_account.account_id,
                                transaction.amount,
                                transaction.id,
                                now().strftime('%Y-%m-%d %H:%M:%S')
                            )
                        except Exception:
                            pass

                elif transaction.transaction_type == 'commission_withdrawal':
                    # For commission withdrawals, verify IB's available commission then deposit into provided trading account
                    try:
                        available = transaction.user.total_earnings - transaction.user.total_commission_withdrawals
                    except Exception:
                        available = None

                    if available is None or transaction.amount <= available:
                        if not trading_account or not getattr(trading_account, 'account_id', None):
                            raise Exception('No trading account specified for commission withdrawal')
                        mt5 = MT5ManagerActions()
                        login_id = int(trading_account.account_id)
                        amount = float(transaction.amount)
                        comment = f"Commission withdrawal TX#{transaction.id}"
                        mt5_result = mt5.deposit_funds(login_id, amount, comment)
                        # no email for commission deposits by default
                    else:
                        return Response({'error': 'Insufficient commission balance.'}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                mt5_error = str(e)
                return Response({'error': f'MT5 operation failed: {mt5_error}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # All external operations succeeded (or were not required) — record approval
            transaction.status = 'approved'
            transaction.approved_by = request.user
            transaction.approved_at = now()

            # Get comment from the request data
            comment = request.data.get('comment', '')
            if comment:
                transaction.admin_comment = comment

            transaction.save()

            ActivityLog.objects.create(
                user=request.user,
                activity=f"Approved transaction #{transaction.id} ({transaction.transaction_type})",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=transaction.id,
                related_object_type="Transaction"
            )

            response_data = {'success': True, 'message': 'Transaction approved successfully'}
            return Response(response_data, status=status.HTTP_200_OK)
        except Transaction.DoesNotExist:
            return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RejectTransactionView(APIView):
    """
    API View to reject a transaction.
    """
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, id, *args, **kwargs):
        try:
            transaction = Transaction.objects.get(id=id, status='pending')
            transaction.status = 'rejected'
            transaction.approved_by = request.user
            transaction.approved_at = now()
            
            # Get comment from the request data
            comment = request.data.get('comment', '')
            if comment:
                transaction.admin_comment = comment
            
            transaction.save()

            ActivityLog.objects.create(
                user=request.user,
                activity=f"Rejected transaction #{transaction.id} ({transaction.transaction_type})",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=transaction.id,
                related_object_type="Transaction"
            )

            return Response({'success': True, 'message': 'Transaction rejected'}, status=status.HTTP_200_OK)
        except Transaction.DoesNotExist:
            return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from adminPanel.models import Transaction
from adminPanel.serializers import TransactionSerializer
from django.db.models import Q

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unified_pending_deposits_view(request):
    """
    Unified view for all pending deposit transactions (manual, requests, USDT/crypto)
    """
    # Manual deposits
    manual_deposits = Transaction.objects.filter(
        status='pending', transaction_type='deposit'
    )
    # Deposit requests
    deposit_requests = Transaction.objects.filter(
        status='pending', transaction_type='deposit_trading'
    )
    # USDT deposits only (exclude crypto)
    usdt_deposits = Transaction.objects.filter(
        status='pending'
    ).filter(Q(source__icontains='usdt'))

    # Combine all, remove duplicates
    all_ids = set()
    all_deposits = []
    for tx in list(manual_deposits) + list(deposit_requests) + list(usdt_deposits):
        if tx.id not in all_ids:
            all_ids.add(tx.id)
            all_deposits.append(tx)

    # Sort by created_at descending
    all_deposits.sort(key=lambda x: x.created_at, reverse=True)

    serializer = TransactionSerializer(all_deposits, many=True)
    return Response(serializer.data)
# ==================== Unapproved Users Management ====================

@csrf_exempt
@api_view(['GET'])
@authentication_classes([JWTAuthentication, TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def unapproved_users_list(request):
    """
    Get list of unapproved users (is_approved_by_admin = False)
    Only admin can access this endpoint
    """
    try:
        if not request.user.is_staff and 'Admin' not in getattr(request.user, 'manager_admin_status', ''):
            return Response(
                {'error': 'Only admins can access this endpoint'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get pagination parameters
        page = request.GET.get('page', 1)
        page_size = request.GET.get('pageSize', 10)
        
        try:
            page = int(page)
            page_size = int(page_size)
        except (ValueError, TypeError):
            page = 1
            page_size = 10
        
        # Get unapproved users
        unapproved_users = CustomUser.objects.filter(
            is_approved_by_admin=False,
            role='client'  # Only show client users
        ).order_by('-date_joined')
        
        total = unapproved_users.count()
        
        # Pagination
        start = (page - 1) * page_size
        end = start + page_size
        paginated_users = unapproved_users[start:end]
        
        # Serialize data
        serializer = UserSerializer(paginated_users, many=True)
        
        return Response({
            'results': serializer.data,
            'total': total,
            'page': page,
            'pageSize': page_size,
            'totalPages': (total + page_size - 1) // page_size
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response(
            {'error': f'Error fetching unapproved users: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class ApproveUserView(APIView):
    """
    Approve or reject a user (set is_approved_by_admin)
    """
    authentication_classes = [JWTAuthentication, TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    
    @method_decorator(csrf_exempt)
    def patch(self, request, id):
        """
        PATCH /api/admin/users/<id>/approve/
        Body: { "is_approved_by_admin": true/false }
        """
        try:
            # Check if user is admin
            if not request.user.is_staff and 'Admin' not in getattr(request.user, 'manager_admin_status', ''):
                return Response(
                    {'error': 'Only admins can approve users'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Get the user
            user = CustomUser.objects.get(id=id)
            
            # Get the approval status from request body
            is_approved = request.data.get('is_approved_by_admin')
            
            if is_approved is None:
                return Response(
                    {'error': 'is_approved_by_admin field is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Update the user's approval status
            user.is_approved_by_admin = bool(is_approved)
            user.save()
            
            action = "approved" if is_approved else "rejected"
            return Response(
                {
                    'message': f'User {action} successfully',
                    'user_id': user.id,
                    'email': user.email,
                    'is_approved_by_admin': user.is_approved_by_admin
                },
                status=status.HTTP_200_OK
            )
            
        except CustomUser.DoesNotExist:
            return Response(
                {'error': f'User with id {id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': f'Error updating user approval: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )