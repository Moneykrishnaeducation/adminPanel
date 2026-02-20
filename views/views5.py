from adminPanel.mt5.services import MT5ManagerActions
from rest_framework.decorators import api_view, permission_classes
from django.utils.timezone import now
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.conf import settings
from .views import get_client_ip, generate_password
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from adminPanel.permissions import *
from rest_framework.response import Response
from rest_framework.views import APIView
from .views import generate_password, get_client_ip
from adminPanel.models import *
from adminPanel.serializers import *
from adminPanel.permissions import *
import logging

logger = logging.getLogger(__name__)
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator


class TogglePropTradingAccountStatusView(APIView):
    """
    API View to toggle the status of a prop trading account.
    """
    permission_classes = [IsAdmin]

    def post(self, request, account_id):
        try:
            account = TradingAccount.objects.get(account_id=account_id, account_type='prop')
            new_status = request.data.get('status')
            
            if new_status not in ['enabled', 'disabled']:
                return Response(
                    {"error": "Invalid status. Must be 'enabled' or 'disabled'."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            account.is_enabled = (new_status == 'enabled')
            account.save()

            ActivityLog.objects.create(
                user=request.user,
                activity=f"Changed prop trading account {account_id} status to {new_status}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=now(),
                related_object_id=account.id,
                related_object_type="PropTradingAccount"
            )

            return Response(
                {"message": f"Account {account_id} {new_status} successfully."},
                status=status.HTTP_200_OK
            )
        except TradingAccount.DoesNotExist:
            return Response(
                {"error": "Prop trading account not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class LatestTradingAccountGroupView(APIView):
    """
    Fetch the latest TradingAccountGroup object excluding demo groups.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        try:
            latest_group = TradingAccountGroup.objects.filter(is_demo=False).latest('id')
            serializer = TradingAccountGroupSerializer(latest_group)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except TradingAccountGroup.DoesNotExist:
            return Response({"error": "No trading account groups found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class UpdateTradingGroupView(APIView):
    """
    Update the selected trading group for a specific trading account.
    """
    permission_classes = [IsAdmin]

    def post(self, request):
        account_id = request.data.get("account_id")
        # Support both 'group_id' and 'selected_group' for backward compatibility
        selected_group = request.data.get("group_id") or request.data.get("selected_group")

        if not account_id or not selected_group:
            return Response(
                {"success": False, "message": "Both account_id and group_id are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            trading_account = TradingAccount.objects.get(account_id=account_id)
        except TradingAccount.DoesNotExist:
            return Response(
                {"success": False, "message": "Trading account not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Validate group exists (skip validation if TradingAccountGroup table is empty)
        try:
            latest_group = TradingAccountGroup.objects.latest('created_at')
            if selected_group not in latest_group.approved_groups:
                logger.warning(f"Group {selected_group} not in approved groups, but proceeding with MT5 update")
        except TradingAccountGroup.DoesNotExist:
            logger.info("No TradingAccountGroup configured, skipping validation")

        # Try to update MT5 first
        try:
            mt5_manager = MT5ManagerActions()
            
            # First verify the account exists in MT5
            current_group = mt5_manager.get_group_of(int(account_id))
            if not current_group:
                logger.error(f"Account {account_id} not found in MT5 or unable to get current group")
                return Response(
                    {"success": False, "message": f"Account {account_id} not found in MT5 or unable to retrieve account information."},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            logger.info(f"Account {account_id} current group: {current_group}, attempting to change to: {selected_group}")
            
            # Attempt the group change
            if mt5_manager.change_account_group(int(account_id), selected_group):
                # MT5 update succeeded, now update database
                trading_account.group_name = selected_group
                trading_account.save()
                
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Updated trading group for account {account_id} from {current_group} to {selected_group}.",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="update",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=now(),
                    related_object_id=trading_account.account_id,
                    related_object_type="TradingAccount"
                )
                
                logger.info(f"Successfully updated trading group for account {account_id} to {selected_group}")
                return Response(
                    {"success": True, "message": f"Trading group updated successfully from '{current_group}' to '{selected_group}'!"},
                    status=status.HTTP_200_OK
                )
            else:
                logger.error(f"MT5 UserUpdate failed for account {account_id}. Group: {selected_group}")
                return Response(
                    {"success": False, "message": f"Failed to update trading group in MT5. Current group: '{current_group}'. Please verify the group name '{selected_group}' exists in MT5 and try again."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        except Exception as e:
            logger.error(f"Error updating trading group for account {account_id}: {str(e)}", exc_info=True)
            return Response(
                {"success": False, "message": f"Error updating trading group: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )



class AccountDetailsView(APIView):
    """
    Fetch account details for a specific account ID.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, account_id):
        try:
            account = TradingAccount.objects.get(account_id=account_id)
            if account:
                mt5action = MT5ManagerActions()
                try:
                    balance_response = mt5action.get_balance(int(account_id)) 
                except:
                    return Response({"error": "Failed to fetch balance"}, status=balance_response.status_code)
                try:
                    equity_response = mt5action.get_equity(int(account_id)) 
                except:
                    return Response({"error": "Failed to fetch equity"}, status=equity_response.status_code)
                try:
                    positions_response = mt5action.get_open_positions(int(account_id)) 
                except:
                    return Response({"error": "Failed to fetch open positions"}, status=positions_response.status_code)
                data = {
                    "balance": balance_response,
                    "equity": equity_response,
                    "open_positions": positions_response
                }
                del mt5action
                return Response(data, status=status.HTTP_200_OK)
            else:
                return Response({"error": "Trading account not found."}, status=status.HTTP_404_NOT_FOUND)
        except TradingAccount.DoesNotExist:
            return Response({"error": "Trading account not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AccountTransactionsView(APIView):
    """
    Fetch all transactions for a specific trading account.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, account_id):
        try:
            if request.user.manager_admin_status in ['Admin', 'Manager']:
                account = TradingAccount.objects.get(account_id=account_id)
            else:
                account = TradingAccount.objects.none()
            if account is not None:
                transactions = Transaction.objects.filter(trading_account=account).order_by('-created_at')
            else:
                transactions = Transaction.objects.none()

            serializer = TransactionSerializer(transactions, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except TradingAccount.DoesNotExist:
            return Response(
                {"error": "Trading account not found or does not belong to the user."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        
class TradingHistoryView(APIView):
    """
    Fetch trading history for a specific trading account using MT5 operations via Flask.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, account_id):
        try:
            if request.user.manager_admin_status in ['Admin', 'Manager']:
                account = TradingAccount.objects.get(account_id=account_id)
            else:
                return Response({"error": "Not authorized to view this account"}, status=status.HTTP_403_FORBIDDEN)

            
            if account:
                open_positions = MT5ManagerActions().get_open_positions(int(account.account_id))
                trading_history = [
                    {
                        "trade_id": position.get("id"),
                        "symbol": position.get("symbol"),
                        "volume": position.get("volume"),
                        "price": position.get("price"),
                        "profit": position.get("profit"),
                        "type": position.get("type"),
                    }
                    for position in open_positions
                ]

                return Response(trading_history, status=status.HTTP_200_OK)
            else:
                return Response({"error": "Failed to retrieve trading history."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except TradingAccount.DoesNotExist:
            return Response({"error": "Trading account not found or does not belong to the user."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": f"An unexpected error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class MamAccountsAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]
    
    def get(self, request):
        try:
            if request.user.manager_admin_status in ['Admin', 'Manager']:
                mam_accounts = TradingAccount.objects.filter(account_type='mam')
            else:
                mam_accounts = TradingAccount.objects.none()
            search_query = request.GET.get('search', '')
            if search_query:
                mam_accounts = mam_accounts.filter(
                    Q(user__email__icontains=search_query) |
                    Q(account_id__icontains=search_query) |
                    Q(account_name__icontains=search_query) |
                    Q(risk_level__icontains=search_query) |
                    Q(payout_frequency__icontains=search_query)
                )

            sort_by = request.GET.get('account_id', 'account_id')  
            sort_order = request.GET.get('sortOrder', 'asc')
            if sort_order == 'desc':
                sort_by = f'-{sort_by}'
            mam_accounts = mam_accounts.order_by(sort_by)

            paginator = PageNumberPagination()
            paginator.page_size = request.GET.get('pageSize', 10)
            paginated_accounts = paginator.paginate_queryset(mam_accounts, request)

            serializer = TradingAccountSerializer(paginated_accounts, many=True)
            return paginator.get_paginated_response(serializer.data)
        except Exception as e:
            print(e)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        
class MamInvestmentsAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, *args, **kwargs):
        try:
            if request.user.manager_admin_status in ['Admin', 'Manager']:
                investments = TradingAccount.objects.filter(account_type='mam_investment')
            else:
                investments = TradingAccount.objects.none()

            search_query = request.GET.get('params', '')  # Corrected search key
            if search_query:
                investments = investments.filter(
                    Q(user__email__icontains=search_query) |
                    Q(account_id__icontains=search_query) |
                    Q(account_name__icontains=search_query) |
                    Q(mam_master_account__account_name__icontains=search_query) |
                    Q(mam_master_account__account_id__icontains=search_query)
                )

            sort_by = request.GET.get('user__email', 'user__email')  # Use user__email for sorting
            sort_order = request.GET.get('sortOrder', 'asc')
            if sort_order == 'desc':
                sort_by = f'-{sort_by}'
            investments = investments.order_by(sort_by)

            paginator = PageNumberPagination()
            paginator.page_size = int(request.GET.get('pageSize', 10))
            paginated_investments = paginator.paginate_queryset(investments, request)

            serializer = TradingAccountSerializer(paginated_investments, many=True)
            return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            print(e)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UpdatePropTradingRequestStatusView(APIView):
    """
    Update the status of a proprietary trading request.
    """
    permission_classes = [IsAdmin]

    def post(self, request, pk, *args, **kwargs):
        def send_prop_account_approval_email(user, account_id, master_password, investor_password):
            """
            Sends an email to the user notifying them of their approved proprietary trading account.
            """
            subject = "Your Proprietary Trading Account Has Been Approved"
            html_message = render_to_string("emails/prop_approved.html", {
                "username": user.username,
                "account_id": account_id,
                "master_password": master_password,
                "investor_password": investor_password,
                "mt5_server": "VTIndex-MT5",  
            })
            email = EmailMessage(
                subject=subject,
                body=html_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
            )
            email.content_subtype = "html"  
            email.send()
        prop_request = get_object_or_404(PropTradingRequest, id=pk)
        status_value = request.data.get("status")
        if prop_request.status != "pending":
            return Response(
                {"error": "Only Pending requests"},
                status=status.HTTP_400_BAD_REQUEST,
            )
            

        if not status_value or status_value not in ["approved", "rejected"]:
            return Response(
                {"error": "Invalid status value. Allowed values are 'approved' or 'rejected'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if status_value == "approved":
                approver = request.user
                groupName = TradingAccountGroup.objects.latest('created_at').default_group
                mpass = generate_password()
                ipass = generate_password()
                agentID = str(int(prop_request.package.total_tradable_fund - prop_request.package.max_cutoff))
                a = 5-len(str(prop_request.id))
                prop_ider = "".join(["0" for _ in range(a)]) + str(prop_request.id)
                
                payload_add = {
                    'group_name': groupName,
                    'leverage': prop_request.package.leverage,
                    'client': {
                        'first_name': prop_request.user.first_name,
                        'last_name': prop_request.user.last_name,
                        'email': prop_request.user.email,
                        'country': prop_request.user.country,
                        'phone_number': prop_request.user.phone_number
                    },
                    'master_password': mpass,
                    'investor_password': ipass,
                    'agent': int("7255"+prop_ider+str(agentID))
                }
                mt5action = MT5ManagerActions()
                prop_id = mt5action.add_new_account(groupName,prop_request.package.leverage, prop_request.user, mpass, ipass, int("7255"+prop_ider+str(agentID)))
                if prop_id:
                    if mt5action.deposit_funds(prop_id, round(float(prop_request.package.total_tradable_fund),2), "Initial deposit"):
                        prop_account = TradingAccount.objects.create(
                            user=prop_request.user,
                            account_id=prop_id,
                            account_type='prop',
                            account_name=f"Proprietary Account - {prop_request.package_name}",
                            package=prop_request.package,
                            approved_by=approver,
                            approved_at=timezone.now()
                        )
                        prop_request.trading_account = prop_account
                        prop_request.status = 'approved'
                        prop_request.handled_by = f"{approver.username} - {approver.email} - {approver.id}"
                        prop_request.handled_at=timezone.now()
                        prop_request.save()

                        ActivityLog.objects.create(
                            user=approver,
                            activity=(
                                f"Approved proprietary trading request for user {prop_request.user.username} "
                                f"and created proprietary account '{prop_account.account_name}'."
                            ),
                            ip_address=get_client_ip(request),
                            endpoint=request.path,
                            activity_type="update",
                            activity_category="management",
                            user_agent=request.META.get("HTTP_USER_AGENT", ""),
                            timestamp=now(),
                            related_object_id=prop_account.id,
                            related_object_type="TradingAccount",
                        )
                        send_prop_account_approval_email(prop_account.user, prop_account.account_id, mpass, ipass)

            elif status_value == "rejected":
                approver = request.user
                prop_request.status = 'rejected'
                prop_request.handled_by = f"{approver.username} - {approver.email} - {approver.id}"
                prop_request.handled_at = timezone.now()
                prop_request.save()
                
                ActivityLog.objects.create(
                    user=approver,
                    activity=f"Rejected proprietary trading request for user {prop_request.user.username}.",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="update",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=now(),
                    related_object_id=prop_request.id,
                    related_object_type="PropTradingRequest",
                )

            return Response(
                {"message": f"Request successfully {status_value}."},
                status=status.HTTP_200_OK,
            )
        except ValueError as e:
            print(e)
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

class PropTradersListView(APIView):
    """
    API to fetch the list of proprietary traders with pagination, sorting, and searching.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, *args, **kwargs):
        try:
            if request.user.manager_admin_status in ['Admin', 'Manager']:
                prop_trading_accounts = TradingAccount.objects.filter(account_type='prop')
            else:
                prop_trading_accounts = TradingAccount.objects.none()

            search_query = request.GET.get('search', '').strip()
            
            if search_query:
                print(search_query)
                search_filters = Q()
                for field in TradingAccount._meta.get_fields():
                    if isinstance(field, (models.CharField, models.TextField)):
                        field_name = field.name
                        search_filters |= Q(**{f"{field_name}__icontains": search_query})
                prop_trading_accounts = prop_trading_accounts.filter(search_filters)

            sort_by = request.GET.get('created_at', 'created_at')
            sort_order = request.GET.get('sortOrder', 'asc')
            if sort_order == 'desc':
                sort_by = f'-{sort_by}'
            prop_trading_accounts = prop_trading_accounts.order_by(sort_by)

            paginator = PageNumberPagination()
            paginator.page_size = request.GET.get('pageSize', 10)  # Default page size
            paginated_accounts = paginator.paginate_queryset(prop_trading_accounts, request)

            serializer = TradingAccountSerializer(paginated_accounts, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            print(e)
            return Response(
                {"error": f"Failed to fetch proprietary traders: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
            
                    
class InvestorListView(APIView):
    """
    API View to fetch a list of investors for a specific MAM master account.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, account_id):
        try:
            mam_account = TradingAccount.objects.filter(
                account_id=account_id, account_type='mam'
            ).first()
            if not mam_account:
                return Response(
                    {"error": "MAM Master Account not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            
            investors = TradingAccount.objects.filter(mam_master_account=mam_account)
            serializer = TradingAccountSerializer(investors, many=True)
            return Response({"investors": serializer.data}, status=status.HTTP_200_OK)

        except Exception as e:
            
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        
class OpenPositionsView(APIView):
    """
    API View to fetch open positions for a specific trading account via MT5 service.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, **kwargs):
        try:
            # Handle both mam_id and account_id for backwards compatibility
            account_id = kwargs.get('account_id') or kwargs.get('mam_id')
            if not account_id:
                return Response(
                    {"error": "Account ID is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            
            positions = MT5ManagerActions().get_open_positions(int(account_id))
            return Response({"positions": positions}, status=status.HTTP_200_OK)
        except Exception as e:
            print(e)
            return Response(
                {"error": "Failed to fetch open positions from MT5 service."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
            
class ServerDetailsView(APIView):
    permission_classes = [IsAdmin]  

    def get(self, request):
        latest_server = ServerSetting.objects.latest('created_at')  
        server_details = {
            "ip_address": latest_server.get_decrypted_server_ip(),
            "real_login": latest_server.real_account_login,
            "password": latest_server.get_decrypted_real_account_password()
        }
        return Response(server_details, status=status.HTTP_200_OK)

@api_view(['POST'])
@csrf_exempt
@permission_classes([IsAuthenticated, IsAdminOrManager])
def CommissionCreationView(request):
    """
    MT5 Webhook Endpoint for Instant Commission Creation
    
    Called by MT5 Expert Advisor when positions close.
    Optimized for lightning-fast processing (target: <20ms).
    """
    import time
    import logging
    from django.conf import settings
    
    start_time = time.time()
    logger = logging.getLogger(__name__)
    
    try:
        # ===== SECURITY: Token Authentication =====
        auth_header = request.headers.get('Authorization', '')
        expected_token = getattr(settings, 'COMMISSION_WEBHOOK_TOKEN', None)
        
        if expected_token and (not auth_header.startswith('Bearer ') or auth_header[7:] != expected_token):
            logger.warning(f"Unauthorized webhook attempt from {request.META.get('REMOTE_ADDR')}")
            return Response(
                {"error": "Unauthorized - Invalid token"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # ===== VALIDATION: Required Fields =====
        login_id = request.data.get("login_id")
        position_id = request.data.get("position_id")
        action = request.data.get("action")  
        entry_type = request.data.get("entry_type")  
        symbol = request.data.get("symbol")
        time = request.data.get("time")  
        commission = abs(float(request.data.get("commission", 0)))

        if not login_id or not position_id or not symbol or commission == 0.0:
            return Response(
                {"error": "Invalid data. Ensure all fields (Login ID, Position ID, Symbol, Commission) are provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ===== OPTIMIZATION: Fetch with select_related (single query) =====
        position_type = "buy" if action == 1 else "sell"
        position_direction = "in" if entry_type == 0 else "out"
        
        trading_account = get_object_or_404(
            TradingAccount.objects.select_related('user', 'user__parent_ib'),
            account_id=login_id
        )
        client_user = trading_account.user

        # ===== VALIDATION: Parent IB Check =====
        if not client_user.parent_ib:
            logger.info(f"Position {position_id}: No parent IB for account {login_id}")
            return Response({"error": "Client does not have a parent IB."}, status=status.HTTP_400_BAD_REQUEST)

        # ===== COMMISSION CREATION =====
        lot_size = float(request.data.get('lot_size', 1.0) or 1.0)
        profit = float(request.data.get('profit', 0.0) or 0.0)
        deal_ticket = request.data.get('deal_ticket')  # MT5 Deal Ticket ID
        mt5_close_time_str = request.data.get('mt5_close_time')  # MT5 close timestamp
        
        # Parse MT5 close time if provided
        mt5_close_time = None
        if mt5_close_time_str:
            try:
                from datetime import datetime
                from django.utils import timezone
                # Try parsing ISO format or common formats
                mt5_close_time = timezone.make_aware(datetime.fromisoformat(mt5_close_time_str.replace('Z', '+00:00')))
            except Exception as e:
                logger.warning(f"Could not parse mt5_close_time '{mt5_close_time_str}': {e}")

        CommissionTransaction.create_commission(
            client=client_user,
            total_commission=commission,
            position_id=position_id,
            trading_account=trading_account,
            trading_symbol=symbol,
            position_type=position_type,
            position_direction=position_direction,
            lot_size=lot_size,
            profit=profit,
            deal_ticket=deal_ticket,
            mt5_close_time=mt5_close_time,
        )

        # ===== PERFORMANCE LOGGING =====
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"✅ Commission created: Position {position_id}, Account {login_id}, "
                   f"Commission {commission}, Processing time: {elapsed_ms:.2f}ms")

        return Response({
            "message": "CommissionTransaction created successfully.",
            "position_id": position_id,
            "processing_time_ms": round(elapsed_ms, 2)
        }, status=status.HTTP_201_CREATED)

    except TradingAccount.DoesNotExist:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.error(f"❌ Trading account {login_id} not found (took {elapsed_ms:.2f}ms)")
        return Response({"error": f"Trading account with login_id {login_id} not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        print(e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
class ServerSettingsAPIView(APIView):
    """
    API View to handle MT5 server settings configuration
    GET: Retrieve current server settings
    PUT: Update server settings
    POST: Update server settings (same as PUT for compatibility)
    """
    permission_classes = [AllowAny]  # <-- Replace with IsAdmin after testing
    http_method_names = ['get', 'put', 'post', 'head', 'options']

    def get(self, request):
        try:
            # Allow caller to request a specific server_type via query param
            # Accepts: 'true'/'false', '1'/'0', case-insensitive
            server_type_param = request.GET.get('server_type')
            if server_type_param is not None:
                st = str(server_type_param).lower()
                server_type_bool = st in ('1', 'true', 'yes', 'y')
                server_setting = ServerSetting.objects.filter(server_type=server_type_bool).order_by('-created_at').first()
            else:
                server_setting = ServerSetting.objects.latest('created_at')

            if not server_setting:
                return Response({
                    "server_ip": "",
                    "login_id": "",
                    "server_password": "",
                    "server_name": ""
                }, status=status.HTTP_200_OK)

            return Response({
                "server_ip": server_setting.get_decrypted_server_ip(),
                "login_id": server_setting.real_account_login,
                "server_password": server_setting.get_decrypted_real_account_password(),
                "server_name": server_setting.server_name_client
            }, status=status.HTTP_200_OK)
        except ServerSetting.DoesNotExist:
            return Response({
                "server_ip": "",
                "login_id": "",
                "server_password": "",
                "server_name": ""
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": f"Failed to retrieve server settings: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def put(self, request, *args, **kwargs):
        try:
            data = request.data
            required_fields = ['server_ip', 'login_id', 'server_password', 'server_name']
            missing_fields = [field for field in required_fields if not data.get(field)]

            if missing_fields:
                return Response(
                    {"error": f"Missing required fields: {', '.join(missing_fields)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Avoid get_or_create() without lookup kwargs which raises
            # MultipleObjectsReturned when more than one row exists. Instead
            # pick the most recent settings row or create one if missing.
            # If caller provided server_type in body, use it to select which record to upsert
            server_type_in_body = data.get('server_type')
            if server_type_in_body is not None:
                st = str(server_type_in_body).lower()
                server_type_bool = st in ('1', 'true', 'yes', 'y')
                server_setting = ServerSetting.objects.filter(server_type=server_type_bool).order_by('-created_at').first()
            else:
                server_setting = ServerSetting.objects.order_by('-created_at').first()
            created = False
            if server_setting is None:
                server_setting = ServerSetting.objects.create(
                    server_ip=data['server_ip'],
                    real_account_login=data['login_id'],
                    real_account_password=data['server_password'],
                    server_name_client=data['server_name'],
                    server_type= server_type_bool if server_type_in_body is not None else True,
                )
                created = True
            else:
                server_setting.server_ip = data['server_ip']
                server_setting.real_account_login = data['login_id']
                server_setting.real_account_password = data['server_password']
                server_setting.server_name_client = data['server_name']
                if server_type_in_body is not None:
                    server_setting.server_type = server_type_bool
                server_setting.save()

            # Force refresh MT5 Manager connection with new credentials
            try:
                from adminPanel.mt5.services import reset_manager_instance
                reset_manager_instance()
                logger.info("MT5 Manager connection reset after server settings update")
            except Exception as e:
                logger.warning(f"Failed to reset MT5 Manager connection: {e}")

            # Optional: Log only if user is authenticated
            if request.user and request.user.is_authenticated:
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"{'Created' if created else 'Updated'} MT5 server settings",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="update" if not created else "create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=server_setting.id,
                    related_object_type="ServerSetting"
                )

            return Response({
                "message": "Server settings updated successfully",
                "server_ip": server_setting.get_decrypted_server_ip(),
                "login_id": server_setting.real_account_login,
                "server_name": server_setting.server_name_client
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": f"Failed to update server settings: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def post(self, request, *args, **kwargs):
        """
        POST method for server settings - same functionality as PUT for compatibility
        """
        try:
            data = request.data
            required_fields = ['server_ip', 'login_id', 'server_password', 'server_name']
            missing_fields = [field for field in required_fields if not data.get(field)]

            if missing_fields:
                return Response(
                    {"error": f"Missing required fields: {', '.join(missing_fields)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Avoid get_or_create() without lookup kwargs which raises
            # MultipleObjectsReturned when more than one row exists. Instead
            # pick the most recent settings row or create one if missing.
            server_type_in_body = data.get('server_type')
            if server_type_in_body is not None:
                st = str(server_type_in_body).lower()
                server_type_bool = st in ('1', 'true', 'yes', 'y')
                server_setting = ServerSetting.objects.filter(server_type=server_type_bool).order_by('-created_at').first()
            else:
                server_setting = ServerSetting.objects.order_by('-created_at').first()
            created = False
            if server_setting is None:
                server_setting = ServerSetting.objects.create(
                    server_ip=data['server_ip'],
                    real_account_login=data['login_id'],
                    real_account_password=data['server_password'],
                    server_name_client=data['server_name']
                    , server_type= server_type_bool if server_type_in_body is not None else True
                )
                created = True
            else:
                server_setting.server_ip = data['server_ip']
                server_setting.real_account_login = data['login_id']
                server_setting.real_account_password = data['server_password']
                server_setting.server_name_client = data['server_name']
                if server_type_in_body is not None:
                    server_setting.server_type = server_type_bool
                server_setting.save()

            # Automated full MT5 database and cache reset after updating credentials
            try:
                from adminPanel.mt5.services import reset_manager_instance
                from adminPanel.mt5.models import MT5GroupConfig
                from django.core.cache import cache
                from django.db import transaction
                reset_manager_instance()
                # Delete all cached trading groups
                with transaction.atomic():
                    MT5GroupConfig.objects.all().delete()
                # Clear all Django cache
                cache.clear()
                # Clear MT5-specific cache keys
                for key in ['mt5_manager_error','mt5_groups_sync','mt5_connection_status','mt5_leverage_options','mt5_groups_last_sync']:
                    cache.delete(key)
                logger.info("Full MT5 database and cache reset after server settings update via POST")
            except Exception as e:
                logger.warning(f"Failed to fully reset MT5 database/cache: {e}")

            # Optional: Log only if user is authenticated
            if request.user and request.user.is_authenticated:
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"{'Created' if created else 'Updated'} MT5 server settings via POST",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="update" if not created else "create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=server_setting.id,
                    related_object_type="ServerSetting"
                )

            return Response({
                "message": "Server settings updated successfully",
                "server_ip": server_setting.get_decrypted_server_ip(),
                "login_id": server_setting.real_account_login,
                "server_name": server_setting.server_name_client
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": f"Failed to update server settings: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@method_decorator(csrf_exempt, name='dispatch')
class DemoServerSettingsAPIView(APIView):
    """
    API View to handle MT5 demo server settings configuration
    Same behaviour as ServerSettingsAPIView but stores/reads demo records (server_type=False)
    """
    permission_classes = [AllowAny]
    http_method_names = ['get', 'put', 'post', 'head', 'options']

    def get(self, request):
        try:
            server_setting = ServerSetting.objects.filter(server_type=False).order_by('-created_at').first()
            if not server_setting:
                return Response({
                    "server_ip": "",
                    "login_id": "",
                    "server_password": "",
                    "server_name": ""
                }, status=status.HTTP_200_OK)
            return Response({
                "server_ip": server_setting.get_decrypted_server_ip(),
                "login_id": server_setting.real_account_login,
                "server_password": server_setting.get_decrypted_real_account_password(),
                "server_name": server_setting.server_name_client
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": f"Failed to retrieve demo server settings: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _upsert_demo(self, data, request):
        required_fields = ['server_ip', 'login_id', 'server_password', 'server_name']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            return Response({"error": f"Missing required fields: {', '.join(missing_fields)}"}, status=status.HTTP_400_BAD_REQUEST)

        server_setting = ServerSetting.objects.filter(server_type=False).order_by('-created_at').first()
        created = False
        if server_setting is None:
            server_setting = ServerSetting.objects.create(
                server_ip=data['server_ip'],
                real_account_login=data['login_id'],
                real_account_password=data['server_password'],
                server_name_client=data['server_name'],
                server_type=False,
            )
            created = True
        else:
            server_setting.server_ip = data['server_ip']
            server_setting.real_account_login = data['login_id']
            server_setting.real_account_password = data['server_password']
            server_setting.server_name_client = data['server_name']
            server_setting.server_type = False
            server_setting.save()

        # Try to reset manager instance for demo connection if applicable
        try:
            from adminPanel.mt5.manager import reset_demo_manager_instance
            reset_demo_manager_instance()
        except Exception:
            pass
        try:
            from adminPanel.mt5.services import reset_manager_instance
            reset_manager_instance()
        except Exception:
            pass

        if request.user and request.user.is_authenticated:
            ActivityLog.objects.create(
                user=request.user,
                activity=f"{'Created' if created else 'Updated'} MT5 demo server settings",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update" if not created else "create",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=server_setting.id,
                related_object_type="ServerSetting"
            )

        return Response({
            "message": "Demo server settings updated successfully",
            "server_ip": server_setting.get_decrypted_server_ip(),
            "login_id": server_setting.real_account_login,
            "server_name": server_setting.server_name_client
        }, status=status.HTTP_200_OK)

    def put(self, request, *args, **kwargs):
        try:
            return self._upsert_demo(request.data, request)
        except Exception as e:
            return Response({"error": f"Failed to update demo server settings: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request, *args, **kwargs):
        try:
            return self._upsert_demo(request.data, request)
        except Exception as e:
            return Response({"error": f"Failed to create demo server settings: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DemoAvailableGroupsView(APIView):
    """
    Fetch available trading groups from the DEMO MT5 server (ServerSetting where server_type=False).
    Returns groups in the same format as AvailableGroupsView so the frontend can use them identically.
    """
    permission_classes = [IsAdminOrManager]

    def get(self, request):
        try:
            from adminPanel.mt5.manager import get_demo_manager_instance

            # Connect to demo MT5 server
            demo_instance = get_demo_manager_instance()
            demo_manager = demo_instance.manager

            # Fetch groups directly via the MT5Manager API
            group_names = []
            for i in range(demo_manager.GroupTotal()):
                grp = demo_manager.GroupNext(i)
                if grp and grp.Group:
                    group_names.append(grp.Group)

            # Load database alias/active info for the groups
            try:
                db_groups = TradeGroup.objects.all()
                db_settings = {}
                for db_group in db_groups:
                    db_settings[db_group.name] = {
                        'is_active': getattr(db_group, 'is_active', False),
                        'alias': getattr(db_group, 'alias', '') or '',
                        'is_default': getattr(db_group, 'is_default', False),
                        'is_demo_default': getattr(db_group, 'is_demo_default', False),
                    }
            except Exception:
                db_settings = {}

            # Determine requester role
            is_admin = getattr(request.user, 'is_superuser', False)
            if not is_admin and hasattr(request.user, 'manager_admin_status'):
                mgr_status = str(request.user.manager_admin_status).lower()
                is_admin = 'admin' in mgr_status
            is_manager = not is_admin and hasattr(request.user, 'manager_admin_status') and \
                         'manager' in str(request.user.manager_admin_status).lower()

            formatted_groups = []
            for group_name in group_names:
                db_info = db_settings.get(group_name, {})
                alias = db_info.get('alias', '') or ''

                base = {
                    "id": group_name,
                    "value": group_name,
                    "label": group_name,
                    "name": group_name,
                    "is_demo": True,  # All groups from the demo server are demo groups
                    "is_live": False,
                    "is_default": db_info.get('is_default', False),
                    "is_demo_default": db_info.get('is_demo_default', False),
                    "enabled": db_info.get('is_active', False),
                    "leverage_max": 1000,
                    "leverage_min": 1,
                    "currency": "USD",
                    "deposit_min": 0,
                    "description": "Demo trading group",
                    "group_type": "MT5",
                    "alias": alias,
                    "original_name": group_name,
                }

                if is_manager:
                    if not alias:
                        continue  # Managers only see groups with an alias
                    base["id"] = alias
                    base["value"] = alias
                    base["label"] = alias
                    base["name"] = alias

                formatted_groups.append(base)

            return Response({
                "groups": formatted_groups,
                "available_groups": formatted_groups,
                "source": "demo_mt5_server",
                "success": True,
                "total_groups": len(formatted_groups),
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error fetching groups from demo MT5 server: {str(e)}")
            return Response({
                "groups": [],
                "available_groups": [],
                "source": "demo_mt5_server",
                "success": False,
                "error": str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SaveDemoGroupConfigurationView(APIView):
    """
    Save demo group configuration. Only touches is_demo_default / demo group flags —
    never modifies is_default (real server default) so the real group page is unaffected.
    
    Expected payload:
      {
        "groups": [
          { "id": "GroupName", "enabled": true, "alias": "...", "demo_default": true/false }
        ]
      }
    Exactly one group should have demo_default=true.
    """
    permission_classes = [IsSuperuser]

    def post(self, request):
        try:
            groups_config = request.data.get('groups', [])
            if not groups_config:
                return Response(
                    {'success': False, 'message': 'Missing groups data'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            demo_defaults = [g for g in groups_config if g.get('demo_default', False)]
            if len(demo_defaults) != 1:
                return Response(
                    {'success': False, 'message': 'Exactly one demo default group must be selected'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Only clear is_demo_default — leave is_default (real groups) untouched
            TradeGroup.objects.all().update(is_demo_default=False)

            updated = 0
            for g in groups_config:
                group_id = g.get('id')
                if not group_id:
                    continue

                group = (
                    TradeGroup.objects.filter(name=group_id).first()
                    or TradeGroup.objects.filter(group_id=group_id).first()
                )
                if not group:
                    group = TradeGroup.objects.create(
                        name=group_id,
                        group_id=group_id,
                        description=f'Demo Trading Group: {group_id}',
                        type='demo',
                        is_active=False,
                        is_default=False,
                        is_demo_default=False,
                    )

                group.is_active = g.get('enabled', False)
                group.alias = g.get('alias', '') or ''
                group.is_demo_default = bool(g.get('demo_default', False))
                if group.is_demo_default:
                    group.type = 'demo'
                group.save()
                updated += 1

            demo_group = TradeGroup.objects.filter(is_demo_default=True).first()
            return Response({
                'success': True,
                'message': f'Demo group configuration saved. Updated {updated} groups.',
                'demo_default_group': demo_group.name if demo_group else None,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error saving demo group configuration: {str(e)}")
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )