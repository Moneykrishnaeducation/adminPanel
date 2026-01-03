from django.utils.timezone import now
from django.shortcuts import get_object_or_404
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.http import JsonResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from adminPanel.permissions import IsAdmin, IsManager, OrPermission, IsAuthenticatedUser
from rest_framework.response import Response
from rest_framework.views import APIView
from .views import get_client_ip
from adminPanel.models import *
from adminPanel.serializers import *
from django.db.models import Q
from rest_framework.pagination import PageNumberPagination

@api_view(['POST'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def add_client(request):
    """
    API View to add a client under an IB user.
    """
    try:
        
        ib_user_id = request.data.get('ibUserId')
        client_user_id = request.data.get('clientUserId')

        if not ib_user_id or not client_user_id:
            return Response({"error": "Both IB user ID and client user ID are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ib_user = CustomUser.objects.get(user_id=ib_user_id, IB_status=True)
        except CustomUser.DoesNotExist:
            return Response({"error": "IB user not found or not an IB."}, status=status.HTTP_404_NOT_FOUND)

        try:
            client_user = CustomUser.objects.get(user_id=client_user_id, parent_ib__isnull=True)
        except CustomUser.DoesNotExist:
            return Response({"error": "Client user not found or already assigned to an IB."}, status=status.HTTP_404_NOT_FOUND)
        if ib_user.parent_ib == client_user:
            return Response({"error": "Wrong"}, status=status.HTTP_400_BAD_REQUEST)

        if ib_user == client_user:
            return Response({"error": "Wrong"}, status=status.HTTP_400_BAD_REQUEST)
            
        client_user.parent_ib = ib_user
        client_user.save()
        ActivityLog.objects.create(
            user=request.user,
            activity=f"Assigned client user {client_user.username} (ID: {client_user_id}) to IB user {ib_user.username} (ID: {ib_user_id}).",
            ip_address=get_client_ip(request),
            endpoint=request.path,
            activity_type="create",
            activity_category="management",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=client_user_id,
            related_object_type="CustomUser"
        )
        return Response({"success": "Client successfully added to the IB."}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CommissionWithdrawalHistoryUserView(APIView):
    """
    API View to fetch commission withdrawal history for a specific user.
    """
    permission_classes = [IsAuthenticatedUser]
    

    def get(self, request, user_id):
        import logging
        logger = logging.getLogger(__name__)
        try:
            # Debug: log the request user and their manager_admin_status
            logger.warning(f"[CommissionWithdrawalHistoryUserView] request.user={request.user.username}, manager_admin_status={getattr(request.user, 'manager_admin_status', None)}")
            user = CustomUser.objects.get(user_id=user_id)
            if getattr(request.user, 'manager_admin_status', None) in ['Admin', 'Manager', 'admin', 'manager']:
                logger.debug(f"[CommissionWithdrawalHistoryUserView] user_id={user_id}, user={user}")
                withdrawals = Transaction.objects.filter(
                    user=user,
                    transaction_type='commission_withdrawal'
                )
            else:
                withdrawals = Transaction.objects.none()

            search_query = request.GET.get('search', '')
            sort_by = request.GET.get('sortBy', 'created_at')
            sort_order = request.GET.get('sortOrder', 'desc')
            logger.debug(f"[CommissionWithdrawalHistoryUserView] search_query='{search_query}', sort_by='{sort_by}', sort_order='{sort_order}'")
            if search_query:
                withdrawals = withdrawals.filter(
                    Q(description__icontains=search_query) |
                    Q(status__icontains=search_query) |
                    Q(amount__icontains=search_query)
                )

            if sort_order == 'desc':
                withdrawals = withdrawals.order_by(f'-{sort_by}')
            else:
                withdrawals = withdrawals.order_by(sort_by)

            paginator = PageNumberPagination()
            paginator.page_size = int(request.GET.get('pageSize', 10))
            result_page = paginator.paginate_queryset(withdrawals, request)
            serializer = TransactionSerializer(result_page, many=True)
            return paginator.get_paginated_response(serializer.data)

        except CustomUser.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"[CommissionWithdrawalHistoryUserView] Exception: {e}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_commission_summary(request, ib_user_id):
    """
    API view to fetch commission summary for an IB user.
    """
    try:
        
        ib_user = get_object_or_404(CustomUser, user_id=ib_user_id, IB_status=True)

        level1_clients = ib_user.get_clients_by_level(1)
        level2_clients = ib_user.get_clients_by_level(2)
        level3_clients = ib_user.get_clients_by_level(3)
        
        # Exclude demo account commissions
        level1_commissions = CommissionTransaction.objects.filter(
            ib_user=ib_user, ib_level=1
        ).exclude(
            client_trading_account__account_type='demo'
        ).aggregate(total=models.Sum('commission_to_ib'))['total'] or 0
        level2_commissions = CommissionTransaction.objects.filter(
            ib_user=ib_user, ib_level=2
        ).exclude(
            client_trading_account__account_type='demo'
        ).aggregate(total=models.Sum('commission_to_ib'))['total'] or 0
        level3_commissions = CommissionTransaction.objects.filter(
            ib_user=ib_user, ib_level=3
        ).exclude(
            client_trading_account__account_type='demo'
        ).aggregate(total=models.Sum('commission_to_ib'))['total'] or 0
        total_commission = level1_commissions + level2_commissions + level3_commissions
        withdrawn_commission = ib_user.total_commission_withdrawals
        withdrawable_commission = total_commission - withdrawn_commission

        
        summary = {
            "level1Clients": len(level1_clients),  
            "level2Clients": len(level2_clients),  
            "level3Clients": len(level3_clients),  
            "level1Commission": round(level1_commissions, 2),
            "level2Commission": round(level2_commissions, 2),
            "level3Commission": round(level3_commissions, 2),
            "totalCommission": round(total_commission, 2),
            "withdrawnCommission": round(withdrawn_commission, 2),
            "withdrawableCommission": round(withdrawable_commission, 2),
        }

        return Response(summary, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)

class CommissionTransactionView(APIView):
    """
    API View to fetch commission transactions for an IB user.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, user_id):
        """
        Get commission transactions for a specific IB user.
        Filters: level (ib_level) and trading_symbol.
        """
        try:
            
            level = int(request.query_params.get('level'))
            ib_user = CustomUser.objects.filter(user_id = user_id).first()
            
            transactions = CommissionTransaction.objects.filter(ib_user=ib_user)

            if level:
                transactions = transactions.filter(ib_level=level)
            
            serializer = CommissionTransactionSerializer(transactions, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        except Exception as e:
            print(e)
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DisableIBStatusView(APIView):
    """
    API View to disable IB status for a specific user.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]  

    def post(self, request):
        try:
            try:
                client = CustomUser.objects.get(user_id=request.data["clientId"])
            except CustomUser.DoesNotExist:
                return Response({"error": "Client not found."}, status=404)
            if not client.IB_status:
                return Response({"error": "Client is not an IB partner."}, status=400)

            client.IB_status = False
            client.save()
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Disabled IB status for user {client.user_id} ({client.email})",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=client.user_id,
                related_object_type="User"
            )

            return Response({"success": "IB status disabled successfully."}, status=200)

        except Exception as e:
            return Response({"error": str(e)}, status=500)

class IBClientsListView(APIView):
    """
    API View to fetch clients grouped by levels for a specific IB user.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, user_id):
        try:
            ib_user = CustomUser.objects.get(user_id=user_id, IB_status=True)
            profile = getattr(ib_user, 'commissioning_profile', None)
            if not profile:
                return Response({"error": "No commissioning profile found for IB user."}, status=404)

            max_levels = profile.get_max_levels() if hasattr(profile, 'get_max_levels') else 3
            levels_data = []
            for lvl in range(1, max_levels + 1):
                clients = ib_user.get_clients_by_level(lvl)
                client_list = [
                    {"user_id": client.user_id, "name": client.username, "email": client.email}
                    for client in clients
                ]
                levels_data.append({
                    "level": lvl,
                    "clients": client_list
                })
            return Response({"levels": levels_data}, status=200)

        except ObjectDoesNotExist:
            return Response({"error": "IB user not found or invalid user ID."}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)
        
class CreatePropTradingPackageView(APIView):
    """
    API View to create a new prop trading package.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def post(self, request):
        serializer = PackageSerializer(data=request.data)
        if serializer.is_valid():
            package = serializer.save()

            
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Created a new prop trading package: {package.name}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=package.id,
                related_object_type="Package"
            )

            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
        """
        Update the status of an IB request.
        """
        try:
            ib_request = IBRequest.objects.get(id=id)
        except IBRequest.DoesNotExist:
            return Response(
                {"error": "IB Request not found."}, status=status.HTTP_404_NOT_FOUND
            )

        
        if "status" not in request.data or 'commissioning_profile' not in request.data:
            return Response(
                {"error": "Invalid data. Only 'status' and 'commissioning_profile' fields are allowed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        
        valid_statuses = ["approved", "rejected"]
        if request.data["status"] not in valid_statuses:
            return Response(
                {"error": f"Invalid status. Must be one of {valid_statuses}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        
        previous_status = ib_request.status  
        ib_request.status = request.data["status"]
        commissioning_profile = CommissioningProfile.objects.get(id=int(request.data['commissioning_profile']))
        ib_request.user.commissioning_profile = commissioning_profile
        ib_request.user.IB_status = True if request.data["status"] == "approved" else False

        ib_request.save()
        ib_request.user.save()

        
        ActivityLog.objects.create(
            user=request.user,
            activity=(
                f"Updated IB request #{ib_request.id} status from '{previous_status}' to '{ib_request.status}'. "
                f"Commissioning profile set to '{commissioning_profile.name}'."
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

class BankDetailsRequestsView(APIView):
    """
    API View to handle fetching all pending bank details requests.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        """
        Get all pending bank details requests.
        """
        if request.user.manager_admin_status in ['Admin', 'Manager']:
            requests = BankDetailsRequest.objects.filter(status="PENDING")
        else:
            requests = BankDetailsRequest.objects.none()


        
        serializer = BankDetailsRequestSerializer(requests, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ApproveBankDetailsRequestView(APIView):
    """
    API View to approve a bank details request.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def patch(self, request, id):
        """
        Approve a specific bank details request.
        """
        try:
            request_obj = BankDetailsRequest.objects.get(id=id, status="PENDING")
            request_obj.approve()
            return Response(
                {"message": "Bank details request approved successfully."},
                status=status.HTTP_200_OK,
            )
        except BankDetailsRequest.DoesNotExist:
            return Response(
                {"error": "Bank details request not found or already processed."},
                status=status.HTTP_404_NOT_FOUND,
            )

class RejectBankDetailsRequestView(APIView):
    """
    API View to reject a bank details request.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def patch(self, request, id):
        """
        Reject a specific bank details request.
        """
        try:
            
            request_obj = BankDetailsRequest.objects.get(id=id, status="PENDING")

            
            request_obj.reject()

            
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
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        """
        Get all pending profile change requests.
        """
        if request.user.manager_admin_status in ['Admin', 'Manager']:
            requests = ChangeRequest.objects.filter(status="PENDING")
        else:
            requests = ChangeRequest.objects.none()

        serializer = ChangeRequestSerializer(requests, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class ApproveProfileChangeRequestView(APIView):
    """
    API View to approve a profile change request.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def patch(self, request, id):
        try:
            change_request = ChangeRequest.objects.get(id=id, status="PENDING")
            change_request.approve()

            # Send KYC verified email if id_proof or address_proof is present and verified
            user = change_request.user
            from adminPanel.EmailSender import EmailSender
            user_name = user.get_full_name() if hasattr(user, 'get_full_name') else user.username
            login_url = 'https://client.vtindex.com'
            support_url = 'support@vtindex.com'
            current_year = timezone.now().year
            if (change_request.id_proof and getattr(user, 'id_proof_verified', False)) or (change_request.address_proof and getattr(user, 'address_proof_verified', False)):
                EmailSender.send_kyc_verified_email(
                    user.email,
                    user_name,
                    login_url,
                    support_url,
                    current_year
                )

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

            return Response({"message": "Request approved successfully."}, status=status.HTTP_200_OK)
        except ChangeRequest.DoesNotExist:
            return Response({"error": "Request not found or already processed."}, status=status.HTTP_404_NOT_FOUND)


class RejectProfileChangeRequestView(APIView):
    """
    API View to reject a profile change request.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def patch(self, request, id):
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

            return Response({"message": "Request rejected successfully."}, status=status.HTTP_200_OK)
        except ChangeRequest.DoesNotExist:
            return Response({"error": "Request not found or already processed."}, status=status.HTTP_404_NOT_FOUND)

class MAMManagerView(APIView):
    """
    API View to handle MAM manager operations.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def get(self, request):
        try:
            if request.user.manager_admin_status == 'Admin':
                mam_accounts = TradingAccount.objects.filter(account_type='mam')
            else:
                # For managers, only show MAM accounts of their assigned clients
                mam_accounts = TradingAccount.objects.filter(
                    account_type='mam',
                    user__created_by=request.user
                )

            serializer = TradingAccountSerializer(mam_accounts, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class MAMInvestorView(APIView):
    """
    API View to handle MAM investor operations.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def get(self, request):
        try:
            if request.user.manager_admin_status == 'Admin':
                investment_accounts = TradingAccount.objects.filter(account_type='mam_investment')
            else:
                # For managers, only show investment accounts of their assigned clients
                investment_accounts = TradingAccount.objects.filter(
                    account_type='mam_investment',
                    user__created_by=request.user
                )

            serializer = TradingAccountSerializer(investment_accounts, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class MAMInvestmentDetailsView(APIView):
    """
    API View to get details of a specific MAM investment account.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def get(self, request, account_id):
        try:
            investment = TradingAccount.objects.get(
                account_id=account_id,
                account_type='mam_investment'
            )
            
            # Check manager permissions
            if request.user.manager_admin_status == 'Manager' and getattr(investment.user, 'created_by', None) != request.user:
                return Response(
                    {"error": "You don't have permission to view this investment account"},
                    status=status.HTTP_403_FORBIDDEN
                )

            serializer = TradingAccountSerializer(investment)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except TradingAccount.DoesNotExist:
            return Response(
                {"error": "Investment account not found"},
                status=status.HTTP_404_NOT_FOUND
            )


