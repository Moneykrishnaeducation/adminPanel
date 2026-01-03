
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from ..models import CustomUser
from ..permissions import IsAdminOrManager
from clientPanel.models import BankDetails as ClientBankDetails
from clientPanel.serializers import BankDetailsSerializer, CryptoDetailsSerializer
from adminPanel.models import CryptoDetails
from adminPanel.views.user_bank_details import UserBankDetailsView

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_kyc_status(request, user_id):
    """
    API endpoint to check if a user's KYC is complete (user_verified).
    Returns: {"user_id": ..., "kyc_complete": true/false}
    """
    try:
        user = get_object_or_404(CustomUser, user_id=user_id)
        return Response({
            "user_id": user.user_id,
            "kyc_complete": user.user_verified
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def get_ib_user_bank_details(request, user_id):
    """
    Return IB user's bank and crypto details for the given user_id (for /ib-user/<user_id>/bank-details/)
    """
    user = get_object_or_404(CustomUser, user_id=user_id)

    if request.method == 'GET':
        # Get bank details
        try:
            bank_details = ClientBankDetails.objects.get(user__id=user.id)
            bank_data = BankDetailsSerializer(bank_details).data
        except ClientBankDetails.DoesNotExist:
            bank_data = {
                "bank_name": "",
                "account_number": "",
                "branch_name": "",
                "ifsc_code": "",
                "bank_doc": None,
                "status": "",
                "created_at": None,
                "updated_at": None
            }
        # Get crypto details
        try:
            crypto_details = CryptoDetails.objects.get(user=user)
            crypto_data = CryptoDetailsSerializer(crypto_details).data
        except CryptoDetails.DoesNotExist:
            crypto_data = {
                "wallet_address": "",
                "exchange_name": "",
                "crypto_doc": None,
                "currency": "BTC",
                "status": "",
                "created_at": None,
                "updated_at": None
            }
        # Flatten and merge both dicts
        merged = {**bank_data, **crypto_data}
        return Response(merged)

    elif request.method == 'POST':
        # Use serializer for validation and saving, with debug logging
        import logging
        logger = logging.getLogger(__name__)
        try:
            # Save bank details
            bank_details, _ = ClientBankDetails.objects.get_or_create(user_id=user.id)
            bank_data = request.data.copy()
            bank_data['user'] = user.id
            # Only auto-approve if admin/staff; managers always get 'pending'
            if hasattr(request, 'user'):
                if getattr(request.user, 'is_staff', False) or getattr(request.user, 'role', None) == 'admin':
                    bank_data['status'] = 'approved'
                else:
                    bank_data['status'] = 'pending'
            bank_serializer = BankDetailsSerializer(bank_details, data=bank_data, partial=True)
            bank_result = None
            if bank_serializer.is_valid():
                bank_serializer.save(user=user)
                bank_result = bank_serializer.data
                logger.info(f"Bank details saved for user {user.id}: {bank_serializer.data}")
            else:
                logger.error(f"Bank details NOT saved for user {user.id}. Data: {bank_data}. Errors: {bank_serializer.errors}")
                return Response({"bank_errors": bank_serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

            # Save crypto details
            try:
                crypto_details = CryptoDetails.objects.get(user=user)
            except CryptoDetails.DoesNotExist:
                crypto_details = CryptoDetails(user=user)
            crypto_data = request.data.copy()
            crypto_data['user'] = user.id
            # Only auto-approve if admin/staff; managers always get 'pending'
            if hasattr(request, 'user'):
                if getattr(request.user, 'is_staff', False) or getattr(request.user, 'role', None) == 'admin':
                    crypto_data['status'] = 'approved'
                else:
                    crypto_data['status'] = 'pending'
            crypto_serializer = CryptoDetailsSerializer(crypto_details, data=crypto_data, partial=True)
            crypto_result = None
            if crypto_serializer.is_valid():
                crypto_serializer.save(user=user)
                crypto_result = crypto_serializer.data
                logger.info(f"Crypto details saved for user {user.id}: {crypto_serializer.data}")
            else:
                logger.error(f"Crypto details NOT saved for user {user.id}. Data: {crypto_data}. Errors: {crypto_serializer.errors}")
                return Response({"crypto_errors": crypto_serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

            # Flatten and merge both dicts for response
            merged = {**(bank_result or {}), **(crypto_result or {})}
            return Response(merged, status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception(f"Exception while saving bank/crypto details for user {user.id}. Data: {request.data}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
# IB-only user list endpoint
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import get_user_model
User = get_user_model()
from adminPanel.serializers import UserSerializer  # Adjust if your serializer is different

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_ib_users(request):
    # Filter IB users by IB_status boolean field (adjust if your field is different)
    ib_users = User.objects.filter(IB_status=True)
    serializer = UserSerializer(ib_users, many=True)
    return Response(serializer.data)
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from ..decorators import role_required
from ..roles import UserRole
from ..models import CustomUser, CommissioningProfile, ActivityLog
from ..serializers import UserSerializer
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q, CharField, TextField

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
# Allow both admins and managers to list users. Managers will only see their own clients.
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
def list_users(request):
    try:
        # Get all users (admin, manager, and client users)
        users = CustomUser.objects.all()

        # If the requester is a manager, restrict to clients assigned to them
        requester_role = getattr(request.user, 'role', None)
        if requester_role == UserRole.MANAGER.value:
            users = users.filter(manager=request.user)
        else:
            # Admins may optionally filter by manager_id query parameter
            manager_id = request.GET.get('manager_id')
            if manager_id:
                users = users.filter(manager__user_id=manager_id)
        
        # Handle search
        search_query = request.GET.get('search', '')
        exact_email = request.GET.get('exact_email', 'false').lower() == 'true'
        
        if search_query:
            
            if exact_email:
                # If exact_email flag is set, prioritize exact email matching
                # Try exact case-insensitive match first
                email_matches = users.filter(email__iexact=search_query)
                
                if email_matches.exists():
                    users = email_matches
                else:
                    # If no exact match, try a contains match for email only
                    email_contains_matches = users.filter(email__icontains=search_query)
                    
                    if email_contains_matches.exists():
                        users = email_contains_matches
                    else:
                        # Fall back to general search across all fields
                        query = Q()
                        for field in CustomUser._meta.get_fields():
                            if field.concrete and field.is_relation is False and isinstance(field, (CharField, TextField)):
                                query |= Q(**{f"{field.name}__icontains": search_query})
                        users = users.filter(query)
            else:
                # Regular search behavior
                query = Q()
                for field in CustomUser._meta.get_fields():
                    if field.concrete and field.is_relation is False:
                        query |= Q(**{f"{field.name}__icontains": search_query})
                users = users.filter(query)

        # Handle sorting
        sort_by = request.GET.get('sortBy', 'date_joined')
        sort_order = request.GET.get('sortOrder', 'desc')
        if sort_order == 'desc':
            sort_by = f'-{sort_by}'
        users = users.order_by(sort_by)

        # Handle pagination
        paginator = PageNumberPagination()
        paginator.page_size = int(request.GET.get('pageSize', 10))
        paginator.max_page_size = 100
        result_page = paginator.paginate_queryset(users, request)

        # Serialize the data
        serializer = UserSerializer(result_page, many=True)
        return paginator.get_paginated_response(serializer.data)

    except Exception as e:
        return Response(
            {"error": f"An unexpected error occurred: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def list_admins_managers(request):
    # Query for admin and manager users
    try:
        # Get users with admin or manager roles
        admins_managers = CustomUser.objects.filter(
            Q(role=UserRole.ADMIN.value) | Q(role=UserRole.MANAGER.value)
        ).values('user_id', 'first_name', 'last_name', 'email', 'role', 'date_joined')
        
        # Format the data as expected by the frontend
        result = []
        for user in admins_managers:
            result.append({
                'id': user['user_id'],
                'first_name': user['first_name'],
                'last_name': user['last_name'],
                'email': user['email'],
                'role': user['role'],
                'elevated_date': user['date_joined'].strftime('%Y-%m-%d') if user['date_joined'] else None
            })
        
        return Response({"admins": result})
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def get_admin_manager_details(request, user_id):
    return Response({"message": f"Details for admin/manager {user_id}"})

class ManageClientAssignmentsView(APIView):
    @role_required([UserRole.ADMIN.value])
    def post(self, request):
        """
        Assign or change IB and manager for a client
        Request body should contain:
        {
            "client_id": int,
            "ib_id": int or null,  # Set to null to remove IB
            "manager_id": int or null,  # Set to null to remove manager
            "commissioning_profile_id": int or null  # Required only when assigning IB
        }
        """
        try:
            with transaction.atomic():
                # Get the client
                client = get_object_or_404(CustomUser, user_id=request.data.get('client_id'))

                # Validate that the user is actually a client
                if client.manager_admin_status != 'None':
                    return Response(
                        {"error": "Selected user is not a client"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                changes_made = []
                
                # Handle IB assignment
                new_ib_id = request.data.get('ib_id')
                if new_ib_id is not None:  # None means no change requested
                    old_ib = client.parent_ib
                    if new_ib_id:  # If not empty/null/0
                        # Assign new IB
                        new_ib = get_object_or_404(CustomUser, user_id=new_ib_id)
                        
                        # Validate that the new IB has IB status
                        if not new_ib.IB_status:
                            return Response(
                                {"error": "Selected user is not an IB"},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        
                        # Get commissioning profile
                        profile_id = request.data.get('commissioning_profile_id')
                        if not profile_id:
                            return Response(
                                {"error": "Commissioning profile is required when assigning an IB"},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        
                        commissioning_profile = get_object_or_404(CommissioningProfile, id=profile_id)
                        new_ib.commissioning_profile = commissioning_profile
                        new_ib.save()
                        
                        client.parent_ib = new_ib
                        changes_made.append(f"IB changed from {old_ib.email if old_ib else 'None'} to {new_ib.email}")
                    else:
                        # Remove IB
                        client.parent_ib = None
                        changes_made.append(f"IB removed (was {old_ib.email if old_ib else 'None'})")

                # Handle manager assignment
                new_manager_id = request.data.get('manager_id')
                if new_manager_id is not None:  # None means no change requested
                    old_manager = client.manager
                    if new_manager_id:  # If not empty/null/0
                        # Assign new manager
                        new_manager = get_object_or_404(CustomUser, user_id=new_manager_id)
                        
                        # Validate that the new manager has manager status
                        if not new_manager.MAM_manager_status:
                            return Response(
                                {"error": "Selected user is not a manager"},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        
                        client.manager = new_manager
                        changes_made.append(f"Manager changed from {old_manager.email if old_manager else 'None'} to {new_manager.email}")
                    else:
                        # Remove manager
                        client.manager = None
                        changes_made.append(f"Manager removed (was {old_manager.email if old_manager else 'None'})")

                client.save()

                # Log the activity
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Modified client {client.email} assignments: {', '.join(changes_made)}",
                    activity_type='update',
                    activity_category='management'
                )

                return Response({
                    "message": "Client assignments updated successfully",
                    "changes": changes_made
                })

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

@api_view(['GET'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def get_user_info(request, user_id):
    """
    Get detailed user information for admin panel
    """
    try:
        user = get_object_or_404(CustomUser, user_id=user_id)
        
        # Prepare user data for response
        user_data = {
            'user_id': user.user_id,
            'id': user.user_id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'phone_number': user.phone_number,
            'role': user.role,
            'user_type': user.role,  # Alias for compatibility
            'is_active': user.is_active,
            'date_joined': user.date_joined,
            'country': user.country,
            'address': user.address,
            'IB_status': user.IB_status,
            'MAM_manager_status': user.MAM_manager_status,
            'manager_admin_status': user.manager_admin_status,
            'available_roles': [
                {'label': 'Admin', 'value': 'admin', 'class': 'admin-member'},
                {'label': 'Manager', 'value': 'manager', 'class': 'manager-member'},
                {'label': 'Client', 'value': 'client', 'class': 'client-member'}
            ]
        }
        
        return Response(user_data)
        
    except CustomUser.DoesNotExist:
        return Response(
            {"error": "User not found"},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {"error": f"An error occurred: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['PATCH'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def update_user_status(request, user_id):
    """
    Update user role/status or active state
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        user = get_object_or_404(CustomUser, user_id=user_id)
        data = request.data
        response_data = {}
        updated = False

        # Handle active status toggle
        if 'active' in data:
            active = data.get('active')
            if isinstance(active, str):
                active = active.lower() == 'true'
            user.is_active = bool(active)
            user.save()
            response_data['active'] = user.is_active
            updated = True

        # Handle role change (legacy, optional)
        if 'role' in data:
            new_role = data.get('role')
            if new_role:
                new_role = new_role.lower()
                valid_roles = [UserRole.ADMIN.value, UserRole.MANAGER.value, UserRole.CLIENT.value]
                if new_role not in valid_roles:
                    return Response(
                        {"error": f"Invalid role. Valid roles are: {', '.join(valid_roles)}"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                old_role = user.role
                user.role = new_role
                # Update related fields based on role
                if new_role == UserRole.ADMIN.value:
                    user.manager_admin_status = 'Admin'
                elif new_role == UserRole.MANAGER.value:
                    user.manager_admin_status = 'Manager'
                    user.MAM_manager_status = True
                else:  # CLIENT
                    user.manager_admin_status = 'Client'
                    user.MAM_manager_status = False
                user.save()
                response_data['old_role'] = old_role
                response_data['new_role'] = new_role
                updated = True

        if updated:
            return Response(response_data, status=status.HTTP_200_OK)
        else:
            logger.warning(f"No valid fields provided in PATCH to update_user_status for user {user_id}")
            return Response({"error": "No valid fields provided (must include 'active' or 'role')"}, status=status.HTTP_400_BAD_REQUEST)

    except CustomUser.DoesNotExist:
        logger.error(f"User {user_id} not found in update_user_status")
        return Response(
            {"error": "User not found"},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.exception(f"Exception in update_user_status for user {user_id}: {str(e)}")
        return Response(
            {"error": f"An error occurred: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
