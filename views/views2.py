import os
import logging
logger = logging.getLogger(__name__)

from django.utils.timezone import now
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import RetrieveUpdateAPIView
from adminPanel.permissions import IsAdmin, IsManager, OrPermission, IsAuthenticatedUser
from rest_framework.response import Response
from rest_framework.views import APIView
from adminPanel.models import *
from adminPanel.serializers import *
from adminPanel.views.views import get_client_ip, send_ib_approval_email, logger
from django.db import models, transaction
from clientPanel.serializers import BankDetailsSerializer, CryptoDetailsSerializer
from clientPanel.models import UserDocument  # Add import for UserDocument model
from rest_framework.parsers import MultiPartParser
from rest_framework.decorators import parser_classes

def try_delete_file(file_field):
    """Safely delete a file field."""
    try:
        if file_field and hasattr(file_field, 'path') and os.path.isfile(file_field.path):
            os.remove(file_field.path)
            return True
    except Exception as e:
        logger.error(f"Error deleting file: {str(e)}")
    return False

class CreateCommissioningProfileView(APIView):
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def post(self, request):
        # Set default values for new commission system
        if 'use_percentage_based' not in request.data:
            request.data['use_percentage_based'] = False  # Default to USD per lot
            
        serializer = CommissioningProfileSerializer(data=request.data)
        if serializer.is_valid():
            profile = serializer.save()
            
            # Enhanced activity logging
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

            # Return enhanced serializer response
            from adminPanel.serializers import CommissioningProfileSerializerFor
            response_serializer = CommissioningProfileSerializerFor(profile)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UpdateCommissioningProfileView(APIView):
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def put(self, request, profile_id):
        try:
            profile = CommissioningProfile.objects.get(id=profile_id)
        except CommissioningProfile.DoesNotExist:
            return Response({"error": "Commissioning profile not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = CommissioningProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            old_values = {
                'name': profile.name,
                'commission_type': 'Percentage-based' if profile.use_percentage_based else 'USD per lot',
                'groups': len(profile.approved_groups) if profile.approved_groups else 0
            }
            
            profile = serializer.save()
            
            # Enhanced activity logging
            commission_type = "Percentage-based" if profile.use_percentage_based else "USD per lot"
            group_info = f" with {len(profile.approved_groups)} approved groups" if profile.approved_groups else " (all groups approved)"
            
            changes = []
            if old_values['name'] != profile.name:
                changes.append(f"name: '{old_values['name']}' → '{profile.name}'")
            if old_values['commission_type'] != commission_type:
                changes.append(f"type: {old_values['commission_type']} → {commission_type}")
            if old_values['groups'] != (len(profile.approved_groups) if profile.approved_groups else 0):
                changes.append(f"groups: {old_values['groups']} → {len(profile.approved_groups) if profile.approved_groups else 0}")
            
            change_summary = f" ({', '.join(changes)})" if changes else ""
            
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Updated commissioning profile: {profile.name} ({commission_type}){group_info}{change_summary}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=profile.id,
                related_object_type="CommissioningProfile"
            )
            
            # Return enhanced serializer response
            from adminPanel.serializers import CommissioningProfileSerializerFor
            response_serializer = CommissioningProfileSerializerFor(profile)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, profile_id):
        try:
            profile = CommissioningProfile.objects.get(id=profile_id)
        except CommissioningProfile.DoesNotExist:
            return Response({"error": "Commissioning profile not found."}, status=status.HTTP_404_NOT_FOUND)

        profile_name = profile.name
        commission_type = "Percentage-based" if profile.use_percentage_based else "USD per lot"
        group_count = len(profile.approved_groups) if profile.approved_groups else 0
        
        profile.delete()
        
        ActivityLog.objects.create(
            user=request.user,
            activity=f"Deleted commissioning profile: {profile_name} ({commission_type}, {group_count} groups)",
            ip_address=get_client_ip(request),
            endpoint=request.path,
            activity_type="delete",
            activity_category="management",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=profile_id,
            related_object_type="CommissioningProfile"
        )
        
        return Response({"message": "Commissioning profile deleted successfully."}, status=status.HTTP_200_OK)
    
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_available_trading_groups(request):
    """
    Get list of available trading groups for commission profile configuration.
    """
    try:
        # Try to get groups from TradingAccountGroup model
        try:
            trading_groups = TradingAccountGroup.objects.first()
            if trading_groups and trading_groups.available_groups:
                available_groups = trading_groups.available_groups
            else:
                available_groups = []
        except:
            available_groups = []
        
        # Also get groups from TradeGroup model
        try:
            trade_groups = TradeGroup.objects.filter(is_active=True).values_list('name', flat=True)
            trade_groups_list = list(trade_groups)
        except:
            trade_groups_list = []
        
        # Combine and deduplicate
        all_groups = list(set(available_groups + trade_groups_list))
        all_groups.sort()
        
        # If no groups found, provide some default examples
        if not all_groups:
            all_groups = ["real", "demo", "standard", "premium", "vip"]
        
        return Response({
            "available_groups": all_groups,
            "total_count": len(all_groups)
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error fetching trading groups: {e}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_available_trading_groups_non_demo(request):
    """
    Get list of available trading groups excluding demo groups for commission profile configuration.
    """
    try:
        # Try to get groups from TradingAccountGroup model
        try:
            trading_groups = TradingAccountGroup.objects.first()
            if trading_groups and trading_groups.available_groups:
                available_groups = trading_groups.available_groups
            else:
                available_groups = []
        except:
            available_groups = []
        
        # Also get groups from TradeGroup model
        try:
            trade_groups = TradeGroup.objects.filter(is_active=True).values_list('name', flat=True)
            trade_groups_list = list(trade_groups)
        except:
            trade_groups_list = []
        
        # Combine and deduplicate
        all_groups = list(set(available_groups + trade_groups_list))
        
        # Filter out demo groups (exclude any group containing "demo" in name)
        non_demo_groups = [g for g in all_groups if g and 'demo' not in g.lower()]
        non_demo_groups.sort()
        
        # If no non-demo groups found, provide some default examples
        if not non_demo_groups:
            non_demo_groups = ["real", "standard", "premium", "vip"]
        
        return Response({
            "available_groups": non_demo_groups,
            "total_count": len(non_demo_groups)
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error fetching non-demo trading groups: {e}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_commission_profile_details(request, profile_id):
    """
    Get detailed information about a specific commission profile.
    """
    try:
        profile = CommissioningProfile.objects.get(id=profile_id)
        from adminPanel.serializers import CommissioningProfileSerializerFor
        serializer = CommissioningProfileSerializerFor(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except CommissioningProfile.DoesNotExist:
        return Response({"error": "Commission profile not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def ib_status(request, user_id):
    user = get_object_or_404(CustomUser, user_id=user_id)
    return Response({"ibEnabled": user.IB_status, "commissioningProfile": str(user.commissioning_profile)}, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def set_ib_status(request, user_id):
    """
    Set or update IB status for a user and configure their commissioning profile.
    """
    try:
        user = CustomUser.objects.get(user_id=user_id)
        commissioning_profile_id = request.data.get('commissioning_profile_id')
        
        if not commissioning_profile_id:
            return Response({"error": "Commissioning profile ID is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            commissioning_profile = CommissioningProfile.objects.get(id=commissioning_profile_id)
        except CommissioningProfile.DoesNotExist:
            return Response({"error": "Invalid commissioning profile ID."}, status=status.HTTP_404_NOT_FOUND)

        user.IB_status = True
        user.commissioning_profile = commissioning_profile
        user.save()

        ActivityLog.objects.create(
            user=request.user,
            activity=f"Set IB status for user {user_id} with commissioning profile {commissioning_profile.name}",
            ip_address=get_client_ip(request),
            endpoint=request.path,
            activity_type="update",
            activity_category="management",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=user.id,
            related_object_type="User"
        )
        send_ib_approval_email(user)
        return Response({"message": "IB status updated successfully."}, status=status.HTTP_200_OK)

    except CustomUser.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def trading_accounts_list(request):
    """
    API view to list trading accounts with search, sorting, and pagination.
    """
    try:
        if request.user.manager_admin_status in ['Admin', 'Manager']:
            standard_trading_accounts = TradingAccount.objects.select_related('user').filter(account_type='standard')
        else:
            standard_trading_accounts = TradingAccount.objects.none()

        search_query = request.GET.get('search', '')
        if search_query:
            standard_trading_accounts = standard_trading_accounts.filter(
                Q(user__username__icontains=search_query) |
                Q(user__email__icontains=search_query) |
                Q(account_id__icontains=search_query)
            )

        sort_by = request.GET.get('sortBy', 'created_at')
        sort_order = request.GET.get('sortOrder', 'desc')
        
        if sort_order == 'desc':
            sort_by = f'-{sort_by}'
        
        standard_trading_accounts = standard_trading_accounts.order_by(sort_by)
        
        paginator = PageNumberPagination()
        paginator.page_size = request.GET.get('pageSize', 10)
        result_page = paginator.paginate_queryset(standard_trading_accounts, request)
        
        serializer = TradingAccountSerializer(result_page, many=True)
        return paginator.get_paginated_response(serializer.data)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_user_documents(request, user_id):
    try:
        user = CustomUser.objects.get(user_id=user_id)
        data = {
            'id_proof': user.id_proof.url if user.id_proof else None,
            'address_proof': user.address_proof.url if user.address_proof else None,
            'id_proof_verified': user.id_proof_verified,
            'address_proof_verified': user.address_proof_verified,
        }
        
        return Response(data, status=status.HTTP_200_OK)
    except CustomUser.DoesNotExist:
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
    
@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
@parser_classes((MultiPartParser,))
def upload_document(request):
    """Upload a document for a user."""
    # Debug logging
    import logging
    logger = logging.getLogger(__name__)
    logger.debug(f"upload_document called - User: {request.user}, Authenticated: {request.user.is_authenticated}")
    user_id = request.POST.get('user_id')
    document_type = request.POST.get('document_type')
    file = request.FILES.get('file')
    
    # Try to use shared validation helper to deeply verify images/PDFs
    try:
        from clientPanel.views.views import validate_upload_file
    except Exception:
        validate_upload_file = None

    if validate_upload_file is not None:
        is_valid, validation_err = validate_upload_file(file, max_size_mb=2)
        if not is_valid:
            return Response({"error": f"Invalid file: {validation_err}"}, status=status.HTTP_400_BAD_REQUEST)

    if not document_type or document_type.upper() not in ['ID', 'ADDRESS']:
        return Response(
            {"error": "Invalid document type. Must be 'ID' or 'Address'."},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not file:
        return Response(
            {"error": "No file provided."}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    # If helper wasn't available, perform basic size/type checks as fallback
    if validate_upload_file is None:
        if file.size > 2 * 1024 * 1024:  
            return Response(
                {"error": "File size exceeds 2 MB."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if file.content_type not in ['image/jpeg', 'image/png', 'application/pdf']:
            return Response(
                {"error": "Invalid file type. Only JPEG, PNG, and PDF are allowed."},
                status=status.HTTP_400_BAD_REQUEST
            )

    try:
        user = CustomUser.objects.get(user_id=user_id)

        # Map admin document types to client document types
        doc_type = 'identity' if document_type.upper() == 'ID' else 'residence'
        
        # Create or update UserDocument
        user_document, created = UserDocument.objects.get_or_create(
            user=user,
            document_type=doc_type,
            defaults={'status': 'pending'}
        )

        # Update document and reset status to pending
        if not created and user_document.document:
            # Delete old document file
            try_delete_file(user_document.document)
        
        user_document.document = file
        user_document.status = 'pending'
        user_document.save()

        # For backward compatibility, also update CustomUser fields
        if doc_type == 'identity':
            if user.id_proof:
                try_delete_file(user.id_proof)
            user.id_proof = file
            user.id_proof_verified = False
        else:
            if user.address_proof:
                try_delete_file(user.address_proof)
            user.address_proof = file
            user.address_proof_verified = False
        user.save()

        ActivityLog.objects.create(
            user=request.user,
            activity=f"Uploaded {document_type} document for user ID {user_id}",
            ip_address=get_client_ip(request),
            endpoint=request.path,
            activity_type="create",
            activity_category="management",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=user_document.id,
            related_object_type="UserDocument"
        )

        return Response({
            "message": "Document uploaded successfully.",
            "status": "pending",
            "document_type": doc_type,
            "document_url": user_document.document.url
        }, status=status.HTTP_201_CREATED)

    except CustomUser.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error uploading document: {str(e)}", exc_info=True)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def verify_document(request, document_type):
    if document_type.lower() not in ['id', 'address']:
        return Response(
            {"error": "Invalid 'document_type'. Use 'ID' or 'Address'."},
            status=status.HTTP_400_BAD_REQUEST
        )
    user_id = request.data.get("user_id")
    
    if not user_id:
        return Response({"error": "Missing 'user_id' in request."}, 
                      status=status.HTTP_400_BAD_REQUEST)

    try:
        user = CustomUser.objects.get(user_id=user_id)
        
        # Map admin document types to client document types
        doc_type = 'identity' if document_type.lower() == 'id' else 'residence'

        # Update UserDocument status
        try:
            user_document = UserDocument.objects.get(user=user, document_type=doc_type)
            user_document.status = 'approved'
            user_document.save()
        except UserDocument.DoesNotExist:
            return Response(
                {"error": f"No {doc_type} document found for user."},
                status=status.HTTP_404_NOT_FOUND
            )

        # For backward compatibility, also update CustomUser fields
        if doc_type == 'identity':
            user.id_proof_verified = True
        else:
            user.address_proof_verified = True
        user.save()

        ActivityLog.objects.create(
            user=request.user,
            activity=f"Verified {document_type} document for user {user.email}",
            ip_address=get_client_ip(request),
            endpoint=request.path,
            activity_type="update",
            activity_category="management",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=user_document.id,
            related_object_type="UserDocument"
        )

        return Response({
            "message": f"{document_type} document verified successfully.",
            "document_type": doc_type,
            "status": "approved",
            "document_url": user_document.document.url
        }, status=status.HTTP_200_OK)

    except CustomUser.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
               
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def user_verification_status(request, user_id):
    try:
        user = CustomUser.objects.get(user_id=user_id)
        serializer = UserVerificationStatusSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except CustomUser.DoesNotExist:
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
    
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def trading_accounts_by_user(request, user_id):
    try:
        trading_accounts = TradingAccount.objects.filter(user__user_id=user_id, account_type='standard')
        serializer = TradingAccountSerializer(trading_accounts, many=True)
        return Response({'tradingAccounts': serializer.data}, status=status.HTTP_200_OK)
    except TradingAccount.DoesNotExist:
        return Response({"error": "No trading accounts found for this user."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
class UserProfileView(RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticatedUser]

    def get_object(self):
        user_id = self.kwargs.get("user_id")
        try:
            return CustomUser.objects.get(user_id=user_id)
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

    def put(self, request, *args, **kwargs):
        user = self.get_object()
        
        # Handle IB and manager assignments if present in request
        if 'ib_id' in request.data or 'manager_id' in request.data:
            try:
                with transaction.atomic():
                    changes_made = []
                    
                    # Handle IB assignment
                    new_ib_id = request.data.get('ib_id')
                    if new_ib_id is not None:  # None means no change requested
                        old_ib = user.parent_ib
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
                            
                            user.parent_ib = new_ib
                            changes_made.append(f"IB changed from {old_ib.email if old_ib else 'None'} to {new_ib.email}")
                        else:
                            # Remove IB
                            user.parent_ib = None
                            changes_made.append(f"IB removed (was {old_ib.email if old_ib else 'None'})")

                    # Handle manager assignment
                    new_manager_id = request.data.get('manager_id')
                    if new_manager_id is not None:  # None means no change requested
                        old_manager = user.manager
                        if new_manager_id:  # If not empty/null/0
                            # Assign new manager
                            new_manager = get_object_or_404(CustomUser, user_id=new_manager_id)
                            
                            # Validate that the new manager has manager status
                            if not new_manager.MAM_manager_status:
                                return Response(
                                    {"error": "Selected user is not a manager"},
                                    status=status.HTTP_400_BAD_REQUEST
                                )
                            
                            user.manager = new_manager
                            changes_made.append(f"Manager changed from {old_manager.email if old_manager else 'None'} to {new_manager.email}")
                        else:
                            # Remove manager
                            user.manager = None
                            changes_made.append(f"Manager removed (was {old_manager.email if old_manager else 'None'})")

                    user.save()

                    # Log the activity
                    ActivityLog.objects.create(
                        user=request.user,
                        activity=f"Modified client {user.email} assignments: {', '.join(changes_made)}",
                        activity_type='update',
                        activity_category='management',
                        ip_address=get_client_ip(request),
                        endpoint=request.path,
                        user_agent=request.META.get("HTTP_USER_AGENT", ""),
                        timestamp=timezone.now(),
                        related_object_id=user.id,
                        related_object_type="User Profile"
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
        
        # Handle regular profile updates
        serializer = self.get_serializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Updated profile for user ID {user.user_id}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=user.id,
                related_object_type="User Profile"
            )

            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_bank_crypto_details(request, user_id):
    response_data = {
        "status": "success",
        "bankDetails": None,
        "bankDetailsMessage": "Bank details not found.",
        "cryptoDetails": None,
        "cryptoDetailsMessage": "Crypto details not found.",
    }

    
    try:
        bank_details = BankDetails.objects.get(user__user_id=user_id)
        bank_serializer = BankDetailsSerializer(bank_details)
        response_data["bankDetails"] = bank_serializer.data
        response_data["bankDetailsMessage"] = "Bank details retrieved successfully."
    except BankDetails.DoesNotExist:
        logger.info("Bank details not found for user_id: %s", user_id)

    
    try:
        crypto_details = CryptoDetails.objects.get(user__user_id=user_id)
        crypto_serializer = CryptoDetailsSerializer(crypto_details)
        response_data["cryptoDetails"] = crypto_serializer.data
        response_data["cryptoDetailsMessage"] = "Crypto details retrieved successfully."
    except CryptoDetails.DoesNotExist:
        logger.info("Crypto details not found for user_id: %s", user_id)

    
    if response_data["bankDetails"] is None and response_data["cryptoDetails"] is None:
        response_data["status"] = "not found"
        response_data["error"] = "Both bank and crypto details not found."

    logger.debug("Response data for user_id %s: %s", user_id, response_data)
    return Response(response_data, status=status.HTTP_200_OK)

@api_view(['PUT'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def update_bank_crypto_details(request, user_id):
    response_data = {
        "bankDetails": None,
        "cryptoDetails": None,
        "bankDetailsErrors": None,
        "cryptoDetailsErrors": None,
        "status":200,
    }
    status_code = status.HTTP_200_OK

    try:
        user = CustomUser.objects.get(user_id=user_id)
    except CustomUser.DoesNotExist:
        response_data["error"] = f"User with user_id {user_id} does not exist."
        status_code = status.HTTP_400_BAD_REQUEST
        return Response(response_data, status=status_code)

    bank_data = {
        "bank_name": request.data.get('bankDetails.bankName'),
        "account_number": request.data.get('bankDetails.accountNumber'),
        "branch": request.data.get('bankDetails.branch'),
        "ifsc_code": request.data.get('bankDetails.ifscCode'),
    }
    
    crypto_data = {
        "wallet_address": request.data.get('cryptoDetails.walletAddress'),
        "exchange_name": request.data.get('cryptoDetails.exchangeName'),
    }

    if bank_data["bank_name"]:
        bank_details, created = BankDetails.objects.get_or_create(user=user)
        bank_serializer = BankDetailsSerializer(bank_details, data=bank_data, partial=True)
        if bank_serializer.is_valid():
            bank_serializer.save()
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
                related_object_type="Bank Details"
            )
            response_data["bankDetails"] = bank_serializer.data
        else:
            response_data["bankDetailsErrors"] = bank_serializer.errors

    if crypto_data["wallet_address"]:
        crypto_details, created = CryptoDetails.objects.get_or_create(user=user)
        crypto_serializer = CryptoDetailsSerializer(crypto_details, data=crypto_data, partial=True)
        if crypto_serializer.is_valid():
            crypto_serializer.save()
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Updated crypto details for user ID {user_id}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=user.id,
                related_object_type="Crypto Details"
            )
            response_data["cryptoDetails"] = crypto_serializer.data
        else:
            response_data["cryptoDetailsErrors"] = crypto_serializer.errors

    
    if not response_data["bankDetails"] and not response_data["cryptoDetails"]:
        status_code = status.HTTP_400_BAD_REQUEST
        response_data["error"] = "Failed to create or update bank and crypto details."

    return Response(response_data, status=status_code)

@api_view(['GET'])
@permission_classes([IsAdmin])
def get_user_status(request, user_id):
    try:
        user = CustomUser.objects.get(user_id=user_id)
        current_status = user.manager_admin_status
        all_statuses = [
            'None', 'Admin', 'Manager'
        ]
        available_levels = [status for status in all_statuses if status != current_status]
        response_data = {
            'status': current_status,
            'available_levels': available_levels
        }
        return Response(response_data, status=200)
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found.'}, status=404)
    
@api_view(['POST'])
@permission_classes([IsAdmin])
def update_user_status(request):
    user_id = request.data.get('userId')
    new_status = request.data.get('newStatus')
    role_statuses = ['None', 'Admin', 'Manager']

    if new_status not in role_statuses:
        return Response({'error': 'Invalid status provided.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        user = CustomUser.objects.get(user_id=user_id)
        if user.manager_admin_status == new_status:
            return Response({'message': 'User is already at this status.'}, status=status.HTTP_400_BAD_REQUEST)
        user.manager_admin_status = new_status
        
            
        user.save()
        ActivityLog.objects.create(
            user=request.user,
            activity=f"Updated status for user ID {user_id} to {new_status}",
            ip_address=get_client_ip(request),
            endpoint=request.path,
            activity_type="update",
            activity_category="management",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=user.id,
            related_object_type="User Status"
        )

        return Response({
            'message': 'User status updated successfully!',
            'newStatus': new_status
        }, status=status.HTTP_200_OK)

    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to update status: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def get_user_active_status(request, user_id):
    try:
        user = CustomUser.objects.get(user_id=user_id)
        return Response({"status": "enabled" if user.is_active else "disabled"}, status=200)
    except CustomUser.DoesNotExist:
        return Response({"error": "User not found"}, status=404)

@api_view(['POST'])
@permission_classes([IsAdmin])
def toggle_user_status(request, user_id):
    try:
        user = CustomUser.objects.get(user_id=user_id)
        
        user.is_active = not user.is_active
        user.save()
        ActivityLog.objects.create(
            user=request.user,
            activity=f"Toggled user ID {user_id} status to {'enabled' if user.is_active else 'disabled'}",
            ip_address=get_client_ip(request),
            endpoint=request.path,
            activity_type="update",
            activity_category="management",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=user.id,
            related_object_type="User"
        )

        new_status = "enabled" if user.is_active else "disabled"
        return Response({"status": new_status, "message": f"User {new_status} successfully!"}, status=200)
    except CustomUser.DoesNotExist:
        return Response({"error": "User not found"}, status=404)


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def update_demo_account(request):
    """Update demo account balance or leverage"""
    try:
        data = request.data
        account_id = data.get('account_id')
        balance = data.get('balance')
        leverage = data.get('leverage')
        
        if not account_id:
            return Response({"success": False, "error": "Account ID is required"}, status=400)
            
        # Get the demo account
        try:
            demo_account = DemoAccount.objects.get(account_id=account_id, user=request.user)
        except DemoAccount.DoesNotExist:
            return Response({"success": False, "error": "Demo account not found"}, status=404)
        
        # Import MT5 services
        from adminPanel.mt5.services import get_manager_instance
        manager = get_manager_instance()
        
        if not manager:
            return Response({"success": False, "error": "MT5 connection failed"}, status=500)
            
        results = []
        
        # Update balance if provided
        if balance is not None:
            try:
                balance = float(balance)
                
                # Get current balance to calculate difference
                current_user = manager.manager.UserGet(int(account_id))
                if current_user:
                    current_balance = current_user.Balance
                    balance_diff = balance - current_balance
                    
                    if balance_diff > 0:
                        # Deposit the difference
                        if manager.deposit_funds(int(account_id), balance_diff, "Balance adjustment via frontend"):
                            demo_account.balance = balance
                            demo_account.save()
                            results.append(f"Balance updated to ${balance}")
                            
                            ActivityLog.objects.create(
                                user=request.user,
                                activity=f"Updated demo account {account_id} balance to ${balance}",
                                ip_address=get_client_ip(request),
                                endpoint=request.path,
                                activity_type="update",
                                activity_category="trading",
                                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                                timestamp=timezone.now(),
                                related_object_id=demo_account.id,
                                related_object_type="DemoAccount"
                            )
                        else:
                            results.append("Failed to update balance in MT5")
                    elif balance_diff < 0:
                        # Withdraw the difference
                        if manager.withdraw_funds(int(account_id), abs(balance_diff), "Balance adjustment via frontend"):
                            demo_account.balance = balance
                            demo_account.save()
                            results.append(f"Balance updated to ${balance}")
                            
                            ActivityLog.objects.create(
                                user=request.user,
                                activity=f"Updated demo account {account_id} balance to ${balance}",
                                ip_address=get_client_ip(request),
                                endpoint=request.path,
                                activity_type="update",
                                activity_category="trading",
                                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                                timestamp=timezone.now(),
                                related_object_id=demo_account.id,
                                related_object_type="DemoAccount"
                            )
                        else:
                            results.append("Failed to update balance in MT5")
                    else:
                        results.append("Balance is already at the target amount")
                else:
                    results.append("Failed to get current balance from MT5")
                    
            except ValueError:
                results.append("Invalid balance value")
            except Exception as e:
                logger.error(f"Error updating balance: {str(e)}")
                results.append(f"Balance update failed: {str(e)}")
        
        # Update leverage if provided
        if leverage is not None:
            try:
                leverage = int(leverage)
                if manager.change_leverage(int(account_id), leverage):
                    demo_account.leverage = leverage
                    demo_account.save()
                    results.append(f"Leverage updated to {leverage}")
                    
                    ActivityLog.objects.create(
                        user=request.user,
                        activity=f"Updated demo account {account_id} leverage to {leverage}",
                        ip_address=get_client_ip(request),
                        endpoint=request.path,
                        activity_type="update",
                        activity_category="trading",
                        user_agent=request.META.get("HTTP_USER_AGENT", ""),
                        timestamp=timezone.now(),
                        related_object_id=demo_account.id,
                        related_object_type="DemoAccount"
                    )
                else:
                    results.append("Failed to update leverage in MT5")
                    
            except ValueError:
                results.append("Invalid leverage value")
            except Exception as e:
                logger.error(f"Error updating leverage: {str(e)}")
                results.append(f"Leverage update failed: {str(e)}")
        
        if results:
            return Response({
                "success": True, 
                "message": "; ".join(results),
                "account_id": account_id,
                "balance": demo_account.balance,
                "leverage": demo_account.leverage
            })
        else:
            return Response({"success": False, "error": "No updates provided"}, status=400)
            
    except Exception as e:
        logger.error(f"Error in update_demo_account: {str(e)}")
        return Response({"success": False, "error": str(e)}, status=500)

