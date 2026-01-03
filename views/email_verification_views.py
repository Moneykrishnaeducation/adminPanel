"""
Email-based verification views for optimized document verification system
"""

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone
import logging

from adminPanel.models import CustomUser
from clientPanel.models import UserDocument
from adminPanel.permissions import IsAdmin, IsManager
from .views import get_client_ip
from adminPanel.models import ActivityLog

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(['GET'])
@authentication_classes([JWTAuthentication, TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_verification_status_by_email(request, email):
    """
    Get comprehensive verification status for a user by email address
    Optimized for faster lookup using email indexes
    """
    try:
        # Validate email
        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"error": "Invalid email format"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check permissions
        if (request.user.email != email and 
            not (hasattr(request.user, 'role') and 
                 request.user.role in ['admin', 'manager'])):
            return Response(
                {"error": "Permission denied"}, 
                status=status.HTTP_403_FORBIDDEN
            )

        # Get user by email
        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "User not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Optimized document query using email index
        documents = UserDocument.objects.filter(
            user_email=email
        ).select_related('user').order_by('document_type')
        
        document_status = {}
        
        for doc in documents:
            document_status[doc.document_type] = {
                'id': doc.id,
                'status': doc.status,
                'uploaded_at': doc.uploaded_at.isoformat() if doc.uploaded_at else None,
                'verified_at': doc.verified_at.isoformat() if doc.verified_at else None,
                'file_url': doc.document.url if doc.document else None,
                'file_name': doc.document.name if doc.document else None,
                'mime_type': doc.mime_type
            }
        
        # Ensure both document types are represented
        for doc_type in ['identity', 'residence']:
            if doc_type not in document_status:
                document_status[doc_type] = {
                    'status': 'not_uploaded',
                    'uploaded_at': None,
                    'verified_at': None,
                    'file_url': None,
                    'file_name': None,
                    'mime_type': None
                }

        # Calculate overall verification status
        overall_verified = (
            document_status.get('identity', {}).get('status') == 'approved' and
            document_status.get('residence', {}).get('status') == 'approved'
        )

        verification_data = {
            'user_id': user.user_id,
            'username': user.username,
            'email': user.email,
            'overall_verified': overall_verified,
            'documents': document_status,
            'legacy_fields': {
                'id_proof_verified': getattr(user, 'id_proof_verified', False),
                'address_proof_verified': getattr(user, 'address_proof_verified', False),
                'id_proof_url': user.id_proof.url if getattr(user, 'id_proof', None) else None,
                'address_proof_url': user.address_proof.url if getattr(user, 'address_proof', None) else None
            },
            'verification_summary': {
                'total_documents': len(documents),
                'verified_documents': sum(1 for doc in documents if doc.status == 'approved'),
                'pending_documents': sum(1 for doc in documents if doc.status == 'pending'),
                'rejected_documents': sum(1 for doc in documents if doc.status == 'rejected'),
            }
        }
        
        return Response(verification_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting verification status by email: {e}", exc_info=True)
        return Response(
            {"error": "Internal server error", "details": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(['POST'])
@authentication_classes([JWTAuthentication, TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def update_verification_status_by_email(request, email):
    """
    Update verification status for a user by email address
    Optimized for faster lookup using email indexes
    """
    try:
        # Validate email
        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"error": "Invalid email format"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check admin permissions
        if not (hasattr(request.user, 'role') and 
                request.user.role in ['admin', 'manager']):
            return Response(
                {"error": "Admin or Manager access required"}, 
                status=status.HTTP_403_FORBIDDEN
            )

        # Get user by email
        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "User not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )

        document_type = request.data.get('document_type')
        action = request.data.get('action')  # approve, reject, reset
        
        if document_type not in ['identity', 'residence']:
            return Response(
                {"error": "Invalid document_type. Use 'identity' or 'residence'."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if action not in ['approve', 'reject', 'reset']:
            return Response(
                {"error": "Invalid action. Use 'approve', 'reject', or 'reset'."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Optimized document lookup using email index
        try:
            user_document = UserDocument.objects.get(
                user_email=email, 
                document_type=document_type
            )
            
            if action == 'approve':
                user_document.status = 'approved'
                user_document.verified_at = timezone.now()
                status_text = "approved"
            elif action == 'reject':
                user_document.status = 'rejected'
                user_document.verified_at = None
                status_text = "rejected"
            else:  # reset
                user_document.status = 'pending'
                user_document.verified_at = None
                status_text = "reset to pending"

            user_document.save()

            # Update legacy CustomUser fields for backward compatibility
            if document_type == 'identity':
                user.id_proof_verified = (action == 'approve')
            elif document_type == 'residence':
                user.address_proof_verified = (action == 'approve')

            user.save()

            # Log activity
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Document {document_type} {status_text} for user {email}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="update",
                activity_category="verification",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=user_document.id,
                related_object_type="UserDocument"
            )

            return Response({
                "message": f"Document {document_type} {status_text} successfully",
                "document_type": document_type,
                "status": user_document.status,
                "user_email": email,
                "verified_at": user_document.verified_at.isoformat() if user_document.verified_at else None
            }, status=status.HTTP_200_OK)

        except UserDocument.DoesNotExist:
            return Response(
                {"error": f"No {document_type} document found for user {email}"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
    except Exception as e:
        logger.error(f"Error updating verification status by email: {e}", exc_info=True)
        return Response(
            {"error": "Internal server error", "details": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(['POST'])
@authentication_classes([JWTAuthentication, TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def bulk_verification_update_by_email(request):
    """
    Update multiple verification statuses at once using email addresses
    Admin-only functionality with optimized email-based lookups
    """
    try:
        # Check admin permissions
        if not (hasattr(request.user, 'role') and 
                request.user.role in ['admin', 'manager']):
            return Response(
                {"error": "Admin or Manager access required"}, 
                status=status.HTTP_403_FORBIDDEN
            )

        updates = request.data.get('updates', [])
        
        if not updates:
            return Response(
                {"error": "No updates provided"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        results = []
        
        for update in updates:
            try:
                email = update.get('email')
                document_type = update.get('document_type')
                action = update.get('action')
                
                # Validate email
                try:
                    validate_email(email)
                except ValidationError:
                    results.append({
                        'email': email,
                        'document_type': document_type,
                        'action': action,
                        'status': 'error',
                        'message': 'Invalid email format'
                    })
                    continue

                # Get user and document using email optimization
                user = CustomUser.objects.get(email=email)
                user_document = UserDocument.objects.get(
                    user_email=email, 
                    document_type=document_type
                )
                
                if action == 'approve':
                    user_document.status = 'approved'
                    user_document.verified_at = timezone.now()
                elif action == 'reject':
                    user_document.status = 'rejected'
                    user_document.verified_at = None
                else:  # reset
                    user_document.status = 'pending'
                    user_document.verified_at = None
                
                user_document.save()
                
                # Update legacy fields
                if document_type == 'identity':
                    user.id_proof_verified = (action == 'approve')
                elif document_type == 'residence':
                    user.address_proof_verified = (action == 'approve')
                
                user.save()
                
                # Log activity
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Bulk update: Document {document_type} {action} for user {email}",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="bulk_update",
                    activity_category="verification",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=user_document.id,
                    related_object_type="UserDocument"
                )
                
                results.append({
                    'email': email,
                    'document_type': document_type,
                    'action': action,
                    'status': 'success'
                })
                
            except Exception as e:
                results.append({
                    'email': update.get('email'),
                    'document_type': update.get('document_type'),
                    'action': update.get('action'),
                    'status': 'error',
                    'message': str(e)
                })
        
        return Response({
            'message': f'Processed {len(results)} updates',
            'results': results
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error in bulk verification update by email: {e}", exc_info=True)
        return Response(
            {"error": "Internal server error", "details": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )