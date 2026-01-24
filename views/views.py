from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.http import JsonResponse
from adminPanel.permissions import IsAuthenticatedUser, IsAdmin, IsAdminOrManager
from rest_framework.permissions import AllowAny
from rest_framework.pagination import PageNumberPagination
from adminPanel.models import CustomUser
from django.db.models import Q
from adminPanel.serializers import UserSerializer
import random

# API endpoint for demo accounts table
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def demo_accounts_api_view(request):
    try:
        user = request.user
        # If unauthenticated, show all demo accounts
        if not hasattr(user, 'is_authenticated') or not user.is_authenticated:
            demo_accounts_queryset = DemoAccount.objects.select_related('user').all()
        else:
            user_role = getattr(user, 'role', None)
            user_status = getattr(user, 'manager_admin_status', None)
            is_superuser = getattr(user, 'is_superuser', False)
            is_admin = (
                is_superuser or 
                user_role == 'admin' or
                (user_status and 'Admin' in user_status)
            )
            is_manager = (
                user_role == 'manager' or
                (user_status and 'Manager' in user_status)
            )
            if is_admin:
                demo_accounts_queryset = DemoAccount.objects.select_related('user').all()
            elif is_manager:
                manager_clients = CustomUser.objects.filter(
                    Q(created_by=user) |
                    Q(parent_ib=user, parent_ib__role='manager')
                )
                demo_accounts_queryset = DemoAccount.objects.select_related('user').filter(user__in=manager_clients)
            else:
                demo_accounts_queryset = DemoAccount.objects.none()
        # Apply server-side search filter if provided
        search_q = request.GET.get('search', '').strip()
        if search_q:
            demo_accounts_queryset = demo_accounts_queryset.filter(
                Q(user__first_name__icontains=search_q) |
                Q(user__last_name__icontains=search_q) |
                Q(user__email__icontains=search_q) |
                Q(account_id__icontains=search_q) |
                Q(user__username__icontains=search_q) |
                Q(user__phone_number__icontains=search_q)
            )

        # Optional filter: filter by user id (supports custom user_id or primary key)
        user_id_param = request.GET.get('user_id')
        if user_id_param:
            # Try to filter by custom user_id first, then fallback to PK
            try:
                demo_accounts_queryset = demo_accounts_queryset.filter(
                    Q(user__user_id=user_id_param) | Q(user__id=int(user_id_param))
                )
            except ValueError:
                # non-numeric user_id: filter only by user__user_id
                demo_accounts_queryset = demo_accounts_queryset.filter(user__user_id=user_id_param)

        demo_accounts = []
        for acc in demo_accounts_queryset:
            demo_accounts.append({
                'user_id': getattr(acc.user, 'user_id', getattr(acc.user, 'id', None)),
                'id': acc.id,
                'name': f"{acc.user.first_name} {acc.user.last_name}".strip(),
                'email': acc.user.email,
                'phone': acc.user.phone_number,
                'account_id': acc.account_id,
                'leverage': acc.leverage if acc.leverage else '0',
                'balance': float(acc.balance) if hasattr(acc, 'balance') else 0.0,
                'registered_date': acc.created_at.strftime('%Y-%m-%d') if acc.created_at else '',
                'country': getattr(acc.user, 'country', ''),
                'is_active': acc.is_active,
            })
        return JsonResponse(demo_accounts, safe=False)
    except Exception as e:
        return Response(
            {"error": f"An unexpected error occurred: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


import random
from adminPanel.mt5.services import MT5ManagerActions
import string
import logging
from django.utils.timezone import now
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.conf import settings
from rest_framework.pagination import PageNumberPagination
from django.utils import timezone
from django.contrib.auth import authenticate
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from adminPanel.models import TradingAccount

from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from rest_framework import status
from django.db.models import Q

from adminPanel.models import *
from adminPanel.serializers import *
from adminPanel.permissions import *

logger = logging.getLogger(__name__)

def generate_password(length=8):
    if length < 8:
        raise ValueError("Password length must be at least 8 characters.")
    
    
    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    special_chars = string.punctuation

    
    password = [
        random.choice(uppercase),
        random.choice(lowercase),
        random.choice(digits),
        random.choice(special_chars)
    ]

    
    all_chars = uppercase + lowercase + digits + special_chars
    password += random.choices(all_chars, k=length - len(password))

    
    random.shuffle(password)

    
    return ''.join(password)

def get_client_ip(request):
    """Get client IP address from request headers."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip

def send_deposit_email(user, transaction):
    subject = "Your Deposit Has Been Processed"
    html_message = render_to_string("emails/new_deposit.html", {
        "username": user.username,
        "account_id": transaction.trading_account.account_id,
        "deposit_amount": round(float(transaction.amount), 2),
        "transaction_id": transaction.id,
        "transaction_date": transaction.approved_at.strftime('%Y-%m-%d %H:%M:%S') if transaction.approved_at else "",
    })
    email = EmailMessage(
        subject=subject,
        body=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.content_subtype = "html"  
    email.send()

def send_withdrawal_email(user, transaction):
    subject = "Your Withdrawal Has Been Processed"
    html_message = render_to_string("emails/withdrawal.html", {
        "username": user.username,
        "account_id": transaction.trading_account.account_id,
        "withdrawal_amount": round(float(transaction.amount), 2),
        "transaction_id": transaction.id,
        "transaction_date": transaction.approved_at.strftime('%Y-%m-%d %H:%M:%S') if transaction.approved_at else "",
    })
    email = EmailMessage(
        subject=subject,
        body=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.content_subtype = "html"  
    email.send()

def send_ib_approval_email(user):
    """
    Sends an email to the user notifying them that their IB request has been approved.
    """
    subject = "Your IB Request Has Been Approved"
    html_message = render_to_string("emails/ib_approved.html", {
        "username": user.username,
    })
    email = EmailMessage(
        subject=subject,
        body=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.content_subtype = "html"  
    email.send()

@csrf_exempt
@api_view(['POST'])
@permission_classes([])
def login_view(request):
    email = request.data.get("email")
    password = request.data.get("password")
    if CustomUser.objects.get(email=email).manager_admin_status == "None":
        user = None
    else:
        user = authenticate(request, email=email, password=password)
    

    if user is not None:
        if getattr(user, 'manager_admin_status', None) != 'None':
            refresh = RefreshToken.for_user(user)
            try:
                refresh['aud'] = 'admin.vtindex'
                refresh['scope'] = 'admin:*'
                access = refresh.access_token
                access['aud'] = 'admin.vtindex'
                access['scope'] = 'admin:*'
            except Exception:
                pass
            return Response({
                "access": str(refresh.access_token),
                "refresh": str(refresh)
            }, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Access restricted. User does not have sufficient privileges."},
                            status=status.HTTP_403_FORBIDDEN)
    else:
        return Response({"error": "Invalid email or password"}, status=status.HTTP_401_UNAUTHORIZED)


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def validate_token_view(request):
    token = request.headers.get('Authorization', '').split('Bearer ')[-1]
    try:
        AccessToken(token)
        return Response({'detail': 'Token is valid'}, status=status.HTTP_200_OK)
    except Exception as e:
        
        return Response({'detail': 'Invalid or expired token'}, status=status.HTTP_401_UNAUTHORIZED)

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def logout_view(request):
    return Response({'detail': 'Logout successful'}, status=status.HTTP_200_OK)



@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def user_info_view(request):
    if request.user.is_authenticated:
        serializer = UserInfoSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)
    else:
        return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)
                    

@api_view(['POST'])
@permission_classes([IsAdmin])
def create_prop_trading_package(request):
    """
    Handle the creation of a new prop trading package.
    """
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



@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def package_list_view(request):
    """
    Retrieve the list of packages.
    """
    try:
        packages = Package.objects.all()
        serializer = PackageSerializer(packages, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def transaction_details(request, transaction_id):
    """
    Retrieve details of a specific transaction.
    """
    try:
        transaction = Transaction.objects.get(transaction_id=transaction_id)
        serializer = TransactionSerializer(transaction)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Transaction.DoesNotExist:
        return Response({"error": "Transaction not found."}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([IsAdmin])
def transaction_approve(request, transaction_id):
    """
    Approve a specific transaction and send an email confirmation.
    """
    try:
        transaction = Transaction.objects.get(id=transaction_id)
        if transaction.status in ['approved', 'completed']:
            return Response({"error": "Transaction already approved or completed."}, status=status.HTTP_400_BAD_REQUEST)
        mt5action = MT5ManagerActions()
        if transaction.transaction_type == "deposit_trading":
            tr = mt5action.deposit_funds(int(transaction.trading_account.account_id), round(float(transaction.amount), 2), transaction.source if transaction.source else "")
        elif transaction.transaction_type == "withdraw_trading":
            tr = mt5action.withdraw_funds(int(transaction.trading_account.account_id), round(float(transaction.amount), 2), transaction.source if transaction.source else "")
        elif transaction.transaction_type == "commission_withdrawal":
            if transaction.amount <= (transaction.user.total_earnings - transaction.user.total_commission_withdrawals):
                logger.info(f"[DEBUG] Attempting deposit for commission withdrawal: TX#{transaction.id} to account {transaction.trading_account.account_id}, amount={transaction.amount}")
                try:
                    tr = mt5action.deposit_funds(
                        int(transaction.trading_account.account_id),
                        round(float(transaction.amount), 2),
                        f"Commission withdrawal TX#{transaction.id}"
                    )
                    logger.info(f"[DEBUG] Deposit result for account {transaction.trading_account.account_id}: {tr}")
                except Exception as e:
                    logger.error(f"[ERROR] Exception during deposit for commission withdrawal TX#{transaction.id}: {e}")
                    return Response({"error": f"MT5 deposit exception: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                logger.warning(f"[WARNING] Insufficient commission balance for TX#{transaction.id}: requested={transaction.amount}, available={transaction.user.total_earnings - transaction.user.total_commission_withdrawals}")
                return Response({"error": "Insufficient commission balance."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"error": "Invalid transaction type."}, status=status.HTTP_400_BAD_REQUEST)
        if tr:
            if transaction.transaction_type == "deposit_trading":
                try:
                    send_deposit_email(transaction.trading_account.user, transaction)  
                except:
                    pass
            elif transaction.transaction_type == "withdraw_trading":
                try:
                    send_withdrawal_email(transaction.trading_account.user, transaction)  
                except:
                    pass
                
            transaction.approved_at = timezone.now()
            transaction.approved_by = request.user
            transaction.status = 'approved'
            transaction.save()
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Approved transaction {transaction.id} of type {transaction.transaction_type} for account {transaction.trading_account.account_id}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=transaction.id,
                related_object_type="Transaction"
            )
            del mt5action
            return Response({"message": "Transaction approved successfully."}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "MT5 error: "}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    except Transaction.DoesNotExist:
        return Response({"error": "Transaction not found."}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([IsAdmin])
def transaction_reject(request, transaction_id):
    """
    Reject a specific transaction.
    """
    try:
        transaction = Transaction.objects.get(id=transaction_id)
        if transaction.status in ['rejected', 'completed']:
            return Response({"error": "Transaction already rejected or completed."}, status=status.HTTP_400_BAD_REQUEST)
        
        transaction.status = 'rejected'
        transaction.approved_at = timezone.now()
        transaction.approved_by = request.user
        ActivityLog.objects.create(
            user=request.user,
            activity=f"Rejected transaction {transaction.id} for account {transaction.trading_account.account_id}",
            ip_address=get_client_ip(request),
            endpoint=request.path,
            activity_type="update",
            activity_category="management",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=transaction.id,
            related_object_type="Transaction"
        )

        transaction.save()
        return Response({"message": "Transaction rejected successfully."}, status=status.HTTP_200_OK)
    except Transaction.DoesNotExist:
        return Response({"error": "Transaction not found."}, status=status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                         
class WithdrawalHistoryPagination(PageNumberPagination):
    page_size = 10

@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def withdrawal_history(request, user_id):
    """
    Retrieve withdrawal history specific to 'commission_withdrawal' transactions for a given user.
    """
    try:
        
        withdrawals = Transaction.objects.filter(
            user_id=user_id,
            transaction_type="commission_withdrawal"
        ).order_by("-created_at")

        
        paginator = WithdrawalHistoryPagination()
        paginated_withdrawals = paginator.paginate_queryset(withdrawals, request)

        
        serializer = TransactionSerializer(paginated_withdrawals, many=True)
        return paginator.get_paginated_response(serializer.data)
    except Transaction.DoesNotExist:
        return Response({"error": "No commission withdrawals found for this user."}, status=status.HTTP_404_NOT_FOUND)
    
    
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_trading_accounts(request, user_id):
    """
    Retrieve trading accounts for a specific IB user.
    """
    try:
        accounts = TradingAccount.objects.filter(user__user_id=user_id, account_type='standard')
        serializer = TradingAccountSerializer(accounts, many=True)
        return Response({'accounts': serializer.data}, status=status.HTTP_200_OK)
    except TradingAccount.DoesNotExist:
        return Response({"error": "Trading accounts not found."}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def get_partner_profile(request, partner_id):
    """
    Retrieve profile information for a specific partner.
    """
    try:
        partner = CustomUser.objects.get(user_id=partner_id)
        # Handle commissioning_profile as integer (ID) or object
        profile_name = getattr(partner, "commission_profile_name", None)
        profile_id = None
        commissioning_profile = getattr(partner, "commissioning_profile", None)
        if commissioning_profile:
            # If it's an int, use as ID
            if isinstance(commissioning_profile, int):
                profile_id = commissioning_profile
            # If it's a model instance, use its id
            elif hasattr(commissioning_profile, "id"):
                profile_id = commissioning_profile.id
                if not profile_name:
                    profile_name = getattr(commissioning_profile, "name", "N/A")
        if not profile_name:
            profile_name = "N/A"
        return Response({
            "profileName": profile_name,
            "profileId": profile_id
        }, status=status.HTTP_200_OK)
    except CustomUser.DoesNotExist:
        return Response({"error": "Partner not found."}, status=status.HTTP_404_NOT_FOUND)

@api_view(['PATCH'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def update_partner_profile(request, partner_id):
    """
    Update profile information for a specific partner.
    """
    try:
        partner = CustomUser.objects.get(user_id=partner_id)
        serializer = UserSerializer(partner, data=request.data, partial=True)  
        if serializer.is_valid():
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Updated partner profile for user ID {partner_id}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=partner.id,
                related_object_type="IB Profile Change"
            )

            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except CustomUser.DoesNotExist:
        return Response({"error": "Partner not found."}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def commissioning_profiles_list(request):
    # Optimized logging - only log on DEBUG level
    if settings.DEBUG:
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"commissioning_profiles_list called - Method: {request.method}, User: {request.user}")
    
    try:
        if request.method == 'GET':
            try:
                profiles = CommissioningProfile.objects.all()
                from adminPanel.serializers import CommissioningProfileSerializerFor
                serializer = CommissioningProfileSerializerFor(profiles, many=True)
                
                # Only log count if debugging
                if settings.DEBUG:
                    logger.debug(f"Returning {len(profiles)} commissioning profiles")
                    
                return Response(serializer.data, status=status.HTTP_200_OK)
            except Exception as e:
                logger.error(f"Error fetching commissioning profiles: {e}")
                return Response({"error": f"Failed to fetch profiles: {str(e)}"}, status=500)
        
        elif request.method == 'POST':
            # Check authentication for POST requests
            if not request.user.is_authenticated:
                return Response(
                    {'error': 'Authentication required for creating profiles'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # Check if user is admin
            if not (request.user.is_staff or 
                    (hasattr(request.user, 'manager_admin_status') and 
                     request.user.manager_admin_status in ['Admin Level 1', 'Admin Level 2', 'Admin', 'Manager'])):
                return Response(
                    {'error': 'Admin access required'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            try:
                # Set default values for new commission system
                if 'use_percentage_based' not in request.data:
                    request.data['use_percentage_based'] = False  # Default to USD per lot
                
                serializer = CommissioningProfileSerializer(data=request.data)
                if serializer.is_valid():
                    profile = serializer.save()
                    
                    # Log the activity
                    commission_type = "Percentage-based" if profile.use_percentage_based else "USD per lot"
                    group_info = f" with {len(profile.approved_groups)} approved groups" if profile.approved_groups else " (all groups approved)"
                    
                    ActivityLog.objects.create(
                        user=request.user,
                        activity=f"Created a new commissioning profile: {profile.name} ({commission_type}){group_info}",  
                        ip_address=get_client_ip(request),
                        endpoint=request.path,
                        activity_type="create",
                        activity_category="management",
                        user_agent=request.META.get("HTTP_USER_AGENT", ""),
                        timestamp=timezone.now(),
                        related_object_id=profile.id,
                        related_object_type="CommissioningProfile"
                    )

                    # Return the created profile with all necessary fields
                    response_serializer = CommissioningProfileSerializerFor(profile)
                    return Response(response_serializer.data, status=status.HTTP_201_CREATED)
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.error(f"🔥 POST Error: {e}")
                print(f"🔥 POST Error: {e}")
                return Response({"error": f"POST failed: {str(e)}"}, status=500)
    except Exception as e:
        logger.error(f"🔥 OUTER Error: {e}")
        print(f"🔥 OUTER Error: {e}")
        return Response({"error": f"View failed: {str(e)}"}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def transaction_history(request, account_id):
    account = TradingAccount.objects.filter(account_id=account_id).first()
    if account:
        transactions = Transaction.objects.filter(trading_account=account).exclude(status = 'pending').order_by('-created_at')
        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data, status =200)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedUser])
def list_users(request):
    if request.method == 'GET':
        # ...existing GET logic...
        user_role = request.user.role
        user_status = request.user.manager_admin_status
        is_superuser = request.user.is_superuser
        is_admin = (
            is_superuser or 
            user_role == 'admin' or
            (user_status and 'Admin' in user_status)
        )
        is_manager = (
            user_role == 'manager' or
            (user_status and 'Manager' in user_status)
        )
        if is_admin:
            users = CustomUser.objects.all().order_by('-date_joined')
        elif is_manager:
            from django.db.models import Q
            manager_clients = CustomUser.objects.filter(
                Q(created_by=request.user) |
                Q(parent_ib=request.user, parent_ib__role='manager')
            )
            users = manager_clients.order_by('-date_joined')
        else:
            users = CustomUser.objects.none().order_by('id')

        # --- Add search functionality (includes phone and date matching) ---
        search_query = request.GET.get('search', '').strip()
        if search_query:
            from django.db.models import Q
            # Base Q for common text fields
            q = (
                Q(username__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(user_id__icontains=search_query) |
                Q(phone_number__icontains=search_query) |
                Q(date_joined__icontains=search_query)
            )

            # If the search looks like a date in common formats, also match date_joined date
            try:
                from datetime import datetime
                for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
                    try:
                        parsed = datetime.strptime(search_query, fmt).date()
                        q = q | Q(date_joined__date=parsed)
                        break
                    except ValueError:
                        continue
            except Exception:
                # ignore date parsing errors and continue with text matching
                pass

            users = users.filter(q)

        paginator = PageNumberPagination()
        paginator.page_size = int(request.GET.get('pageSize', 10))
        paginator.max_page_size = 100
        result_page = paginator.paginate_queryset(users, request)
        serializer = UserSerializer(result_page, many=True)
        return paginator.get_paginated_response(serializer.data)

    elif request.method == 'POST':
        data = request.data
        required_fields = ['name', 'email', 'password', 'phone', 'country', 'address']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            return Response({'error': f'Missing required fields: {", ".join(missing_fields)}'}, status=status.HTTP_400_BAD_REQUEST)

        email = data.get('email').lower().strip()
        if CustomUser.objects.filter(email=email).exists():
            return Response({'error': 'A user with this email already exists'}, status=status.HTTP_400_BAD_REQUEST)

        user = CustomUser.objects.create_user(
            email=email,
            password=data.get('password'),
            first_name=data.get('name', ''),
            last_name='',
            phone_number=data.get('phone', ''),
            country=data.get('country', ''),
            address=data.get('address', ''),
            is_active=True,
            created_by=request.user
        )
        user.verification_status = data.get('verification_status', 'pending')
        user.save()

        response_data = {
            'user_id': user.user_id,
            'email': user.email,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'phone_number': user.phone_number,
            'country': user.country,
            'address': user.address,
            'date_joined': user.date_joined.isoformat(),
            'is_active': user.is_active
        }

        return Response({'message': 'User created successfully', 'user': response_data}, status=status.HTTP_201_CREATED)
     
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def withdrawal_transactions(request):
    """
    Fetch Withdrawal Transactions with Pagination, Sorting, and Searching.
    """
    try:
        user = request.user
        search_query = request.GET.get('search', '')  # Search query
        sort_by = request.GET.get('sortBy', 'created_at')  # Default sorting field
        sort_order = request.GET.get('sortOrder', 'desc')  # Default sort order
        page = int(request.GET.get('page', 1))  # Current page
        page_size = int(request.GET.get('pageSize', 10))  # Records per page

        # Apply sorting (`-` for descending in Django)
        sort_by = f"-{sort_by}" if sort_order == "desc" else sort_by

        # Role-Based Filtering
        user_role = user.role
        user_status = user.manager_admin_status
        is_superuser = user.is_superuser
        
        # Determine if user has admin permissions
        is_admin = (
            is_superuser or 
            user_role == 'admin' or
            (user_status and 'Admin' in user_status)
        )
        
        # Determine if user is a manager
        is_manager = (
            user_role == 'manager' or
            (user_status and 'Manager' in user_status)
        )
        
        if is_admin:
            # Admins can see all withdrawal transactions
            withdrawals = Transaction.objects.filter(
                transaction_type='withdraw_trading'
            ).exclude(status='pending')
        elif is_manager:
            # Managers can only see withdrawal transactions of users they created or their IB clients
            from django.db.models import Q
            manager_clients = CustomUser.objects.filter(
                Q(created_by=user) | Q(parent_ib=user)
            )
            withdrawals = Transaction.objects.filter(
                transaction_type='withdraw_trading',
                user__in=manager_clients
            ).exclude(status='pending')
        else:
            # Regular users cannot access withdrawal transactions list
            withdrawals = Transaction.objects.none()

        # Apply search query
        if search_query:
            withdrawals = withdrawals.filter(
                Q(user__username__icontains=search_query) |
                Q(user__email__icontains=search_query) |
                Q(trading_account_id__icontains=search_query) |
                Q(id__icontains=search_query)
            )

        # Apply sorting
        withdrawals = withdrawals.order_by(sort_by)

        # Apply pagination
        total_count = withdrawals.count()
        start = (page - 1) * page_size
        end = start + page_size
        withdrawals = withdrawals[start:end]

        # Serialize and return
        serializer = TransactionSerializer(withdrawals, many=True)
        return Response({
            "total": total_count,
            "results": serializer.data,
            "user_type": "manager" if is_manager else "admin"
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def internal_transfer_transactions(request):
    """
    Fetch Internal Transfer Transactions with Pagination, Sorting, and Searching.
    """
    try:
        user = request.user
        search_query = request.GET.get('search', '')  # Search query
        sort_by = request.GET.get('sortBy', 'created_at')  # Default sorting field
        sort_order = request.GET.get('sortOrder', 'desc')  # Default sort order
        page = int(request.GET.get('page', 1))  # Current page
        page_size = int(request.GET.get('pageSize', 10))  # Records per page

        # Role-Based Filtering
        if request.user.manager_admin_status in ['Admin', 'Manager']:
            internal_transfers = Transaction.objects.filter(
                transaction_type='internal_transfer'
            ).exclude(status='pending')
        else:
            internal_transfers = Transaction.objects.none()

        # Apply search query
        if search_query:
            internal_transfers = internal_transfers.filter(
                Q(user__username__icontains=search_query) |
                Q(user__email__icontains=search_query) |
                Q(trading_account_id__icontains=search_query) |
                Q(id__icontains=search_query)
            )

        # Apply sorting (`-` for descending in Django)
        sort_by = f"-{sort_by}" if sort_order == "desc" else sort_by
        internal_transfers = internal_transfers.order_by(sort_by)

        # Apply pagination
        total_count = internal_transfers.count()
        start = (page - 1) * page_size
        end = start + page_size
        internal_transfers = internal_transfers[start:end]

        # Serialize and return
        serializer = TransactionSerializer(internal_transfers, many=True)
        return Response({
            "total": total_count,
            "results": serializer.data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAdminOrManager])
def create_user_view(request):
    """
    Admin endpoint to create a new user account.
    Handles user creation with email notification.
    """
    try:
        data = request.data
        logger.info(f"Admin {request.user.email} attempting to create user: {data.get('email')}")

        # Validate required fields
        required_fields = ['first_name', 'email', 'password']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            return Response({
                'error': f'Missing required fields: {", ".join(missing_fields)}'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Check if user already exists
        email = data.get('email').lower().strip()
        if CustomUser.objects.filter(email=email).exists():
            return Response({
                'error': 'A user with this email already exists'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate against disposable/temporary email providers
        try:
            from adminPanel.utils.email_validation import validate_signup_email
            validate_signup_email(email)
        except ValueError:
            return Response({'error': 'Disposable or temporary email addresses are not allowed'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            # If the validator fails unexpectedly, allow continuation rather than blocking all signups
            pass


        # Determine if requester is a manager
        requester_is_manager = False
        try:
            requester_is_manager = (hasattr(request.user, 'manager_admin_status') and 'manager' in (request.user.manager_admin_status or '').lower())
        except Exception:
            requester_is_manager = False

        # Prevent managers from creating elevated accounts or changing status
        if requester_is_manager:
            # Enforce client role for users created by managers
            enforced_status = 'Client'
        else:
            # Admins may optionally pass a manager_id to assign the client
            enforced_status = data.get('manager_admin_status', 'Client')

        # Hash password using the custom format (salt$hash.hex()) for compatibility with verify_password()
        import hashlib
        import secrets
        raw_password = data.get('password')
        salt = secrets.token_hex(16)  # Random 16-byte salt
        password_hash = hashlib.pbkdf2_hmac(
            'sha256',
            raw_password.encode('utf-8'),
            salt.encode('utf-8'),
            100000  # Iterations - must match verify_password() function
        )
        hashed_password = f"{salt}${password_hash.hex()}"

        # Create the user without using create_user() to avoid Django's default hashing
        user = CustomUser(
            email=email,
            password=hashed_password,  # Store the pre-hashed password
            dob=data.get('dob') if data.get('dob') else None,
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            phone_number=data.get('phone_number', ''),
            country=data.get('country', ''),
            address=data.get('address', ''),
            is_active=True,
            created_by=request.user,  # Track who created this user
            verification_status=data.get('verification_status', 'pending'),
            manager_admin_status=enforced_status
        )
        user.save()

        # If the requester is a manager, assign the created user to that manager
        if requester_is_manager:
            try:
                user.manager = request.user
                # If the requester has IB_status or manager_admin_status indicates IB, set as parent_ib
                try:
                    if getattr(request.user, 'IB_status', False) or ('ib' in (getattr(request.user, 'manager_admin_status', '') or '').lower()):
                        user.parent_ib = request.user
                except Exception:
                    pass
                user.save()
            except Exception:
                # non-fatal: continue
                pass
        else:
            # Admin may optionally pass manager_id to assign a manager to the created client
            manager_id = data.get('manager_id') or request.data.get('manager_id')
            if manager_id:
                try:
                    mgr = CustomUser.objects.get(user_id=manager_id)
                    user.manager = mgr
                    # If the selected manager is actually an IB, also set as parent_ib
                    try:
                        if getattr(mgr, 'IB_status', False) or ('ib' in (getattr(mgr, 'manager_admin_status', '') or '').lower()):
                            user.parent_ib = mgr
                    except Exception:
                        pass
                    user.save()
                except CustomUser.DoesNotExist:
                    # ignore invalid manager id
                    pass
            # If parent_ib not set yet and the creator/admin is an IB, set parent_ib to creator
            try:
                if not getattr(user, 'parent_ib', None):
                    if getattr(request.user, 'IB_status', False) or ('ib' in (getattr(request.user, 'manager_admin_status', '') or '').lower()):
                        user.parent_ib = request.user
                        user.save()
            except Exception:
                pass

        logger.info(f"User created successfully: {user.email} (ID: {user.user_id})")

        # Send welcome email if requested
        send_welcome_email = data.get('send_welcome_email', True)
        if send_welcome_email:
            try:
                send_welcome_email_to_user(user, data.get('password'))
                logger.info(f"Welcome email sent to {user.email}")
            except Exception as e:
                logger.error(f"Failed to send welcome email to {user.email}: {str(e)}")
                # Don't fail the user creation if email fails

        # Use UserSerializer to return all user fields, including user_id
        serializer = UserSerializer(user)
        return Response({
            'message': 'User created successfully',
            'user': serializer.data,
            'welcome_email_sent': send_welcome_email
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        return Response({
            'error': f'Failed to create user: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def send_welcome_email_to_user(user, password):
    """
    Send a welcome email to the newly created user with login instructions.
    """
    try:
        # Use the provided HTML template for the welcome email. The template expects
        # keys: first_name, email, password (and optional items for branding).
        template_context = {
            'first_name': user.get_full_name() or user.first_name or user.username,
            'email': user.email,
            'password': password,
            'login_url': f"{settings.FRONTEND_URL}/client_login.html" if hasattr(settings, 'FRONTEND_URL') else "https://client.vtindex.com/",
            'company_name': getattr(settings, 'COMPANY_NAME', 'VTIndex'),
            'company_logo': getattr(settings, 'COMPANY_LOGO', 'https://vtindex.com/static/images/logo.png'),
            'company_website': getattr(settings, 'COMPANY_WEBSITE', 'https://vtindex.com'),
            'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@vtindex.com'),
            'year': timezone.now().year
        }

        subject = f"Welcome to {template_context['company_name']} - Your Account is Ready!"

        # Render the HTML template located at clientPanel/templates/emails/new_user_from_admin.html
        html_message = render_to_string('emails/new_user_from_admin.html', template_context)

        # Send the email
        email = EmailMessage(
            subject=subject,
            body=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.content_subtype = "html"
        email.send()

    except Exception as e:
        logger.error(f"Failed to send welcome email to {user.email}: {str(e)}")
        raise e

# ===== NEW API ENDPOINTS FOR MODALS =====

@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_ib_profiles(request, user_id):
    """
    Get available IB commission profiles.
    """
    try:
        profiles = CommissioningProfile.objects.all()
        profiles_data = []
        for profile in profiles:
            # Handle the case where commission_percentage might be None
            # Use level_1_percentage as fallback since that's the primary commission
            commission = float(profile.commission_percentage) if profile.commission_percentage is not None else float(profile.level_1_percentage or 0.0)
            profiles_data.append({
                'id': profile.id,
                'name': profile.name,
                'commission': commission,
                'level_1_percentage': float(profile.level_1_percentage or 0.0),
                'level_2_percentage': float(profile.level_2_percentage or 0.0),
                'level_3_percentage': float(profile.level_3_percentage or 0.0)
            })
        return Response(profiles_data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error in get_ib_profiles: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticatedUser])  
def user_ib_status(request, user_id):
    """
    Get or update user's IB status.
    """
    try:
        user = CustomUser.objects.get(user_id=user_id)
        
        if request.method == 'GET':
            # Return current IB status
            if user.IB_status and user.commissioning_profile:
                # Handle the case where commission_percentage might be None
                commission = float(user.commissioning_profile.commission_percentage) if user.commissioning_profile.commission_percentage is not None else 0.0
                return Response({
                    'enabled': True,
                    'profile_id': user.commissioning_profile.id,
                    'profile_name': user.commissioning_profile.name,
                    'commission': commission
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'enabled': False,
                    'profile_id': None,
                    'profile_name': None,
                    'commission': 0
                }, status=status.HTTP_200_OK)
        
        elif request.method == 'PATCH':
            # Update IB status
            enabled = request.data.get('enabled', False)
            profile_id = request.data.get('profile_id')
            
            if enabled and profile_id:
                profile = CommissioningProfile.objects.get(id=profile_id)
                user.IB_status = True
                user.commissioning_profile = profile
            else:
                user.IB_status = False
                user.commissioning_profile = None
            
            user.save()
            
            # Log activity
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Updated IB status for user ID {user_id}: {'Enabled' if enabled else 'Disabled'}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=user.id,
                related_object_type="IB Status Change"
            )
            
            return Response({'success': True}, status=status.HTTP_200_OK)
            
    except CustomUser.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
    except CommissioningProfile.DoesNotExist:
        return Response({"error": "Commission profile not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_user_transactions(request, user_id):
    """
    Get user's comprehensive transaction history from the Transaction model.
    Returns completed and pending transactions with full details.
    """
    try:
        user = CustomUser.objects.get(user_id=user_id)
        
        # Get all transactions for this user from the Transaction model
        all_transactions = Transaction.objects.filter(user=user).select_related(
            'trading_account', 'approved_by', 'from_account', 'to_account'
        ).order_by('-created_at')
        
        completed_transactions = []
        pending_transactions = []
        
        for transaction in all_transactions:
            # Determine account number/identifier
            account_number = 'N/A'
            if transaction.trading_account:
                account_number = transaction.trading_account.account_id
            elif transaction.from_account:
                account_number = f"{transaction.from_account.account_id} → {transaction.to_account.account_id if transaction.to_account else 'N/A'}"
            else:
                account_number = f'USER-{user_id}'
            
            # Format transaction data
            transaction_data = {
                'id': transaction.id,
                'transaction_date': transaction.created_at.strftime('%Y-%m-%d %H:%M'),
                'date': transaction.created_at.strftime('%Y-%m-%d'),  # For backwards compatibility
                'amount': float(transaction.amount),
                'transaction_type': transaction.get_transaction_type_display(),
                'type': transaction.transaction_type,  # Raw value for filtering
                'account_number': account_number,
                'account': account_number,  # For backwards compatibility
                'status': transaction.status.title(),
                'approved_by': transaction.approved_by.username if transaction.approved_by else 'N/A',
                'approvedBy': transaction.approved_by.username if transaction.approved_by else 'N/A',  # For backwards compatibility
                'approval_date': transaction.approved_at.strftime('%Y-%m-%d %H:%M') if transaction.approved_at else 'N/A',
                'approvalDate': transaction.approved_at.strftime('%Y-%m-%d') if transaction.approved_at else 'N/A',  # For backwards compatibility
                'description': transaction.description or f'{transaction.get_transaction_type_display()} transaction',
                'source': transaction.source or 'N/A',
                'payout_to': transaction.get_payout_to_display() if transaction.payout_to else 'N/A',
                'external_account': transaction.external_account or 'N/A',
                'document_url': transaction.document.url if transaction.document else None,
            }
            
            # Categorize transactions by status
            if transaction.status in ['approved', 'rejected']:
                completed_transactions.append(transaction_data)
            else:
                pending_transactions.append(transaction_data)
        
        # Sort transactions by date (newest first)
        completed_transactions.sort(key=lambda x: x['transaction_date'], reverse=True)
        pending_transactions.sort(key=lambda x: x['transaction_date'], reverse=True)
        
        return Response({
            'completed': completed_transactions,
            'pending': pending_transactions,
            'total_completed': len(completed_transactions),
            'total_pending': len(pending_transactions),
            'user_id': user_id,
            'user_name': f"{user.first_name} {user.last_name}".strip() or user.username,
        }, status=status.HTTP_200_OK)
        
    except CustomUser.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error fetching transactions for user {user_id}: {str(e)}")
        return Response({"error": f"Failed to fetch transactions: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST', 'PATCH'])
@permission_classes([IsAuthenticatedUser])
def user_bank_details(request, user_id):
    """
    Get or update user's bank details.
    """
    try:
        user = CustomUser.objects.get(user_id=user_id)
        
        if request.method == 'GET':
            # Get bank details from BankDetails model
            bank_details_data = {}
            try:
                bank_details = BankDetails.objects.get(user=user)
                bank_details_data = {
                    'bank_name': bank_details.bank_name or '',
                    'account_number': bank_details.account_number or '',
                    'branch_name': bank_details.branch or '',
                    'ifsc_code': bank_details.ifsc_code or ''
                }
            except BankDetails.DoesNotExist:
                bank_details_data = {
                    'bank_name': '',
                    'account_number': '',
                    'branch_name': '',
                    'ifsc_code': ''
                }
            
            # Get crypto details from CryptoDetails model
            crypto_details_data = {}
            try:
                crypto_details = CryptoDetails.objects.get(user=user)
                crypto_details_data = {
                    'wallet_address': crypto_details.wallet_address or '',
                    'exchange_name': crypto_details.exchange_name or ''
                }
            except CryptoDetails.DoesNotExist:
                crypto_details_data = {
                    'wallet_address': '',
                    'exchange_name': ''
                }
            
            # Combine both bank and crypto details
            combined_details = {**bank_details_data, **crypto_details_data}
            return Response(combined_details, status=status.HTTP_200_OK)
        
        elif request.method in ['POST', 'PATCH']:
            # Update bank details (POST or PATCH)
            # Support both old format (bank-details-name) and new format (bank_name)
            bank_data = {
                'bank_name': request.data.get('bank_name') or request.data.get('bank-details-name', ''),
                'account_number': request.data.get('account_number') or request.data.get('bank-details-account', ''),
                'branch': request.data.get('branch_name') or request.data.get('branch') or request.data.get('bank-details-branch', ''),
                'ifsc_code': request.data.get('ifsc_code') or request.data.get('bank-details-ifsc', '')
            }
            
            # Only create/update if at least one bank field is provided
            if any(bank_data.values()):
                bank_details, created = BankDetails.objects.get_or_create(user=user)
                for field, value in bank_data.items():
                    if value:  # Only update non-empty values
                        setattr(bank_details, field, value)
                bank_details.save()
            
            # Update crypto details
            # Support both old format (crypto-wallet) and new format (wallet_address)
            crypto_data = {
                'wallet_address': request.data.get('wallet_address') or request.data.get('crypto-wallet', ''),
                'exchange_name': request.data.get('exchange_name') or request.data.get('crypto-exchange', '')
            }
            
            # Only create/update if at least one crypto field is provided
            if any(crypto_data.values()):
                crypto_details, created = CryptoDetails.objects.get_or_create(user=user)
                for field, value in crypto_data.items():
                    if value:  # Only update non-empty values
                        setattr(crypto_details, field, value)
                crypto_details.save()
            
            # Log activity
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Updated bank details for user ID {user_id}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=user.id,
                related_object_type="Bank Details Update"
            )
            
            return Response({'success': True}, status=status.HTTP_200_OK)
            
    except CustomUser.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def user_verification_status(request, user_id):
    """
    Get user's document verification status.
    """
    try:
        user = CustomUser.objects.get(user_id=user_id)
        
        # Determine status based on verification state and file presence
        def get_verification_status(file_field, verified_field):
            if verified_field:
                return 'verified'
            elif file_field:
                return 'uploaded'
            else:
                return 'not_uploaded'
        
        verification_data = {
            'id_document': {
                'status': get_verification_status(user.id_proof, user.id_proof_verified),
                'file_url': user.id_proof.url if user.id_proof else None,
                'file_name': user.id_proof.name if user.id_proof else None
            },
            'address_document': {
                'status': get_verification_status(user.address_proof, user.address_proof_verified), 
                'file_url': user.address_proof.url if user.address_proof else None,
                'file_name': user.address_proof.name if user.address_proof else None
            }
        }
        
        return Response(verification_data, status=status.HTTP_200_OK)
        
    except CustomUser.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_demo_accounts(request, user_id):
    """
    Get user's demo accounts.
    """
    try:
        user = CustomUser.objects.get(user_id=user_id)
        demo_accounts = TradingAccount.objects.filter(user=user, account_type='demo')
        
        accounts_data = []
        for account in demo_accounts:
            accounts_data.append({
                'account_number': account.account_number,
                'balance': float(account.balance),
                'leverage': account.leverage,
                'status': account.status or 'active',
                'created_at': account.created_at.isoformat() if account.created_at else None,
                'server': account.server or 'Demo Server'
            })
        
        return Response(accounts_data, status=status.HTTP_200_OK)
        
    except CustomUser.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PATCH'])
@permission_classes([IsAuthenticatedUser])
def update_demo_account(request, user_id, account_number):
    """
    Update demo account status.
    """
    try:
        user = CustomUser.objects.get(user_id=user_id)
        demo_account = TradingAccount.objects.get(
            user=user, 
            account_number=account_number, 
            account_type='demo'
        )
        
        new_status = request.data.get('status')
        if new_status in ['active', 'inactive']:
            demo_account.status = new_status
            demo_account.save()
            
            # Log activity
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Updated demo account {account_number} status to {new_status} for user ID {user_id}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=demo_account.id,
                related_object_type="Demo Account Status"
            )
            
            return Response({'success': True}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)
            
    except CustomUser.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
    except TradingAccount.DoesNotExist:
        return Response({"error": "Demo account not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def reset_demo_account(request, user_id, account_number):
    """
    Reset demo account balance.
    """
    try:
        user = CustomUser.objects.get(user_id=user_id)
        demo_account = TradingAccount.objects.get(
            user=user, 
            account_number=account_number, 
            account_type='demo'
        )
        
        # Reset balance to initial amount (e.g., 10000)
        initial_balance = 10000.00
        demo_account.balance = initial_balance
        demo_account.save()
        
        # Log activity
        ActivityLog.objects.create(
            user=request.user,
            activity=f"Reset demo account {account_number} balance for user ID {user_id}",
            ip_address=get_client_ip(request),
            endpoint=request.path,
            activity_type="update",
            activity_category="management",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=demo_account.id,
            related_object_type="Demo Account Reset"
        )
        
        return Response({'success': True, 'new_balance': initial_balance}, status=status.HTTP_200_OK)
        
    except CustomUser.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
    except TradingAccount.DoesNotExist:
        return Response({"error": "Demo account not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- API endpoint for trading account leverage info ---
@api_view(["GET"])
@permission_classes([IsAdmin])
def change_leverage_info(request, account_id):
    """
    Returns current leverage and available leverage options for a trading account.
    Uses account_id (MT5 account number) for lookup.
    """
    try:
        account = TradingAccount.objects.get(account_id=str(account_id))
        current_leverage = account.leverage
        # Fetch available leverages directly from MT5
        mt5_manager = MT5ManagerActions()
        try:
            available_leverage = mt5_manager.get_available_leverages()  # Should return a list of leverages
        except Exception as e:
            logger.error(f"Error fetching leverages from MT5: {str(e)}")
            available_leverage = [10, 20, 50, 100, 200, 500, 1000]  # fallback
        return Response({
            "account_id": account_id,
            "current_leverage": current_leverage,
            "available_leverage": available_leverage
        }, status=status.HTTP_200_OK)
    except TradingAccount.DoesNotExist:
        return Response({"error": "Account not found"}, status=status.HTTP_404_NOT_FOUND)

# --- API endpoint for trading account leverage update ---
@api_view(["POST"])
@permission_classes([IsAdmin])
def change_leverage_update(request):
    """
    Allows admin to update the leverage for a trading account.
    Expects: {"account_id": ..., "new_leverage": ...}
    """
    account_id = request.data.get("account_id")
    new_leverage = request.data.get("new_leverage")
    if not account_id or not new_leverage:
        return Response({"error": "Missing account_id or new_leverage."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        account = TradingAccount.objects.get(account_id=str(account_id))
        if int(new_leverage) not in [10, 20, 50, 100, 200, 500, 1000]:
            return Response({"error": "Invalid leverage value."}, status=status.HTTP_400_BAD_REQUEST)
        old_leverage = account.leverage
        account.leverage = int(new_leverage)
        account.save()
        # Log activity
        ActivityLog.objects.create(
            user=request.user,
            activity=f"Changed leverage for account {account_id} from {old_leverage} to {new_leverage}",
            ip_address=get_client_ip(request),
            endpoint=request.path,
            activity_type="update",
            activity_category="management",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=account.id,
            related_object_type="TradingAccountLeverageChange"
        )
        return Response({"success": True, "account_id": account_id, "new_leverage": account.leverage}, status=status.HTTP_200_OK)
    except TradingAccount.DoesNotExist:
        return Response({"error": "Account not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAdminOrManager])
def disable_demo_account(request, account_id):
    """
    Disable a demo account by setting its status to disabled/inactive.
    """
    try:
        logger.debug(f"[Disable DemoAccount] Incoming request for account_id={account_id} from IP={get_client_ip(request)}")
        account = DemoAccount.objects.filter(account_id=account_id).first()
        if not account:
            logger.debug(f"[Disable DemoAccount] DemoAccount not found for account_id={account_id}")
            return JsonResponse({'error': 'Demo account not found.'}, status=404)
        
        # Disable account in MT5 server first
        try:
            mt5_manager = MT5ManagerActions()
            if not mt5_manager.disable_account(account_id):
                logger.error(f"[Disable DemoAccount] Failed to disable account in MT5 server for account_id={account_id}")
                return JsonResponse({'error': 'Failed to disable account in MT5 server'}, status=500)
            logger.info(f"[Disable DemoAccount] Successfully disabled account in MT5 for account_id={account_id}")
        except Exception as mt5_ex:
            logger.error(f"[Disable DemoAccount] MT5 error for account_id={account_id}: {mt5_ex}")
            return JsonResponse({'error': f'MT5 server error: {str(mt5_ex)}'}, status=500)
        
        # Update database after successful MT5 operation
        # Check for is_active or fallback to status field
        if hasattr(account, 'is_active'):
            logger.debug(f"[Disable DemoAccount] Found DemoAccount: account_id={account.account_id}, is_active={account.is_active}")
            account.is_active = False
        elif hasattr(account, 'status'):
            logger.debug(f"[Disable DemoAccount] Found DemoAccount: account_id={account.account_id}, status={account.status}")
            account.status = 'disabled'
        else:
            logger.error(f"[Disable DemoAccount] DemoAccount missing is_active/status field for account_id={account.account_id}")
            return JsonResponse({'error': 'DemoAccount missing is_active/status field.'}, status=500)
        account.save()
        logger.info(f"[Disable DemoAccount] Disabled account_id={account.account_id}")
        return JsonResponse({'success': True, 'message': 'Demo account disabled.'})
    except Exception as e:
        logger.error(f"[Disable DemoAccount] Error for account_id={account_id}: {e}")
        return JsonResponse({'error': str(e)}, status=500)
@csrf_exempt
def reset_leverage_demo_account(request, account_id):
    if request.method == 'POST':
        import json
        logger.debug(f"[Leverage Reset] Incoming request for account_id={account_id} from IP={get_client_ip(request)}")
        try:
            data = json.loads(request.body)
            logger.debug(f"[Leverage Reset] Parsed JSON body: {data}")
        except Exception as ex:
            logger.error(f"[Leverage Reset] Invalid JSON: {request.body} | Error: {ex}")
            return JsonResponse({'error': 'Invalid JSON.'}, status=400)
        leverage = data.get('leverage')
        if not leverage:
            logger.error(f"[Leverage Reset] Missing leverage value in request for account_id={account_id}")
            return JsonResponse({'error': 'Missing leverage value.'}, status=400)
        try:
            account = DemoAccount.objects.get(account_id=account_id)
            logger.debug(f"[Leverage Reset] Found DemoAccount: id={account.id}, current_leverage={account.leverage}")
            # Optionally validate leverage value
            try:
                int_leverage = int(leverage)
                if int_leverage not in [10, 20, 50, 100, 200, 500, 1000]:
                    logger.error(f"[Leverage Reset] Invalid leverage value: {leverage} for account_id={account_id}")
                    return JsonResponse({'error': 'Invalid leverage value.'}, status=400)
            except Exception as ex:
                logger.error(f"[Leverage Reset] Leverage must be integer. Got: {leverage} | Error: {ex}")
                return JsonResponse({'error': 'Leverage must be an integer.'}, status=400)
            old_leverage = account.leverage
            
            # Update MT5 server first
            try:
                mt5_manager = MT5ManagerActions()
                success = mt5_manager.change_leverage(account_id, int_leverage)
                if not success:
                    logger.error(f"[Leverage Reset] MT5 update failed for account_id={account_id}")
                    return JsonResponse({'error': 'Failed to update leverage on MT5 server'}, status=500)
                logger.info(f"[Leverage Reset] Successfully updated MT5 leverage for account_id={account_id}")
            except Exception as mt5_ex:
                logger.error(f"[Leverage Reset] MT5 update exception for account_id={account_id}: {mt5_ex}")
                return JsonResponse({'error': f'MT5 server error: {str(mt5_ex)}'}, status=500)
            
            # Update database after successful MT5 update
            account.leverage = str(leverage)
            account.save()
            logger.info(f"[Leverage Reset] Updated database leverage for account_id={account_id} from {old_leverage} to {leverage}")
            # Optionally log activity
            try:
                user = getattr(request, 'user', None)
                if user and hasattr(user, 'id') and not getattr(user, 'is_anonymous', True):
                    ActivityLog.objects.create(
                        user=user,
                        activity=f"Changed leverage for demo account {account.account_id} from {old_leverage} to {leverage}",
                        ip_address=get_client_ip(request),
                        endpoint=request.path,
                        activity_type="update",
                        activity_category="management",
                        user_agent=request.META.get("HTTP_USER_AGENT", ""),
                        timestamp=timezone.now(),
                        related_object_id=account.id,
                        related_object_type="DemoAccountLeverageChange"
                    )
                else:
                    logger.info(f"[Leverage Reset] ActivityLog not created: unauthenticated user.")
            except Exception as ex:
                logger.error(f"[Leverage Reset] ActivityLog creation failed: {ex}")
                pass
            return JsonResponse({'success': True, 'new_leverage': account.leverage})
        except DemoAccount.DoesNotExist:
            logger.error(f"[Leverage Reset] DemoAccount not found for account_id={account_id}")
            return JsonResponse({'error': 'Demo account not found.'}, status=404)
        except Exception as e:
            logger.error(f"[Leverage Reset] Unexpected error for account_id={account_id}: {e}")
            return JsonResponse({'error': str(e)}, status=500)
    logger.error(f"[Leverage Reset] Invalid method: {request.method} for account_id={account_id}")
    return JsonResponse({'error': 'Invalid method'}, status=405)

# Reset balance for demo account
@csrf_exempt
def reset_balance_demo_account(request, account_id):
    if request.method == 'POST':
        import json
        logger.debug(f"[Balance Reset] Incoming request for account_id={account_id} from IP={get_client_ip(request)}")
        try:
            data = json.loads(request.body)
            logger.debug(f"[Balance Reset] Parsed JSON body: {data}")
        except Exception as ex:
            logger.error(f"[Balance Reset] Invalid JSON: {request.body} | Error: {ex}")
            return JsonResponse({'error': 'Invalid JSON.'}, status=400)
        balance = data.get('balance')
        if balance is None:
            logger.error(f"[Balance Reset] Missing balance value in request for account_id={account_id}")
            return JsonResponse({'error': 'Missing balance value.'}, status=400)
        try:
            account = DemoAccount.objects.get(account_id=account_id)
            logger.debug(f"[Balance Reset] Found DemoAccount: account_id={account.account_id}, current_balance={account.balance}")
            try:
                new_balance = float(balance)
                if new_balance < 0:
                    logger.error(f"[Balance Reset] Negative balance value: {balance} for account_id={account_id}")
                    return JsonResponse({'error': 'Balance must be non-negative.'}, status=400)
            except Exception as ex:
                logger.error(f"[Balance Reset] Balance must be a number. Got: {balance} | Error: {ex}")
                return JsonResponse({'error': 'Balance must be a number.'}, status=400)
            old_balance = account.balance
            
            # Update MT5 server first
            try:
                mt5_manager = MT5ManagerActions()
                
                # Get current balance from MT5
                current_mt5_balance = mt5_manager.get_balance(account_id)
                if current_mt5_balance is None:
                    logger.error(f"[Balance Reset] Could not get current MT5 balance for account_id={account_id}")
                    return JsonResponse({'error': 'Failed to get current balance from MT5 server'}, status=500)
                
                # Calculate difference and reset balance
                balance_difference = new_balance - current_mt5_balance
                
                if abs(balance_difference) > 0.01:  # Only update if significant difference
                    if balance_difference > 0:
                        # Need to deposit
                        success = mt5_manager.deposit_funds(account_id, balance_difference, "Admin Balance Reset")
                    else:
                        # Need to withdraw
                        success = mt5_manager.withdraw_funds(account_id, abs(balance_difference), "Admin Balance Reset")
                    
                    if not success:
                        logger.error(f"[Balance Reset] MT5 balance operation failed for account_id={account_id}")
                        return JsonResponse({'error': 'Failed to update balance on MT5 server'}, status=500)
                
                logger.info(f"[Balance Reset] Successfully updated MT5 balance for account_id={account_id} from {current_mt5_balance} to {new_balance}")
            except Exception as mt5_ex:
                logger.error(f"[Balance Reset] MT5 update exception for account_id={account_id}: {mt5_ex}")
                return JsonResponse({'error': f'MT5 server error: {str(mt5_ex)}'}, status=500)
            
            # Update database after successful MT5 update
            account.balance = new_balance
            account.save()
            logger.info(f"[Balance Reset] Updated database balance for account_id={account_id} from {old_balance} to {new_balance}")
            try:
                user = getattr(request, 'user', None)
                if user and hasattr(user, 'id') and not getattr(user, 'is_anonymous', True):
                    ActivityLog.objects.create(
                        user=user,
                        activity=f"Changed balance for demo account {account.account_id} from {old_balance} to {new_balance}",
                        ip_address=get_client_ip(request),
                        endpoint=request.path,
                        activity_type="update",
                        activity_category="management",
                        user_agent=request.META.get("HTTP_USER_AGENT", ""),
                        timestamp=timezone.now(),
                        related_object_id=account.id,
                        related_object_type="DemoAccountBalanceChange"
                    )
                else:
                    logger.info(f"[Balance Reset] ActivityLog not created: unauthenticated user.")
            except Exception as ex:
                logger.error(f"[Balance Reset] ActivityLog creation failed: {ex}")
                pass
            return JsonResponse({'success': True, 'new_balance': str(account.balance)})
        except DemoAccount.DoesNotExist:
            logger.error(f"[Balance Reset] DemoAccount not found for id={account_id}")
            return JsonResponse({'error': 'Demo account not found.'}, status=404)
        except Exception as e:
            logger.error(f"[Balance Reset] Unexpected error for id={account_id}: {e}")
            return JsonResponse({'error': str(e)}, status=500)
    logger.error(f"[Balance Reset] Invalid method: {request.method} for id={account_id}")
    return JsonResponse({'error': 'Invalid method'}, status=405)
# Enable demo account by account_id
@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAdminOrManager])
def enable_demo_account(request, account_id):
    """
    Enable a demo account by account_id (MT5/demo account number).
    """
    try:
        ip = request.META.get('REMOTE_ADDR', '')
        logger.debug(f"[Enable DemoAccount] Incoming request for account_id={account_id} from IP={ip}")
        demo_account = DemoAccount.objects.filter(account_id=account_id).first()
        if not demo_account:
            logger.error(f"[Enable DemoAccount] DemoAccount not found for account_id={account_id}")
            return Response({"error": "Demo account not found."}, status=status.HTTP_404_NOT_FOUND)
        logger.debug(f"[Enable DemoAccount] Found DemoAccount: account_id={account_id}, is_active={demo_account.is_active}")
        
        # Enable account in MT5 server first
        try:
            mt5_manager = MT5ManagerActions()
            if not mt5_manager.enable_account(account_id):
                logger.error(f"[Enable DemoAccount] Failed to enable account in MT5 server for account_id={account_id}")
                return Response({"error": "Failed to enable account in MT5 server"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            logger.info(f"[Enable DemoAccount] Successfully enabled account in MT5 for account_id={account_id}")
        except Exception as mt5_ex:
            logger.error(f"[Enable DemoAccount] MT5 error for account_id={account_id}: {mt5_ex}")
            return Response({"error": f"MT5 server error: {str(mt5_ex)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Update database after successful MT5 operation
        demo_account.is_active = True
        demo_account.save()
        logger.info(f"[Enable DemoAccount] Enabled account_id={account_id}")
        return Response({"message": "Demo account enabled successfully."}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"[Enable DemoAccount] Error enabling account {account_id}: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

