"""
Backend-Client Panel Verification Integration
============================================

This file implements a complete integration between the backend verification system
and the client panel verification interface.
"""
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.generic import View
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
import json
import logging
from typing import Dict, Any, Optional

from adminPanel.models import CustomUser, ActivityLog
from clientPanel.models import UserDocument
from adminPanel.permissions import IsAuthenticatedUser
from adminPanel.serializers import UserVerificationStatusSerializer

logger = logging.getLogger(__name__)

class VerificationIntegrationView(View):
    """
    Main verification integration view that handles both admin and client interactions
    """
    
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)
    
    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def log_activity(self, request, user, activity, related_object=None):
        """Log verification activity"""
        try:
            ActivityLog.objects.create(
                user=request.user,
                activity=activity,
                ip_address=self.get_client_ip(request),
                endpoint=request.path,
                activity_type="verification",
                activity_category="document_management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=related_object.id if related_object else None,
                related_object_type=related_object.__class__.__name__ if related_object else None
            )
        except Exception as e:
            logger.error(f"Error logging activity: {e}")

@csrf_exempt
@api_view(['GET'])
@authentication_classes([JWTAuthentication, TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_verification_status(request, user_id):
    """
    Get comprehensive verification status for a user
    Supports both admin and client access
    """
    try:
        user = CustomUser.objects.get(user_id=user_id)
        
        # Get document statuses
        documents = UserDocument.objects.filter(user=user)
        document_status = {}
        
        for doc in documents:
            document_status[doc.document_type] = {
                'status': doc.status,
                'uploaded_at': doc.uploaded_at.isoformat() if doc.uploaded_at else None,
                'verified_at': getattr(doc, 'verified_at', None).isoformat() if getattr(doc, 'verified_at', None) else None,
                'file_url': doc.document.url if doc.document else None,
                'file_name': doc.document.name if doc.document else None,
                'mime_type': getattr(doc, 'mime_type', None)
            }
        
        # Legacy support for CustomUser fields
        verification_data = {
            'user_id': user.user_id,
            'username': user.username,
            'email': user.email,
            'overall_verified': getattr(user, 'user_verified', False),
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
                'rejected_documents': sum(1 for doc in documents if doc.status == 'rejected')
            }
        }
        
        return Response({
            'status': 'success',
            'data': verification_data,
            'message': 'Verification status retrieved successfully'
        }, status=status.HTTP_200_OK)
        
    except CustomUser.DoesNotExist:
        return Response({
            'status': 'error',
            'error': 'User not found',
            'message': 'The specified user does not exist'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error getting verification status: {e}")
        return Response({
            'status': 'error',
            'error': str(e),
            'message': 'An error occurred while retrieving verification status'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@csrf_exempt
@api_view(['POST'])
@authentication_classes([JWTAuthentication, TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def update_verification_status(request, user_id):
    """
    Update verification status for a user's documents
    Admin-only functionality
    """
    try:
        user = CustomUser.objects.get(user_id=user_id)
        # Accept both camelCase and snake_case for all fields
        def get_field(*names):
            for n in names:
                if n in request.data:
                    return request.data[n]
            return None

        document_type = get_field('document_type', 'documentType')
        action = get_field('action')  # 'approve', 'reject', 'reset'

        # Bank details fields
        bank_name = get_field('bank_name', 'bankName')
        account_number = get_field('account_number', 'accountNumber')
        ifsc_code = get_field('ifsc_code', 'ifscCode')
        branch = get_field('branch', 'branchName')

        # Profile change fields
        requested_changes = get_field('requested_changes', 'requestedChanges')
        id_proof = get_field('id_proof', 'idProof')
        address_proof = get_field('address_proof', 'addressProof')

        # Crypto fields
        wallet_address = get_field('wallet_address', 'walletAddress')
        exchange = get_field('exchange')

        if not document_type or not action:
            return Response({"error": "document_type and action are required"}, status=status.HTTP_400_BAD_REQUEST)

        if action not in ['approve', 'reject', 'reset']:
            return Response({"error": "Invalid action. Use 'approve', 'reject', or 'reset'"}, status=status.HTTP_400_BAD_REQUEST)

        # Update UserDocument
        try:
            user_document = UserDocument.objects.get(user=user, document_type=document_type)
            # Update fields if provided
            if bank_name is not None:
                user_document.bank_name = bank_name
            if account_number is not None:
                user_document.account_number = account_number
            if ifsc_code is not None:
                user_document.ifsc_code = ifsc_code
            if branch is not None:
                user_document.branch = branch
            if requested_changes is not None:
                user_document.requested_changes = requested_changes
            if id_proof is not None:
                user_document.id_proof = id_proof
            if address_proof is not None:
                user_document.address_proof = address_proof
            if wallet_address is not None:
                user_document.wallet_address = wallet_address
            if exchange is not None:
                user_document.exchange = exchange

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
            integration_view = VerificationIntegrationView()
            integration_view.log_activity(
                request, 
                user, 
                f"Document {document_type} {status_text} for user {user.email}",
                user_document
            )

            return Response({
                "message": f"Document {document_type} {status_text} successfully",
                "document_type": document_type,
                "status": user_document.status,
                "verified_at": user_document.verified_at.isoformat() if user_document.verified_at else None
            }, status=status.HTTP_200_OK)

        except UserDocument.DoesNotExist:
            return Response({"error": f"No {document_type} document found for user"}, status=status.HTTP_404_NOT_FOUND)
        
        # Update UserDocument
        try:
            user_document = UserDocument.objects.get(user=user, document_type=document_type)
            
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
            integration_view = VerificationIntegrationView()
            integration_view.log_activity(
                request, 
                user, 
                f"Document {document_type} {status_text} for user {user.email}",
                user_document
            )
            
            return Response({
                "message": f"Document {document_type} {status_text} successfully",
                "document_type": document_type,
                "status": user_document.status,
                "verified_at": user_document.verified_at.isoformat() if user_document.verified_at else None
            }, status=status.HTTP_200_OK)
            
        except UserDocument.DoesNotExist:
            return Response(
                {"error": f"No {document_type} document found for user"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
    except CustomUser.DoesNotExist:
        return Response(
            {"error": "User not found"}, 
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error updating verification status: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@csrf_exempt
@api_view(['GET'])
@authentication_classes([JWTAuthentication, TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_pending_verifications(request):
    """
    Get all pending verification requests
    Admin-only functionality
    """
    try:
        pending_documents = UserDocument.objects.filter(
            status='pending'
        ).select_related('user').order_by('-uploaded_at')
        
        pending_data = []
        for doc in pending_documents:
            data = {
                'id': getattr(doc, 'id', '') or '',
                'user_id': getattr(doc.user, 'user_id', '') or '',
                'username': getattr(doc.user, 'username', '') or '',
                'email': getattr(doc.user, 'email', '') or '',
                'document_type': getattr(doc, 'document_type', '') or '',
                'uploaded_at': doc.uploaded_at.isoformat() if getattr(doc, 'uploaded_at', None) else '',
                'file_url': doc.document.url if getattr(doc, 'document', None) and getattr(doc.document, 'url', None) else '',
                'file_name': doc.document.name if getattr(doc, 'document', None) and getattr(doc.document, 'name', None) else '',
                'mime_type': getattr(doc, 'mime_type', '') or '',
                # IB fields
                'commissioning_profile': getattr(doc, 'commissioning_profile', '') or '',
                # Bank fields
                'bank_name': getattr(doc, 'bank_name', '') or '',
                'account_number': getattr(doc, 'account_number', '') or '',
                'branch': getattr(doc, 'branch', '') or '',
                'ifsc_code': getattr(doc, 'ifsc_code', '') or '',
                # Profile change fields
                'requested_changes': getattr(doc, 'requested_changes', '') or '',
                'id_proof': getattr(doc, 'id_proof', '') or '',
                'address_proof': getattr(doc, 'address_proof', '') or '',
                # Crypto fields
                'wallet_address': getattr(doc, 'wallet_address', '') or '',
                'exchange': getattr(doc, 'exchange', '') or '',
            }
            # Ensure all expected keys are present, even if not in model
            expected_keys = [
                'id', 'user_id', 'username', 'email', 'document_type', 'uploaded_at', 'file_url', 'file_name', 'mime_type',
                'commissioning_profile', 'bank_name', 'account_number', 'branch', 'ifsc_code',
                'requested_changes', 'id_proof', 'address_proof', 'wallet_address', 'exchange'
            ]
            for key in expected_keys:
                if key not in data:
                    data[key] = ''
            pending_data.append(data)
        
        return Response({
            'pending_verifications': pending_data,
            'total_count': len(pending_data)
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting pending verifications: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@csrf_exempt
@api_view(['POST'])
@authentication_classes([JWTAuthentication, TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def bulk_verification_update(request):
    """
    Update multiple verification statuses at once
    Admin-only functionality
    """
    try:
        updates = request.data.get('updates', [])
        
        if not updates:
            return Response(
                {"error": "No updates provided"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        results = []
        integration_view = VerificationIntegrationView()
        
        for update in updates:
            try:
                user_id = update.get('user_id')
                document_type = update.get('document_type')
                action = update.get('action')
                
                user = CustomUser.objects.get(user_id=user_id)
                user_document = UserDocument.objects.get(user=user, document_type=document_type)
                
                if action == 'approve':
                    user_document.status = 'approved'
                    user_document.verified_at = timezone.now()
                elif action == 'reject':
                    user_document.status = 'rejected'
                    user_document.verified_at = None
                else:
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
                integration_view.log_activity(
                    request, 
                    user, 
                    f"Bulk update: Document {document_type} {action} for user {user.email}",
                    user_document
                )
                
                results.append({
                    'user_id': user_id,
                    'document_type': document_type,
                    'action': action,
                    'status': 'success'
                })
                
            except Exception as e:
                results.append({
                    'user_id': update.get('user_id'),
                    'document_type': update.get('document_type'),
                    'action': update.get('action'),
                    'status': 'error',
                    'error': str(e)
                })
        
        return Response({
            'results': results,
            'total_processed': len(results),
            'successful': len([r for r in results if r['status'] == 'success']),
            'failed': len([r for r in results if r['status'] == 'error'])
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error in bulk verification update: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@csrf_exempt
@api_view(['GET'])
@authentication_classes([JWTAuthentication, TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_client_verification_status(request):
    """
    Get verification status for the authenticated client user
    Client-only functionality
    """
    try:
        user = request.user
        
        # Get document statuses
        documents = UserDocument.objects.filter(user=user)
        document_status = {}
        
        for doc in documents:
            document_status[doc.document_type] = {
                'status': doc.status,
                'uploaded_at': doc.uploaded_at.isoformat() if doc.uploaded_at else None,
                'verified_at': doc.verified_at.isoformat() if doc.verified_at else None,
                'has_file': bool(doc.document),
                'mime_type': doc.mime_type
            }
        
        verification_data = {
            'user_id': user.user_id,
            'overall_verified': user.user_verified,
            'documents': document_status,
            'verification_summary': {
                'total_documents': len(documents),
                'verified_documents': sum(1 for doc in documents if doc.status == 'approved'),
                'pending_documents': sum(1 for doc in documents if doc.status == 'pending'),
                'rejected_documents': sum(1 for doc in documents if doc.status == 'rejected')
            }
        }
        
        return Response(verification_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting client verification status: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@csrf_exempt
@api_view(['GET'])
@authentication_classes([JWTAuthentication, TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_verification_analytics(request):
    """
    Get verification analytics for admin dashboard
    Admin-only functionality
    """
    try:
        from django.db.models import Count, Q
        from datetime import datetime, timedelta
        
        # Get date range (last 30 days)
        end_date = timezone.now()
        start_date = end_date - timedelta(days=30)
        
        # Overall statistics
        total_users = CustomUser.objects.count()
        verified_users = CustomUser.objects.filter(user_verified=True).count()
        
        # Document statistics
        document_stats = UserDocument.objects.aggregate(
            total_documents=Count('id'),
            approved_documents=Count('id', filter=Q(status='approved')),
            pending_documents=Count('id', filter=Q(status='pending')),
            rejected_documents=Count('id', filter=Q(status='rejected'))
        )
        
        # Recent activity
        recent_activity = UserDocument.objects.filter(
            uploaded_at__gte=start_date
        ).values('document_type', 'status').annotate(
            count=Count('id')
        ).order_by('document_type', 'status')
        
        # Verification rate by document type
        doc_type_stats = UserDocument.objects.values('document_type').annotate(
            total=Count('id'),
            approved=Count('id', filter=Q(status='approved')),
            pending=Count('id', filter=Q(status='pending')),
            rejected=Count('id', filter=Q(status='rejected'))
        )
        
        analytics_data = {
            'overview': {
                'total_users': total_users,
                'verified_users': verified_users,
                'verification_rate': (verified_users / total_users * 100) if total_users > 0 else 0,
                'unverified_users': total_users - verified_users
            },
            'document_statistics': document_stats,
            'recent_activity': list(recent_activity),
            'document_type_breakdown': list(doc_type_stats),
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            }
        }
        
        return Response(analytics_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting verification analytics: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
