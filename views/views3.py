from adminPanel.mt5.services import MT5ManagerActions
from django.utils.timezone import now
from django.shortcuts import get_object_or_404
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.http import JsonResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from adminPanel.permissions import IsAdmin, IsManager, OrPermission, IsAuthenticatedUser, IsAdminOrManager
from rest_framework.response import Response
from rest_framework.views import APIView
from .views import get_client_ip
from adminPanel.models import *
from adminPanel.models import ActivityLog
from adminPanel.serializers import *
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Sum
from decimal import Decimal

class CreditOutView(APIView):
    # Use the custom BlacklistCheckingJWTAuthentication from settings instead of overriding
    # authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def post(self, request):
        try:
            account_id = int(request.data.get("accountId"))
            amount = request.data.get("amount")
            comment = request.data.get("comment", "Credit Out TA")
            if not account_id or not amount:
                return Response({"error": "Account ID and amount are required."}, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                amount = round(float(Decimal(amount)), 2)
                if amount <= 0:
                    return Response({"error": "Amount must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)
            except:
                return Response({"error": "Invalid amount format."}, status=status.HTTP_400_BAD_REQUEST)

            try:
                account = TradingAccount.objects.get(account_id=account_id)
            except TradingAccount.DoesNotExist:
                return Response({"error": "Trading account not found."}, status=status.HTTP_404_NOT_FOUND)

            mt5action = MT5ManagerActions( )
            tr = mt5action.credit_out(int(account_id), amount, comment)
            if tr:
                transaction = Transaction.objects.create(
                    user=account.user,
                    trading_account=account,
                    transaction_type="credit_out",
                    amount=round(float(amount),2),
                    description=comment,
                    approved_by = request.user,
                    status="approved",
                    source="Admin Operation",
                )

                serializer = TransactionSerializer(transaction)
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Credited out {amount} from account ID {account_id}.",
                    ip_address=request.META.get('REMOTE_ADDR'),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=transaction.id,
                    related_object_type="Transaction"
                )

                return Response(
                    {
                        "message": "Credit out successful.",
                        "transaction": serializer.data,
                    },
                    status=status.HTTP_201_CREATED,
                )
            else:
                return Response({"error": "MT5 credit out operation failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({"error": f"An unexpected error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
               
class CreditInTransactionView(APIView):
    # Use the custom BlacklistCheckingJWTAuthentication from settings instead of overriding
    # authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [OrPermission(IsAdmin, IsManager)] 

    def post(self, request):
        account_id = request.data.get("accountId")
        amount = request.data.get("amount")
        comment = request.data.get("comment", "Credit In TA")
        if not account_id or not amount:
            return Response({"error": "Account ID and amount are required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amount = round(float(amount), 2)
            if amount <= 0:
                return Response({"error": "Amount must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({"error": "Invalid amount format."}, status=status.HTTP_400_BAD_REQUEST)

        data = {
            'login_id': int(account_id),
            'amount': amount,
            'comment': comment
        }
        mt5action = MT5ManagerActions()
        if mt5action.credit_in(int(account_id), amount, comment):
            try:
                account = TradingAccount.objects.get(account_id=account_id)
            except TradingAccount.DoesNotExist:
                return Response({"error": "Trading account not found."}, status=status.HTTP_404_NOT_FOUND)

            transaction = Transaction.objects.create(
                user=account.user,
                trading_account=account,
                transaction_type="credit_in",
                amount=round(float(amount),2),
                description=comment,
                approved_by = request.user,
                status="approved",
                source="Admin Operation",
            )

            transaction_serializer = TransactionSerializer(transaction)

            ActivityLog.objects.create(
                user=request.user,
                activity=f"Credited in {amount} to account ID {account_id}.",
                ip_address=request.META.get('REMOTE_ADDR'),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=transaction.id,
                related_object_type="Transaction"
            )

            return Response(
                {
                    "message": "Credit in successful.",
                    "transaction": transaction_serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )
        else:
            return Response({"error": "MT5 credit in operation failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class EnableDisableAccountView(APIView):
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def post(self, request):
        # Accept both camelCase and snake_case keys from the frontend
        account_id = request.data.get("accountId") or request.data.get("account_id")
        status_action = request.data.get("status") or request.data.get("action")

        if not account_id or not status_action:
            return Response(
                {"error": "Account ID and status action ('enable' or 'disable') are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        status_action = str(status_action).lower()
        if status_action not in ['enable', 'disable']:
            return Response(
                {"error": "Invalid status action. Use 'enable' or 'disable'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Ensure we're searching with the correct type
            try:
                acct_lookup = int(account_id)
            except Exception:
                acct_lookup = account_id

            account = TradingAccount.objects.get(account_id=acct_lookup)
        except TradingAccount.DoesNotExist:
            return Response(
                {"error": "Trading account not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        data = {
            'login_id': int(account_id),
            'action': status_action
        }
        
        try:
            mt5_ok = MT5ManagerActions().toggle_account_status(int(account.account_id), status_action)
        except Exception as e:
            mt5_ok = False
            mt5_err = str(e)

        if mt5_ok:
            account.is_enabled = (status_action == 'enable')
            account.save()
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Account ID {account_id} was {status_action}d.",
                ip_address=request.META.get('REMOTE_ADDR'),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=account.id,
                related_object_type="TradingAccount"
            )

            return Response(
                {
                    "message": f"Account successfully {status_action}d.",
                    "account_id": account.account_id,
                    "is_enabled": account.is_enabled,
                },
                status=status.HTTP_200_OK
            )
        else:
            return Response({"error": "Failed to update account status in MT5", "detail": locals().get('mt5_err', '') },status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            
class EnableDisableTradingView(APIView):
    permission_classes = [OrPermission(IsAdmin, IsManager)] 

    def post(self, request):
        account_id = request.data.get("accountId") or request.data.get("account_id")
        action = request.data.get("action") or request.data.get("status")

        if not account_id or action not in ["enable", "disable"]:
            return Response(
                {"error": "Invalid data provided. 'account_id' and 'action' ('enable' or 'disable') are required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            try:
                acct_lookup = int(account_id)
            except Exception:
                acct_lookup = account_id
            account = TradingAccount.objects.get(account_id=acct_lookup)
        except TradingAccount.DoesNotExist:
            return Response(
                {"error": "Standard trading account not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        try:
            mt5_ok = MT5ManagerActions().toggle_algo(int(account.account_id), action)
        except Exception:
            mt5_ok = False

        if mt5_ok:
            account.is_algo_enabled = (action == 'enable')
            account.save()
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Trading for account ID {account_id} was {action}d.",
                ip_address=request.META.get('REMOTE_ADDR'),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=account.id,
                related_object_type="TradingAccount"
            )

            return Response(
                {
                    "message": f"Trading successfully {action}d.",
                    "account_id": account.account_id,
                    "is_trading_enabled": account.is_algo_enabled,
                },
                status=status.HTTP_200_OK
            )
        else:
            return Response({"error": "Failed to update trading status in MT5"},status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- Updated ChangeLeverageView to support both JWT and Session authentication, and return available leverage options ---
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response

class ChangeLeverageView(APIView):
    # Use the custom BlacklistCheckingJWTAuthentication from settings instead of overriding
    # authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def get(self, request, account_id):
        try:
            account = TradingAccount.objects.get(account_id=account_id)
            # You can customize available leverage options as needed
            available_leverage = [10, 20, 50, 100, 200, 500,1000]
            return Response({
                "current_leverage": account.leverage,
                "available_leverage": available_leverage
            }, status=status.HTTP_200_OK)
        except TradingAccount.DoesNotExist:
            return Response({"error": "Account not found."}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request):
        account_id = request.data.get('accountId')
        new_leverage = request.data.get('leverage')
        if not account_id or not new_leverage:
            return Response(
                {"error": "Account ID and leverage are required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            new_leverage = int(new_leverage)
            account = TradingAccount.objects.get(account_id=account_id)
            if MT5ManagerActions().change_leverage(int(account_id), new_leverage):
                account.leverage = new_leverage
                account.save()
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Changed leverage for account ID {account_id} to {new_leverage}.",
                    ip_address=request.META.get('REMOTE_ADDR'),
                    endpoint=request.path,
                    activity_type="update",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=account.id,
                    related_object_type="TradingAccount"
                )
                return Response({"message": "Leverage updated successfully!", "new_leverage": new_leverage}, status=status.HTTP_200_OK)
            else:
                return Response({"error": "Failed to update leverage in MT5"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except ValueError:
            return Response({"error": "Leverage must be a valid number."}, status=status.HTTP_400_BAD_REQUEST)
        except TradingAccount.DoesNotExist:
            return Response({"error": "Account not found."}, status=status.HTTP_404_NOT_FOUND)
        
class DemoAccountUpdateView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, *args, **kwargs):
        account_id = request.data.get('account_id')
        is_enabled = request.data.get('is_enabled')
        balance = request.data.get('balance')
        leverage = request.data.get('leverage')

        account = get_object_or_404(DemoAccount, account_id=account_id)
        mt5action = MT5ManagerActions()
        if is_enabled is not None:
            status_action = "enable" if is_enabled else "disable"
            
            if mt5action.toggle_account_status(int(account_id),status_action):
                account.is_enabled = bool(is_enabled)
            else:
                return Response(
                    {"success": False, "message": "Failed to update account status."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        if balance is not None:
            try:
                new_balance = float(balance)
                if new_balance < 0:
                    return Response(
                        {"success": False, "message": "Balance cannot be negative."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                
                
                reset_to = new_balance - mt5action.get_balance(int(account_id))
                if reset_to != 0:
                    if not mt5action.deposit_funds(int(account_id), reset_to, "Demo Reset"):
                        return Response(
                            {"success": False, "message": "Failed to adjust balance."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        )
                account.balance = new_balance
            except (ValueError, TypeError):
                return Response(
                    {"success": False, "message": "Invalid balance value."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if leverage is not None:
            try:
                if mt5action.change_leverage(int(account_id), int(leverage)):
                    account.leverage = int(leverage)
                else:
                    return Response(
                        {"success": False, "message": "Failed to update leverage."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
            except ValueError:
                return Response(
                    {"success": False, "message": "Invalid leverage value."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        account.save()

        serializer = DemoAccountSerializer(account)
        return Response(
            {"success": True, "message": "Account updated successfully.", "account": serializer.data},
            status=status.HTTP_200_OK,
        )
        

class CommissionWithdrawalHistoryView(APIView):
    """
    API View to fetch the complete commission withdrawal transaction history 
    with pagination, sorting, and searching.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        try:
            transactions = Transaction.objects.filter(
                transaction_type='commission_withdrawal'
            )

            # Searching
            search_query = request.query_params.get("search", "").strip()
            if search_query:
                transactions = transactions.filter(
                    Q(username__icontains=search_query) |
                    Q(email__icontains=search_query) |
                    Q(trading_account_id__icontains=search_query) |
                    Q(transaction_type_display__icontains=search_query) |
                    Q(status__icontains=search_query)
                )

            # Sorting
            sort_by = request.query_params.get("sortBy", "created_at")
            sort_order = request.query_params.get("sortOrder", "desc")
            if sort_order == "desc":
                sort_by = f"-{sort_by}"
            transactions = transactions.order_by(sort_by)

            # Pagination
            paginator = PageNumberPagination()
            paginator.page_size = int(request.query_params.get("pageSize", 10))
            paginator.max_page_size = 100
            result_page = paginator.paginate_queryset(transactions, request)

            serializer = TransactionSerializer(result_page, many=True)
            return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class CommissionWithdrawView(APIView):
    """
    API View to fetch withdrawable commission and perform commission withdrawal.
    """
    from adminPanel.permissions import IsAdminOrManager
    permission_classes = [IsAdminOrManager]

    def get(self, request, user_id):
        """
        Fetch the withdrawable commission for the IB user identified by user_id.
        """
        try:
            user = CustomUser.objects.get(user_id=user_id)

            if not user.IB_status:
                return Response({"error": "User is not an IB partner."}, status=status.HTTP_403_FORBIDDEN)

            withdrawable_commission = user.total_earnings - user.total_commission_withdrawals
            return Response(
                {"user_id": user.user_id, "withdrawable_commission": withdrawable_commission},
                status=status.HTTP_200_OK
            )
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def post(self, request):
        try:
        
            user = CustomUser.objects.get(user_id=request.data["userId"])
            # KYC check for commission withdrawal
            if not user.user_verified:
                ActivityLog.objects.create(
                    user=user,
                    activity=f"Blocked commission withdrawal attempt: KYC incomplete for user {user.email}",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )
                return Response({"error": "Withdrawal blocked: Please complete KYC verification before making withdrawals."}, status=status.HTTP_403_FORBIDDEN)
            account_id = request.data["accountId"]
            amount = request.data["amount"]

            if not account_id or not amount:
                return Response({"error": "Account ID and amount are required."}, status=status.HTTP_400_BAD_REQUEST)

            amount = float(amount)
            if amount <= 0:
                return Response({"error": "Amount must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)

            
            withdrawable_commission = user.total_earnings - user.total_commission_withdrawals

            if round(float(withdrawable_commission),2) - round(amount,2) < 0:
                return Response({"error": "Amount exceeds withdrawable commission."}, status=status.HTTP_400_BAD_REQUEST)

            
            trading_account = TradingAccount.objects.filter(account_id=account_id).first()
            if not trading_account:
                return Response({"error": "Trading account not found."}, status=status.HTTP_404_NOT_FOUND)
            
            # Check if this account exists in MT5 and get valid accounts if not
            mt5_manager = MT5ManagerActions()
            try:
                # First verify the account exists in MT5
                mt5_account = mt5_manager.manager.UserGet(int(trading_account.account_id))
                
                if not mt5_account:
                    # Find valid MT5 accounts for this user
                    valid_accounts = []
                    user_accounts = TradingAccount.objects.filter(user=user)
                    
                    for acc in user_accounts:
                        try:
                            mt5_acc = mt5_manager.manager.UserGet(int(acc.account_id))
                            if mt5_acc:
                                valid_accounts.append(acc.account_id)
                        except Exception as e:
                            logging.error(f"Error verifying MT5 account {acc.account_id}: {str(e)}")
                            continue
                    
                    error_msg = f"Account {account_id} not found in MT5."
                    if valid_accounts:
                        error_msg += f" Valid accounts for this user: {', '.join(valid_accounts)}"
                    else:
                        error_msg += " No valid MT5 accounts found for this user."
                    
                    return Response({"error": error_msg}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({"error": f"Error verifying MT5 account: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            result = MT5ManagerActions().deposit_funds(int(trading_account.account_id), round(float(amount), 2), "IBC to Account")
            
            if result:
                # Get the before values for debugging
                before_total_earnings = user.total_earnings
                before_withdrawals = user.total_commission_withdrawals
                before_balance = before_total_earnings - before_withdrawals
                
                # Create a transaction record for the commission withdrawal
                # This will automatically be counted in total_commission_withdrawals property
                transaction = Transaction.objects.create(
                    user=user,
                    trading_account=trading_account,
                    transaction_type="commission_withdrawal",
                    amount=Decimal(str(amount)),  # Convert to Decimal to ensure proper storage
                    status="approved",  # Must be "approved" to match the property's filter
                    approved_by=request.user,
                    approved_at=timezone.now()
                )
                
                # Double check it's saved correctly
                fresh_transaction = Transaction.objects.get(id=transaction.id)
               
                # Force a refresh of the user object from the database
                user = CustomUser.objects.get(id=user.id)
                
                # Get the after values for debugging
                after_total_earnings = user.total_earnings
                after_withdrawals = user.total_commission_withdrawals
                after_balance = after_total_earnings - after_withdrawals
                
                # Check if this specific transaction is being counted
                manual_count = Transaction.objects.filter(
                    user=user,
                    transaction_type="commission_withdrawal",
                    status="approved"
                ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
                
                ActivityLog.objects.create(
                    user=user,
                    activity=f"Commission withdrawal of ${amount} to account ID {account_id}",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=transaction.id,
                    related_object_type="Transaction"
                )
                
                # Calculate and return the remaining balance in the response using the property
                # The new transaction will be automatically included in the total_commission_withdrawals property
                remaining_balance = after_balance
                
                return Response({
                    "success": "Commission withdrawn successfully.",
                    "remaining_balance": float(remaining_balance)
                }, status=status.HTTP_200_OK)
            else:
                return Response({"error": f"Deposit failed: {result}"}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            print(e)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def list_ib_free_users(request):
    try:
        users = CustomUser.objects.filter(parent_ib__isnull=True)
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
        try:
            transactions = Transaction.objects.filter(user__user_id=user_id, transaction_type='commission_withdrawal').order_by('-created_at')
            serializer = TransactionSerializer(transactions, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CommissionZeroView(APIView):
    """
    Admin endpoint to zero a user's withdrawable commission without performing an MT5 deposit.
    Records an approved commission_withdrawal Transaction for the remaining withdrawable amount.
    """
    from adminPanel.permissions import IsAdminOrManager
    permission_classes = [IsAdminOrManager]

    def post(self, request):
        try:
            user_id = request.data.get('userId') or request.data.get('user_id')
            if not user_id:
                return Response({"error": "userId is required."}, status=status.HTTP_400_BAD_REQUEST)

            user = CustomUser.objects.get(user_id=user_id)
            # Calculate withdrawable
            withdrawable_commission = user.total_earnings - user.total_commission_withdrawals
            if withdrawable_commission <= 0:
                return Response({"error": "No withdrawable commission available."}, status=status.HTTP_400_BAD_REQUEST)

            # Create a dummy trading account reference if provided, else None
            account_id = request.data.get('accountId')
            trading_account = None
            if account_id:
                trading_account = TradingAccount.objects.filter(account_id=account_id).first()

            # Create approved transaction to zero balance
            transaction = Transaction.objects.create(
                user=user,
                trading_account=trading_account,
                transaction_type="commission_withdrawal",
                amount=Decimal(str(withdrawable_commission)),
                status="approved",
                approved_by=request.user,
                approved_at=timezone.now()
            )

            # Log activity
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Zeroed withdrawable commission for user {user.email} (user_id={user.user_id}) amount={withdrawable_commission}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                timestamp=timezone.now(),
                related_object_id=transaction.id,
                related_object_type="Transaction"
            )

            # Force refresh and compute remaining
            user = CustomUser.objects.get(id=user.id)
            remaining_balance = user.total_earnings - user.total_commission_withdrawals

            return Response({"success": "Commission zeroed successfully.", "remaining_balance": float(remaining_balance)}, status=status.HTTP_200_OK)

        except CustomUser.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logging.exception("Error zeroing commission")
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

        
        level1_commission = sum(client.total_earnings for client in level1_clients)
        level2_commission = sum(client.total_earnings for client in level2_clients)
        level3_commission = sum(client.total_earnings for client in level3_clients)

        total_commission = level1_commission + level2_commission + level3_commission
        withdrawn_commission = ib_user.total_commission_withdrawals
        withdrawable_commission = total_commission - withdrawn_commission

        
        summary = {
            "level1Clients": len(level1_clients),  
            "level2Clients": len(level2_clients),  
            "level3Clients": len(level3_clients),  
            "level1Commission": round(level1_commission, 2),
            "level2Commission": round(level2_commission, 2),
            "level3Commission": round(level3_commission, 2),
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
            
            level = request.query_params.get('level')

            
            transactions = CommissionTransaction.objects.filter(ib_user_id=user_id)

            
            if level:
                transactions = transactions.filter(ib_level=level)


            
            serializer = CommissionTransactionSerializer(transactions, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        except Exception as e:
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
                return JsonResponse({"error": "Client not found."}, status=404)
            if not client.IB_status:
                return JsonResponse({"error": "Client is not an IB partner."}, status=400)

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

            return JsonResponse({"success": "IB status disabled successfully."}, status=200)

        except Exception as e:
            
            return JsonResponse({"error": str(e)}, status=500)

class IBClientsListView(APIView):
    """
    API View to fetch clients grouped by levels for a specific IB user.
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, user_id):
        try:
            
            ib_user = CustomUser.objects.get(user_id=user_id, IB_status=True)

            
            level1_clients = ib_user.get_clients_by_level(1)
            level2_clients = ib_user.get_clients_by_level(2)
            level3_clients = ib_user.get_clients_by_level(3)

            
            level1_data = [
                {"user_id": client.user_id, "name": client.username, "email": client.email}
                for client in level1_clients
            ]
            level2_data = [
                {"user_id": client.user_id, "name": client.username, "email": client.email}
                for client in level2_clients
            ]
            level3_data = [
                {"user_id": client.user_id, "name": client.username, "email": client.email}
                for client in level3_clients
            ]

            
            data = {
                "level1": level1_data,
                "level2": level2_data,
                "level3": level3_data,
            }
            return Response(data, status=200)

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

