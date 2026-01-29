from adminPanel.mt5.services import MT5ManagerActions
from django.db.models import Q, CharField, TextField
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from adminPanel.permissions import *
from rest_framework.response import Response
from rest_framework.views import APIView
from adminPanel.models import *
from adminPanel.serializers import *
from adminPanel.permissions import *
from adminPanel.EmailSender import EmailSender
from .views import generate_password, get_client_ip, send_deposit_email, send_withdrawal_email, logger
from rest_framework.pagination import PageNumberPagination
from django.middleware.csrf import get_token
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def user_completed_transactions(request, user_id):
    try:
        user = CustomUser.objects.get(user_id=user_id)
        transactions = Transaction.objects.filter(user=user).exclude(status='pending')
        serializer = TransactionSerializer(transactions, many=True)
        return Response({'transactions': serializer.data}, status=200)
    except Transaction.DoesNotExist:
        return Response({'error': 'No completed transactions found for this user.'}, status=404)
    except Exception as e:
        return Response({'error': str(e)}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_pending_transactions(request, user_id):
    try:
        transactions = Transaction.objects.filter(user__user_id=user_id, status='pending').exclude(source="CheesePay")
        serializer = TransactionSerializer(transactions, many=True)
        return Response({'transactions': serializer.data}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': 'Could not retrieve pending transactions', 'details': str(e)},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def user_trade_account_details(request, user_id):
    try:
        
        user = CustomUser.objects.get(user_id=user_id)
        accounts = TradingAccount.objects.filter(user=user).exclude(account_type = 'prop')
        
        
        serializer = TradingAccountSerializer(accounts, many=True)
        logger.info(f"Accounts retrieved for user ID {user_id}: {serializer.data}")
        return Response({"accounts": serializer.data}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error retrieving trading accounts for user ID {user_id}: {str(e)}")
        return Response({"error": "An error occurred while retrieving account details"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    
@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def create_demo_account_view(request):
    user_id = request.data.get('userId')
    account_name = request.data.get('accountName', "")
    leverage = request.data.get('leverage', "100").split(":")[-1]
    # Handle balance - use client specified amount or default to $10,000
    balance = request.data.get('balance')
    if balance is None or balance == '':
        balance = 10000.00  # Default balance
    else:
        try:
            balance = float(balance)
            # Validate balance range
            if balance < 100:
                return Response({'error': 'Minimum balance is $100'}, status=status.HTTP_400_BAD_REQUEST)
            if balance > 1000000:
                return Response({'error': 'Maximum balance is $1,000,000'}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({'error': 'Invalid balance amount'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Get custom passwords from request (optional)
    master_password = request.data.get('masterPassword')
    investor_password = request.data.get('investorPassword')

    try:
        user = CustomUser.objects.get(user_id=user_id)
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

    if not account_name:
        account_name = f"{user.username} - Demo"

    # Get demo group with fallback options
    try:
        groupName = TradingAccountGroup.objects.latest('created_at').demo_account_group
        if not groupName:
            # If demo_account_group is empty, use a fallback
            groupName = "demo"
    except TradingAccountGroup.DoesNotExist:
        # If no TradingAccountGroup exists, use fallback demo group
        groupName = "demo"
    


    # Validate custom passwords if provided
    def validate_mt5_password(password, password_type="Password"):
        """Validate password meets MT5 requirements based on actual testing"""
        if not password:
            return True, ""  # None/empty passwords are OK, will be auto-generated
            
        # MT5 password requirements (based on successful test: Test_123, Pass_456)
        if len(password) < 6:
            return False, f"{password_type} must be at least 6 characters long"
        
        if len(password) > 12:
            return False, f"{password_type} should be no more than 12 characters long for MT5 compatibility"
            
        # Check for required character types
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        
        if not (has_upper and has_lower and has_digit):
            return False, f"{password_type} must contain at least one uppercase letter, one lowercase letter, and one digit"
        
        # Check for forbidden characters that MT5 doesn't accept
        forbidden_chars = '"\'`<>&|;(){}[]!@#$%^*()+='
        if any(char in forbidden_chars for char in password):
            return False, f"{password_type} contains forbidden characters. Only letters, digits, and underscore (_) are allowed"
        
        # Recommend underscore format based on working examples    
        if not ('_' in password or password.isalnum()):
            return False, f"{password_type} should use underscore format (e.g., Test_123) for best MT5 compatibility"
            
        return True, ""

    # Validate master password if provided
    if master_password:
        is_valid, error_msg = validate_mt5_password(master_password, "Master password")
        if not is_valid:
            return Response({
                'error': 'Invalid master password format',
                'details': error_msg
            }, status=status.HTTP_400_BAD_REQUEST)
    
    # Validate investor password if provided  
    if investor_password:
        is_valid, error_msg = validate_mt5_password(investor_password, "Investor password")
        if not is_valid:
            return Response({
                'error': 'Invalid investor password format', 
                'details': error_msg
            }, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Let MT5 service handle password generation for compatibility
        mt5action = MT5ManagerActions()
        
        # Check if MT5 manager is connected and has permissions
        if not mt5action.manager:
            if mt5action.connection_error:
                logger.error(f"MT5 Manager not connected: {mt5action.connection_error}")
                return Response({
                    'error': 'MT5 service is currently unavailable. Please try again later or contact support.',
                    'details': 'MT5 connection error'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            else:
                logger.error("MT5 Manager not connected: Unknown error")
                return Response({
                    'error': 'MT5 service is currently unavailable. Please try again later or contact support.',
                    'details': 'MT5 manager not available'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        
        # Use the working create_account method with custom or auto-generated passwords
        try:
            account_result = mt5action.create_account(
                name=f"{user.first_name} {user.last_name}".strip(),
                email=user.email,
                phone=user.phone_number,
                group=groupName,
                leverage=int(leverage),
                password=master_password,  # Use custom password or None for auto-generation
                investor_password=investor_password,  # Use custom password or None for auto-generation
                account_type='demo'
            )
        except Exception as e:
            error_message = str(e)
            logger.error(f"Demo account creation error: {error_message}")
            
            # Check for specific permission error
            if "MT_RET_ERR_PERMISSIONS" in error_message:
                return Response({
                    'error': f'Failed to create demo account: {error_message}. Please try again or contact support.',
                    'details': 'MT5 manager permissions issue - contact administrator'
                }, status=status.HTTP_403_FORBIDDEN)
            else:
                return Response({
                    'error': f'Failed to create demo account: {error_message}',
                    'details': 'MT5 service error'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        if not account_result:
            logger.error(f"Failed to create MT5 demo account for user {user.username} in group {groupName}")
            return Response({
                'error': 'Failed to create demo account in MT5. This may be due to insufficient MT5 manager permissions or server issues.',
                'details': 'Please contact support if this issue persists.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Extract the login ID and passwords from the result
        demoid = account_result.get('login')
        masterpass = account_result.get('master_password')
        invpass = account_result.get('investor_password')
        
        if demoid:
            demo_account = DemoAccount.objects.create(
                user=user,
                account_name=account_name,
                leverage=leverage,
                balance=balance,
                account_id=demoid,
            )

            if not mt5action.deposit_funds(demoid, round(float(balance), 2), "Demo Deposit"):
                demo_account.delete()
                return Response({'error': 'Failed to deposit funds into the demo account'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Send demo account creation email
            try:
                email_sent = EmailSender.send_demo_account_creation(
                    user_email=user.email,
                    username=user.username,
                    account_id=demoid,
                    master_password=masterpass,
                    investor_password=invpass,
                    balance=balance,
                    leverage=leverage
                )
                if email_sent:
                    pass
                else:
                    logger.warning(f"Failed to send demo account creation email to {user.email}")
            except Exception as e:
                logger.error(f"Error sending demo account creation email to {user.email}: {str(e)}")
                # Don't fail the entire operation if email fails

            return Response({
                'message': 'Demo account created successfully!',
                'account': CreateDemoAccountSerializer(demo_account).data
            }, status=status.HTTP_201_CREATED)
        else:
            logger.error(f"Failed to create MT5 demo account for user {user.username} in group {groupName}")
            return Response({
                'error': 'Failed to create demo account in MT5. This may be due to insufficient MT5 manager permissions or server issues.',
                'details': 'Please contact support if this issue persists.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except Exception as e:
        logger.error(f"Error creating demo account for user {user.username}: {str(e)}")
        
        # Check if it's a permissions error
        if 'MT_RET_ERR_PERMISSIONS' in str(e) or 'permission' in str(e).lower():
            return Response({
                'error': 'Demo account creation failed due to insufficient MT5 permissions.',
                'details': 'The MT5 manager account does not have permission to create new accounts. Please contact administrator.',
                'error_type': 'permissions'
            }, status=status.HTTP_403_FORBIDDEN)
        elif 'No free logins' in str(e):
            return Response({
                'error': 'Demo account creation failed: No free login slots available.',
                'details': 'The MT5 server has reached its maximum number of accounts. Please contact administrator.',
                'error_type': 'server_limit'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        elif 'login already exists' in str(e):
            return Response({
                'error': 'Demo account creation failed: Account already exists.',
                'details': 'An account with this login already exists. Please try again.',
                'error_type': 'duplicate'
            }, status=status.HTTP_409_CONFLICT)
        elif 'non current server' in str(e):
            return Response({
                'error': 'Demo account creation failed: Server configuration issue.',
                'details': 'Cannot create user for non-current server. Please contact administrator.',
                'error_type': 'server_config'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        
        return Response({
            'error': f'Error creating demo account: {str(e)}',
            'details': 'Please try again or contact support if the issue persists.',
            'error_type': 'general'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    
@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def create_trading_account_view(request):
    user_id = request.data.get('userId')
    account_name = request.data.get('accountName', "")
    leverage = request.data.get('leverage', "100").split(":")[-1]
    groupName = request.data.get('group')
    
    # Get custom passwords from request (optional)
    master_password = request.data.get('masterPassword')
    investor_password = request.data.get('investorPassword')

    try:
        user = CustomUser.objects.get(user_id=user_id)
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if not account_name:
        account_name = user.username
    
    if not groupName:
        return Response({'error': 'Trading group is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Validate custom passwords if provided (reuse validation function)
    def validate_mt5_password(password, password_type="Password"):
        """Validate password meets MT5 requirements based on actual testing"""
        if not password:
            return True, ""  # None/empty passwords are OK, will be auto-generated
            
        if len(password) < 6:
            return False, f"{password_type} must be at least 6 characters long"
        
        if len(password) > 12:
            return False, f"{password_type} should be no more than 12 characters long for MT5 compatibility"
            
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        
        if not (has_upper and has_lower and has_digit):
            return False, f"{password_type} must contain at least one uppercase letter, one lowercase letter, and one digit"
        
        forbidden_chars = '"\'`<>&|;(){}[]!@#$%^*()+='
        if any(char in forbidden_chars for char in password):
            return False, f"{password_type} contains forbidden characters. Only letters, digits, and underscore (_) are allowed"
        
        if not ('_' in password or password.isalnum()):
            return False, f"{password_type} should use underscore format (e.g., Test_123) for best MT5 compatibility"
            
        return True, ""

    # Validate passwords if provided
    if master_password:
        is_valid, error_msg = validate_mt5_password(master_password, "Master password")
        if not is_valid:
            return Response({
                'error': 'Invalid master password format',
                'details': error_msg
            }, status=status.HTTP_400_BAD_REQUEST)
    
    if investor_password:
        is_valid, error_msg = validate_mt5_password(investor_password, "Investor password")
        if not is_valid:
            return Response({
                'error': 'Invalid investor password format', 
                'details': error_msg
            }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        # Use the working create_account method with custom or auto-generated passwords
        account_result = MT5ManagerActions().create_account(
            name=f"{user.first_name} {user.last_name}".strip(),
            email=user.email,
            phone=user.phone_number,
            group=groupName,
            leverage=int(leverage),
            password=master_password,  # Use custom password or None for auto-generation
            investor_password=investor_password,  # Use custom password or None for auto-generation
            account_type='real'
        )
        
        # Extract the login ID and passwords from the result
        ac_id = account_result.get('login') if account_result else None
        masterpass = account_result.get('master_password') if account_result else None
        invpass = account_result.get('investor_password') if account_result else None
        
        if ac_id:
            trading_account = TradingAccount.objects.create(
                user=user,
                account_id=ac_id,
                account_name=account_name,
                account_type='standard',
                leverage=leverage,
                balance=0.00 
            )
            
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Created real account ID {ac_id} for user ID {user_id} with leverage {leverage} and balance {trading_account.balance}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=trading_account.id,
                related_object_type="Trading Account"
            )
            
            def send_trading_account_email(user, account_id, master_password, investor_password):
                """
                Sends an email to the user with their new trading account details.
                """
                subject = "Your New Trading Account Has Been Created"
                html_message = render_to_string("emails/new_account_creation.html", {
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

            send_trading_account_email(trading_account.user, trading_account.account_id, masterpass, invpass)
            
            # Create notification for the user
            from adminPanel.utils.notification_utils import create_account_creation_notification
            create_account_creation_notification(
                user=user,
                account_type='standard',
                account_number=ac_id,
                status='created'
            )
            
            return Response({
                'message': 'Real trading account created successfully!',
                'account': CreateTradingAccountSerializer(trading_account).data
            }, status=status.HTTP_201_CREATED)
        else:
            return Response({
                'error': 'Failed to create MT5 trading account. Please check MT5 server status and try again or contact support.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except Exception as e:
        logger.error(f"Error creating trading account for user {user.username}: {str(e)}")
        
        # Check if it's a permissions error
        if 'MT_RET_ERR_PERMISSIONS' in str(e) or 'permission' in str(e).lower():
            return Response({
                'error': 'Trading account creation failed due to insufficient MT5 permissions.',
                'details': 'The MT5 manager account does not have permission to create new accounts. Please contact administrator.',
                'error_type': 'permissions'
            }, status=status.HTTP_403_FORBIDDEN)
        elif 'No free logins' in str(e):
            return Response({
                'error': 'Trading account creation failed: No free login slots available.',
                'details': 'The MT5 server has reached its maximum number of accounts. Please contact administrator.',
                'error_type': 'server_limit'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        elif 'login already exists' in str(e):
            return Response({
                'error': 'Trading account creation failed: Account already exists.',
                'details': 'An account with this login already exists. Please try again.',
                'error_type': 'duplicate'
            }, status=status.HTTP_409_CONFLICT)
        elif 'non current server' in str(e):
            return Response({
                'error': 'Trading account creation failed: Server configuration issue.',
                'details': 'Cannot create user for non-current server. Please contact administrator.',
                'error_type': 'server_config'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        
        return Response({
            'error': f'Error creating trading account: {str(e)}',
            'details': 'Please try again or contact support if the issue persists.',
            'error_type': 'general'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    



@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def list_demo_accounts(request):
    """
    Fetch all demo accounts with pagination, sorting, and searching across all fields.
    """
    try:
        # Filter accounts based on role
        if request.user.manager_admin_status in ['Admin', 'Manager']:
            demo_accounts = DemoAccount.objects.all()
        else:
            demo_accounts = DemoAccount.objects.none()

        # Dynamic Searching (Across All Fields)
        search_query = request.query_params.get("search", "").strip()
        if search_query:
            search_filters = Q()
            search_fields = [field.name for field in DemoAccount._meta.fields if isinstance(field, (CharField, TextField))]

            # Add related user fields
            related_user_fields = ["user__username", "user__email", "user__country"]

            # Dynamically create OR search conditions
            for field in search_fields:
                search_filters |= Q(**{f"{field}__icontains": search_query})
            
            # Add user-related fields to search
            for field in related_user_fields:
                search_filters |= Q(**{f"{field}__icontains": search_query})

            demo_accounts = demo_accounts.filter(search_filters)

        # Sorting
        sort_by = request.query_params.get("sortBy", "created_at")
        sort_order = request.query_params.get("sortOrder", "desc")
        
        if sort_order == "desc":
            sort_by = f"-{sort_by}"
        
        demo_accounts = demo_accounts.order_by(sort_by)

        # Pagination
        paginator = PageNumberPagination()
        paginator.page_size = request.query_params.get("pageSize", 10)
        paginated_accounts = paginator.paginate_queryset(demo_accounts, request)
        
        serializer = DemoAccountSerializer(paginated_accounts, many=True)
        return paginator.get_paginated_response(serializer.data)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def demo_accounts_by_user(request, user_id):
    user = CustomUser.objects.get(user_id=user_id)
    demo_accounts = DemoAccount.objects.filter(user=user)
    serializer = DemoAccountSerializer(demo_accounts, many=True)
    return Response({'demoAccounts': serializer.data}, status=status.HTTP_200_OK)
    
class DepositView(APIView):
    """
    Enhanced DepositView with proper database and MT5 integration
    """
    # Use the custom BlacklistCheckingJWTAuthentication from settings instead of overriding
    # authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAdminOrManager]
    
    def options(self, request, *args, **kwargs):
        """Handle CORS preflight requests"""
        response = Response({
            "message": "OPTIONS request successful",
            "allowed_methods": ["GET", "POST", "OPTIONS"]
        })
        response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-CSRFToken'
        response['Allow'] = 'GET, POST, OPTIONS'
        return response
    
    def get(self, request, *args, **kwargs):
        """Return a list of deposit transactions (for admin panel)"""
        try:
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')
            qs = Transaction.objects.filter(transaction_type='deposit_trading')
            qs = qs.exclude(Q(source='CheesePay') & Q(status__in=['pending', 'failed']))
            if start_date:
                qs = qs.filter(created_at__date__gte=start_date)
            if end_date:
                qs = qs.filter(created_at__date__lte=end_date)
            qs = qs.order_by('-created_at')[:200]
            serializer = TransactionSerializer(qs, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    def post(self, request, *args, **kwargs):
        """Handle POST requests for deposits with full database and MT5 integration"""
        logger.info(f"Deposit request from user: {request.user.username} ({request.user.manager_admin_status})")
        
        # Extract and validate request data
        account_id = request.data.get('account_id')
        amount = request.data.get('amount')
        comment = request.data.get('comment', 'Admin deposit')
        transaction_type = request.data.get('transaction_type', 'deposit')
        
        # Validation
        if not account_id:
            return Response({
                "error": "account_id is required",
                "received_data": dict(request.data)
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not amount:
            return Response({
                "error": "amount is required",
                "received_data": dict(request.data)
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            amount = float(Decimal(amount))
            if amount <= 0:
                return Response({
                    "error": "amount must be greater than zero"
                }, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError, InvalidOperation):
            return Response({
                "error": "amount must be a valid number"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Find the trading account
            trading_account = TradingAccount.objects.get(account_id=account_id)
            logger.info(f"Found trading account: {trading_account.account_id} for user: {trading_account.user.username}")
            
            # Check permissions for managers
            if request.user.manager_admin_status == 'Manager':
                if getattr(trading_account.user, 'created_by', None) != request.user:
                    return Response({
                        "error": "You don't have permission to deposit to this account"
                    }, status=status.HTTP_403_FORBIDDEN)
            
            # Attempt MT5 deposit with fallback
            mt5_success = False
            mt5_error = None
            
            try:
                mt5_manager = MT5ManagerActions()
                logger.info(f"Attempting MT5 deposit: account={account_id}, amount={amount}")
                
                mt5_success = mt5_manager.deposit_funds(
                    login_id=int(account_id),
                    amount=float(amount),
                    comment=comment
                )
                
                if mt5_success:
                    # Update account balance from MT5
                    new_balance = mt5_manager.get_balance(int(account_id))
                    if new_balance is not None:
                        trading_account.balance = Decimal(str(new_balance))
                        trading_account.save()
                        logger.info(f"Updated account balance from MT5: {new_balance}")
                    else:
                        # If we can't get the new balance, just add the amount
                        trading_account.balance += Decimal(str(amount))
                        trading_account.save()
                        logger.warning(f"Could not fetch new balance from MT5, estimated balance: {trading_account.balance}")
                else:
                    logger.error(f"MT5 deposit failed for account {account_id}")
                    mt5_error = "MT5 deposit operation failed"
                    
            except Exception as mt5_exception:
                logger.error(f"MT5 integration error: {str(mt5_exception)}")
                mt5_error = str(mt5_exception)
                mt5_success = False
            
            # Fallback: Update balance directly in database if MT5 fails
            if not mt5_success:
                logger.warning(f"MT5 failed, updating balance directly in database. Error: {mt5_error}")
                trading_account.balance += Decimal(str(amount))
                trading_account.save()
                logger.info(f"Fallback: Updated account balance to {trading_account.balance}")
            
            # Create transaction record regardless of MT5 status
            transaction = Transaction.objects.create(
                user=trading_account.user,
                trading_account=trading_account,
                transaction_type='deposit_trading',
                amount=Decimal(str(amount)),
                description=comment + (" (MT5 Failed - Database Only)" if not mt5_success else ""),
                status='approved',
                approved_by=request.user,
                source="Admin Operation" + (" - Fallback Mode" if not mt5_success else ""),
                approved_at=timezone.now()
            )
                
            # Create activity log
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Deposited ${amount} to account {account_id}. New balance: ${trading_account.balance}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=account_id,
                related_object_type="TradingAccount"
            )
            
            # Send notification email
            try:
                send_deposit_email(trading_account.user, transaction)
                logger.info("Deposit notification email sent successfully")
            except Exception as email_error:
                logger.warning(f"Failed to send deposit email: {email_error}")
                
            return Response({
                "message": "Deposit processed successfully" + (" (Fallback Mode - MT5 Integration Failed)" if not mt5_success else ""),
                "transaction_id": transaction.id,
                "account_id": account_id,
                "amount": float(amount),
                "new_balance": float(trading_account.balance),
                "comment": comment,
                "status": "approved",
                "created_at": transaction.created_at.isoformat(),
                "mt5_integration": mt5_success,
                "mt5_error": mt5_error if not mt5_success else None,
                "fallback_mode": not mt5_success
            }, status=status.HTTP_201_CREATED)
        
        except TradingAccount.DoesNotExist:
            logger.error(f"Trading account not found: {account_id}")
            return Response({
                "error": f"Trading account {account_id} not found"
            }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            logger.error(f"Deposit processing error: {str(e)}", exc_info=True)
            return Response({
                "error": f"Internal server error: {str(e)}",
                "account_id": account_id if 'account_id' in locals() else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class WithdrawView(APIView):
    """Enhanced WithdrawView with proper database and MT5 integration"""
    # Use the custom BlacklistCheckingJWTAuthentication from settings instead of overriding
    # authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAdminOrManager]
    
    def options(self, request, *args, **kwargs):
        """Handle CORS preflight requests"""
        response = Response({
            "message": "OPTIONS request successful",
            "allowed_methods": ["GET", "POST", "OPTIONS"]
        })
        response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-CSRFToken'
        response['Allow'] = 'GET, POST, OPTIONS'
        return response
    
    def get(self, request, *args, **kwargs):
        """Return a list of withdrawal transactions (for admin panel)"""
        try:
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')
            qs = Transaction.objects.filter(
                Q(transaction_type='withdraw_trading') | Q(transaction_type='commission_withdrawal')
            )
            if start_date:
                qs = qs.filter(created_at__date__gte=start_date)
            if end_date:
                qs = qs.filter(created_at__date__lte=end_date)
            qs = qs.order_by('-created_at')[:200]
            serializer = TransactionSerializer(qs, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=500)
    
    def post(self, request):
        """Handle withdrawal requests with full database and MT5 integration"""
        logger.info(f"Withdrawal request from user: {request.user.username} ({request.user.manager_admin_status})")
        
        account_id = request.data.get('account_id') or request.data.get('accountId')
        amount = request.data.get('amount')
        comment = request.data.get('comment', 'Admin withdrawal')
        
        # Validation
        if not account_id or not amount:
            return Response({
                "error": "Account ID and amount are required.",
                "received_data": dict(request.data)
            }, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            amount = float(Decimal(amount))
            if amount <= 0:
                return Response({
                    "error": "Amount must be greater than zero."
                }, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError, InvalidOperation):
            return Response({
                "error": "Invalid amount format."
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Find the trading account
            trading_account = TradingAccount.objects.get(account_id=account_id)
            logger.info(f"Found trading account: {trading_account.account_id} for user: {trading_account.user.username}")
            
            # Check permissions for managers
            if request.user.manager_admin_status == 'Manager':
                if getattr(trading_account.user, 'created_by', None) != request.user:
                    return Response({
                        "error": "You don't have permission to withdraw from this account"
                    }, status=status.HTTP_403_FORBIDDEN)
            
            # Check if account has sufficient balance
            current_balance = float(trading_account.balance)
            if current_balance < amount:
                return Response({
                    "error": f"Insufficient balance. Current balance: ${current_balance:.2f}, Requested: ${amount:.2f}"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Perform MT5 withdrawal
            mt5_manager = MT5ManagerActions()
            logger.info(f"Attempting MT5 withdrawal: account={account_id}, amount={amount}")
            
            mt5_success = mt5_manager.withdraw_funds(
                login_id=int(account_id),
                amount=float(amount),
                comment=comment
            )
            
            if mt5_success:
                # Update account balance from MT5
                new_balance = mt5_manager.get_balance(int(account_id))
                if new_balance is not None:
                    trading_account.balance = Decimal(str(new_balance))
                    trading_account.save()
                    logger.info(f"Updated account balance to: {new_balance}")
                else:
                    # If we can't get the new balance, subtract the amount
                    trading_account.balance -= Decimal(str(amount))
                    trading_account.save()
                    logger.warning(f"Could not fetch new balance from MT5, estimated balance: {trading_account.balance}")
                
                # Create transaction record
                transaction = Transaction.objects.create(
                    user=trading_account.user,
                    trading_account=trading_account,
                    transaction_type='withdraw_trading',
                    amount=Decimal(str(amount)),
                    description=comment,
                    status='approved',
                    approved_by=request.user,
                    source="Admin Operation",
                    approved_at=timezone.now()
                )
                
                # Create activity log
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Withdrew ${amount} from account {account_id}. New balance: ${trading_account.balance}",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=transaction.id,
                    related_object_type="Transaction"
                )
                
                # Send notification email
                try:
                    send_withdrawal_email(trading_account.user, transaction)
                    logger.info("Withdrawal notification email sent successfully")
                except Exception as email_error:
                    logger.warning(f"Failed to send withdrawal email: {email_error}")
                
                logger.info(f"Withdrawal completed successfully: transaction_id={transaction.id}")
                
                return Response({
                    "message": "Withdrawal successful.",
                    "transaction_id": transaction.id,
                    "account_id": account_id,
                    "amount": float(amount),
                    "new_balance": float(trading_account.balance),
                    "comment": comment,
                    "status": "approved",
                    "created_at": transaction.created_at.isoformat(),
                    "mt5_integration": True
                }, status=status.HTTP_201_CREATED)
                
            else:
                logger.error(f"MT5 withdrawal failed for account {account_id}")
                return Response({
                    "error": "Withdrawal failed due to MT5 system error.",
                    "account_id": account_id,
                    "amount": amount,
                    "mt5_error": True
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except TradingAccount.DoesNotExist:
            logger.error(f"Trading account not found: {account_id}")
            return Response({
                "error": f"Trading account {account_id} not found."
            }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            logger.error(f"Withdrawal processing error: {str(e)}", exc_info=True)
            return Response({
                "error": f"Internal server error: {str(e)}",
                "account_id": account_id if 'account_id' in locals() else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
def ib_clients_deposit_transactions(request):
    """
    Get deposit transactions only for clients under the authenticated IB parent.
    This endpoint filters transactions based on the client's parent_ib field.
    
    Query Parameters:
    - page: Page number (default: 1)
    - page_size: Number of records per page (default: 50)
    - start_date: Filter by start date (YYYY-MM-DD format)
    - end_date: Filter by end date (YYYY-MM-DD format)
    """
    permission_classes = [IsAdminOrManager]
    try:
        # Get the authenticated user
        authenticated_user = request.user
        
        # Check if the user is an IB (has clients)
        try:
            ib_clients = authenticated_user.clients.all()
            if not ib_clients.exists():
                return Response({
                    "data": [],
                    "total": 0,
                    "message": "You don't have IB client access"
                }, status=status.HTTP_200_OK)
        except (AttributeError, Exception):
            return Response({
                "data": [],
                "total": 0,
                "message": "You don't have IB client access"
            }, status=status.HTTP_200_OK)
        
        # Get all clients under this IB parent
        ib_clients = authenticated_user.clients.all()
        client_ids = ib_clients.values_list('id', flat=True)
        
        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        
        # Query transactions for all clients under this IB
        qs = Transaction.objects.filter(
            user_id__in=client_ids,
            transaction_type='deposit_trading'
        )
        qs = qs.exclude(Q(source='CheesePay') & Q(status__in=['pending', 'failed']))
        
        # Apply date filters if provided
        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)
        
        # Order by created date (newest first)
        qs = qs.order_by('-created_at')
        
        # Get total count before pagination
        total_count = qs.count()
        
        # Apply pagination
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_qs = qs[start_idx:end_idx]
        
        # Serialize the results
        serializer = TransactionSerializer(paginated_qs, many=True)
        
        return Response({
            "data": serializer.data,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size,
            "clients_count": client_ids.count(),
            "ib_username": authenticated_user.username
        }, status=status.HTTP_200_OK)
        
    except ValueError as e:
        return Response({
            "error": "Invalid pagination parameters",
            "details": str(e)
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error fetching IB client deposits: {str(e)}", exc_info=True)
        return Response({
            "error": "Internal server error",
            "details": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def ib_clients_withdrawal_transactions(request):
    """
    Get withdrawal transactions only for clients under the authenticated IB parent.
    This endpoint filters transactions based on the client's parent_ib field.
    
    Query Parameters:
    - page: Page number (default: 1)
    - page_size: Number of records per page (default: 50)
    - start_date: Filter by start date (YYYY-MM-DD format)
    - end_date: Filter by end date (YYYY-MM-DD format)
    """
    permission_classes = [IsAdminOrManager]
    try:
        # Get the authenticated user
        authenticated_user = request.user
        
        # Check if the user is an IB (has clients)
        if not hasattr(authenticated_user, 'clients') or authenticated_user.clients.count() == 0:
            return Response({
                "data": [],
                "total": 0,
                "message": "You don't have IB client access"
            }, status=status.HTTP_200_OK)
        
        # Get all clients under this IB parent
        ib_clients = authenticated_user.clients.all()
        client_ids = ib_clients.values_list('id', flat=True)
        
        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        
        # Query transactions for all clients under this IB
        qs = Transaction.objects.filter(
            user_id__in=client_ids,
            transaction_type='withdraw_trading'
        )
        
        # Apply date filters if provided
        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)
        
        # Order by created date (newest first)
        qs = qs.order_by('-created_at')
        
        # Get total count before pagination
        total_count = qs.count()
        
        # Apply pagination
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_qs = qs[start_idx:end_idx]
        
        # Serialize the results
        serializer = TransactionSerializer(paginated_qs, many=True)
        
        return Response({
            "data": serializer.data,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size,
            "clients_count": client_ids.count(),
            "ib_username": authenticated_user.username
        }, status=status.HTTP_200_OK)
        
    except ValueError as e:
        return Response({
            "error": "Invalid pagination parameters",
            "details": str(e)
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error fetching IB client withdrawals: {str(e)}", exc_info=True)
        return Response({
            "error": "Internal server error",
            "details": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def ib_clients_internal_transfer_transactions(request):
    """
    Get internal transfer transactions only for clients under the authenticated IB parent.
    This endpoint filters transactions based on the client's parent_ib field.
    
    Query Parameters:
    - page: Page number (default: 1)
    - page_size: Number of records per page (default: 50)
    - start_date: Filter by start date (YYYY-MM-DD format)
    - end_date: Filter by end date (YYYY-MM-DD format)
    """
    
    permission_classes = [IsAdminOrManager]
    try:
        # Get the authenticated user
        authenticated_user = request.user
        
        # Check if the user is an IB (has clients)
        if not hasattr(authenticated_user, 'clients') or authenticated_user.clients.count() == 0:
            return Response({
                "data": [],
                "total": 0,
                "message": "You don't have IB client access"
            }, status=status.HTTP_200_OK)
        
        # Get all clients under this IB parent
        ib_clients = authenticated_user.clients.all()
        client_ids = ib_clients.values_list('id', flat=True)
        
        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        
        # Query transactions for all clients under this IB
        qs = Transaction.objects.filter(
            user_id__in=client_ids,
            transaction_type='internal_transfer'
        )
        
        # Apply date filters if provided
        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)
        
        # Order by created date (newest first)
        qs = qs.order_by('-created_at')
        
        # Get total count before pagination
        total_count = qs.count()
        
        # Apply pagination
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_qs = qs[start_idx:end_idx]
        
        # Serialize the results
        serializer = TransactionSerializer(paginated_qs, many=True)
        
        return Response({
            "data": serializer.data,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size,
            "clients_count": client_ids.count(),
            "ib_username": authenticated_user.username
        }, status=status.HTTP_200_OK)
        
    except ValueError as e:
        return Response({
            "error": "Invalid pagination parameters",
            "details": str(e)
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error fetching IB client internal transfers: {str(e)}", exc_info=True)
        return Response({
            "error": "Internal server error",
            "details": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class InternalTransferView(APIView):
    # Use the custom BlacklistCheckingJWTAuthentication from settings instead of overriding
    # authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAdminOrManager]
    
    def get(self, request, *args, **kwargs):
        """Return a list of internal transfer transactions (for admin panel)"""
        try:
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')
            qs = Transaction.objects.filter(transaction_type='internal_transfer')
            if start_date:
                qs = qs.filter(created_at__date__gte=start_date)
            if end_date:
                qs = qs.filter(created_at__date__lte=end_date)
            qs = qs.order_by('-created_at')[:200]
            serializer = TransactionSerializer(qs, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    def post(self, request):
        from_account_id = request.data['fromAccountId']
        to_account_id = request.data['toAccountId']
        amount = request.data['amount']
        comment = request.data['comment']
        if from_account_id == to_account_id:
            return Response({"error": "From and To accounts must be different"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from_account = TradingAccount.objects.exclude(account_type='prop').get(account_id=from_account_id)
            to_account = TradingAccount.objects.exclude(account_type='prop').get(account_id=to_account_id)
            if from_account.balance < float(amount):
                return Response({"error": "Insufficient balance in the from account"}, status=status.HTTP_400_BAD_REQUEST)

            if from_account.user != to_account.user:
                return Response({"error": "Different User - Not allowed"}, status=status.HTTP_400_BAD_REQUEST)
            
            mt5action = MT5ManagerActions()
            if mt5action.internal_transfer(int(to_account_id), int(from_account_id), round(float(amount),2)):
                try:
                    transaction = Transaction.objects.create(
                        user=from_account.user,
                        from_account=from_account,
                        to_account=to_account,
                        transaction_type='internal_transfer',
                        amount=amount,
                        status='completed'  
                    )
                    ActivityLog.objects.create(
                        user=request.user,
                        activity=(
                            f"Transferred {amount} from account ID {from_account_id} "
                            f"to account ID {to_account_id}. New balances: "
                            f"From Account: {from_account.balance}, To Account: {to_account.balance}"
                        ),
                        ip_address=get_client_ip(request),
                        endpoint=request.path,
                        activity_type="create",
                        activity_category="management",
                        user_agent=request.META.get("HTTP_USER_AGENT", ""),
                        timestamp=timezone.now(),
                        related_object_id=transaction.id,
                        related_object_type="Transaction"
                    )
                    from_account.balance -= Decimal(amount)
                    to_account.balance += Decimal(amount)
                    from_account.save()
                    to_account.save()

                    return Response({
                        "message": "Internal transfer successful!",
                        "transaction_id": transaction.id,
                        "from_account_balance": from_account.balance,
                        "to_account_balance": to_account.balance,
                    }, status=status.HTTP_201_CREATED)

                except Exception as e:
                    mt5action.internal_transfer(from_account_id, to_account_id, round(float(amount),2))
                    return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                return Response({"error": "MT5 Error - Internal Transfer failed "}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except CustomUser.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        except TradingAccount.DoesNotExist:
            return Response({"error": "Account not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Simple test deposit view for debugging
class TestDepositView(APIView):
    """
    Simple test deposit view to debug the 405 Method Not Allowed issue
    """
    authentication_classes = []  # No authentication for testing
    permission_classes = []      # No permissions for testing
    
    def post(self, request):
        return Response({
            "message": "Test deposit endpoint working!",
            "method": request.method,
            "data": request.data
        }, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def update_demo_account_view(request):
    """Update demo account balance or leverage"""
    account_id = request.data.get('account_id')
    balance = request.data.get('balance')
    leverage = request.data.get('leverage')
    
    if not account_id:
        return Response({'error': 'Account ID is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        # Get the demo account
        demo_account = DemoAccount.objects.get(account_id=account_id, user=request.user)
    except DemoAccount.DoesNotExist:
        return Response({'error': 'Demo account not found'}, status=status.HTTP_404_NOT_FOUND)
    
    try:
        mt5action = MT5ManagerActions()
        
        # Check if MT5 manager is connected
        if not mt5action.manager:
            return Response({
                'error': 'MT5 service is currently unavailable. Please try again later.',
                'details': 'MT5 connection error'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        
        update_message = []
        
        # Update balance if provided
        if balance is not None:
            try:
                balance = float(balance)
                if balance < 0:
                    return Response({'error': 'Balance cannot be negative'}, status=status.HTTP_400_BAD_REQUEST)
                
                # Update balance in MT5
                if mt5action.set_balance(int(account_id), balance, "Balance update"):
                    # Update balance in database
                    demo_account.balance = balance
                    update_message.append(f'Balance updated to ${balance:,.2f}')
                    logger.info(f"Demo account {account_id} balance updated to {balance}")
                else:
                    return Response({'error': 'Failed to update balance in MT5'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except (ValueError, TypeError):
                return Response({'error': 'Invalid balance amount'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Update leverage if provided
        if leverage is not None:
            try:
                leverage = int(leverage)
                if leverage <= 0:
                    return Response({'error': 'Leverage must be positive'}, status=status.HTTP_400_BAD_REQUEST)
                
                # Update leverage in MT5
                if mt5action.change_leverage(int(account_id), leverage):
                    # Update leverage in database
                    demo_account.leverage = str(leverage)
                    update_message.append(f'Leverage updated to 1:{leverage}')
                    logger.info(f"Demo account {account_id} leverage updated to {leverage}")
                else:
                    return Response({'error': 'Failed to update leverage in MT5'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except (ValueError, TypeError):
                return Response({'error': 'Invalid leverage value'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Save changes to database
        demo_account.save()
        
        return Response({
            'success': True,
            'message': '; '.join(update_message),
            'account_id': account_id,
            'new_balance': str(demo_account.balance),
            'new_leverage': demo_account.leverage
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error updating demo account {account_id}: {str(e)}")
        return Response({
            'error': f'Failed to update demo account: {str(e)}',
            'details': 'MT5 service error'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def options(self, request, *args, **kwargs):
        response = Response()
        response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response

@require_http_methods(["GET"])
@ensure_csrf_cookie
@api_view(['GET'])
@permission_classes([AllowAny])
def csrf_token_view(request):
    """
    Simple endpoint to provide CSRF token for frontend
    """
    return JsonResponse({
        'csrfToken': get_token(request),
        'message': 'CSRF token provided'
    })

