#!/usr/bin/env python3
"""
API views for managing client-to-IB assignments.
These endpoints allow admins to view and manage IB client assignments to parent IBs.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.shortcuts import get_object_or_404

from adminPanel.models import CustomUser
from adminPanel.permissions import IsAdmin
from adminPanel.utils.client_manager_assignment import (
    assign_ib_clients_to_manager,
    get_unassigned_ib_clients,
    assign_client_to_manager,
    get_manager_client_stats
)
import logging
from rest_framework.permissions import IsAuthenticated

logger = logging.getLogger(__name__)

@api_view(['POST'])
@permission_classes([IsAdmin])
def assign_manager_clients_api(request):
    """
    API endpoint to assign IB clients to a parent IB.
    
    POST data:
    {
        "parent_ib_email": "ib@example.com",
        "force_reassign": false  // optional, default false
    }
    """
    try:
        manager_email = request.data.get('parent_ib_email') or request.data.get('manager_email')
        force_reassign = request.data.get('force_reassign', False)
        
        if not manager_email:
            return Response({
                'error': 'parent_ib_email is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            parent_ib_user = CustomUser.objects.get(email=manager_email)
        except CustomUser.DoesNotExist:
            return Response({
                'error': f'IB user not found with email: {manager_email}'
            }, status=status.HTTP_404_NOT_FOUND)

        # Perform the assignment
        result = assign_ib_clients_to_manager(parent_ib_user, force_reassign)
        
        if 'error' in result:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({
            'success': True,
            'message': f'Successfully assigned {result["assigned"]} clients to parent IB {manager_email}',
            'data': result
        })
        
    except Exception as e:
        logger.error(f"Error in assign_manager_clients_api: {str(e)}")
        return Response({
            'error': f'An unexpected error occurred: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAdmin])
def manager_client_stats_api(request, manager_id=None):
    """
    API endpoint to get client assignment statistics for parent IBs.
    
    GET /api/admin/manager-client-stats/  # All parent IBs
    GET /api/admin/manager-client-stats/{manager_id}/  # Specific parent IB
    """
    try:
        if manager_id:
            # Get stats for specific IB user
            parent_ib_user = get_object_or_404(CustomUser, id=manager_id)
            stats = get_manager_client_stats(parent_ib_user)
            if 'error' in stats:
                return Response(stats, status=status.HTTP_400_BAD_REQUEST)
            return Response({
                'success': True,
                'data': stats
            })
        else:
            # Get stats for all IB users
            ib_users = CustomUser.objects.filter(IB_status=True)
            all_stats = []
            for ib_user in ib_users:
                ib_stats = get_manager_client_stats(ib_user)
                if 'error' not in ib_stats:
                    all_stats.append(ib_stats)
            total_unassigned = get_unassigned_ib_clients().count()
            total_ib_users = ib_users.count()
            return Response({
                'success': True,
                'summary': {
                    'total_ib_users': total_ib_users,
                    'total_unassigned_clients': total_unassigned
                },
                'data': all_stats
            })
            
    except Exception as e:
        logger.error(f"Error in manager_client_stats_api: {str(e)}")
        return Response({
            'error': f'An unexpected error occurred: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAdmin])
def assign_specific_client_api(request):
    """
    API endpoint to manually assign a specific client to a parent IB.
    
    POST data:
    {
        "client_email": "client@example.com",
        "parent_ib_email": "ib@example.com",
        "force_reassign": false  // optional, default false
    }
    """
    try:
        client_email = request.data.get('client_email')
        manager_email = request.data.get('parent_ib_email') or request.data.get('manager_email')
        force_reassign = request.data.get('force_reassign', False)
        
        if not client_email or not manager_email:
            return Response({
                'error': 'Both client_email and parent_ib_email are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            client_user = CustomUser.objects.get(email=client_email)
        except CustomUser.DoesNotExist:
            return Response({
                'error': f'Client not found with email: {client_email}'
            }, status=status.HTTP_404_NOT_FOUND)

        try:
            parent_ib_user = CustomUser.objects.get(email=manager_email)
        except CustomUser.DoesNotExist:
            return Response({
                'error': f'IB user not found with email: {manager_email}'
            }, status=status.HTTP_404_NOT_FOUND)

        # Set parent_ib and save
        client_user.parent_ib = parent_ib_user
        client_user.save(update_fields=['parent_ib'])

        # Optionally call assign_client_to_manager if you need more logic
        result = assign_client_to_manager(client_user, parent_ib_user, force_reassign)

        if not result['success']:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'success': True,
            'message': f'Successfully assigned client {client_email} to parent IB {manager_email}',
            'data': result
        })
        
    except Exception as e:
        logger.error(f"Error in assign_specific_client_api: {str(e)}")
        return Response({
            'error': f'An unexpected error occurred: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAdmin])
def unassigned_clients_api(request):
    """
    API endpoint to get all unassigned IB clients.
    
    Query parameters:
    - parent_ib_email: Get unassigned clients for specific parent IB only
    """
    try:
        manager_email = request.GET.get('parent_ib_email') or request.GET.get('manager_email')
        
        if manager_email:
            try:
                parent_ib_user = CustomUser.objects.get(email=manager_email)
                unassigned_clients = get_unassigned_ib_clients(parent_ib_user)
            except CustomUser.DoesNotExist:
                return Response({
                    'error': f'Parent IB not found with email: {manager_email}'
                }, status=status.HTTP_404_NOT_FOUND)
        else:
            unassigned_clients = get_unassigned_ib_clients()
        
        clients_data = []
        for client in unassigned_clients:
            clients_data.append({
                'id': client.id,
                'email': client.email,
                'user_id': client.user_id,
                'first_name': client.first_name,
                'last_name': client.last_name,
                'referral_code_used': client.referral_code_used,
                'parent_ib_email': client.parent_ib.email if client.parent_ib else None,
                'parent_ib_name': f"{client.parent_ib.first_name} {client.parent_ib.last_name}".strip() if client.parent_ib else None,
                'date_joined': client.date_joined.isoformat() if hasattr(client, 'date_joined') and client.date_joined else None
            })
        
        return Response({
            'success': True,
            'count': len(clients_data),
            'data': clients_data
        })
        
    except Exception as e:
        logger.error(f"Error in unassigned_clients_api: {str(e)}")
        return Response({
            'error': f'An unexpected error occurred: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAdmin])
def bulk_assign_clients_api(request):
    """
    API endpoint to bulk assign multiple clients to parent IBs.
    
    POST data:
    {
        "assignments": [
            {
                "client_email": "client1@example.com",
                "parent_ib_email": "ib1@example.com"
            },
            {
                "client_email": "client2@example.com", 
                "parent_ib_email": "ib2@example.com"
            }
        ],
        "force_reassign": false  // optional, default false
    }
    """
    try:
        assignments = request.data.get('assignments', [])
        force_reassign = request.data.get('force_reassign', False)
        
        if not assignments:
            return Response({
                'error': 'assignments list is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        results = []
        success_count = 0
        error_count = 0
        
        with transaction.atomic():
            for assignment in assignments:
                client_email = assignment.get('client_email')
                parent_ib_email = assignment.get('parent_ib_email') or assignment.get('manager_email')
                
                if not client_email or not parent_ib_email:
                    results.append({
                        'client_email': client_email,
                        'parent_ib_email': parent_ib_email,
                        'success': False,
                        'error': 'Both client_email and parent_ib_email are required'
                    })
                    error_count += 1
                    continue
                try:
                    client_user = CustomUser.objects.get(email=client_email)
                    parent_ib_user = CustomUser.objects.get(email=parent_ib_email)
                    result = assign_client_to_manager(client_user, parent_ib_user, force_reassign)
                    results.append({
                        'client_email': client_email,
                        'parent_ib_email': parent_ib_email,
                        **result
                    })
                    if result['success']:
                        success_count += 1
                    else:
                        error_count += 1
                except CustomUser.DoesNotExist as e:
                    results.append({
                        'client_email': client_email,
                        'parent_ib_email': parent_ib_email,
                        'success': False,
                        'error': f'User not found: {str(e)}'
                    })
                    error_count += 1
        
        return Response({
            'success': True,
            'summary': {
                'total_assignments': len(assignments),
                'successful': success_count,
                'failed': error_count
            },
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Error in bulk_assign_clients_api: {str(e)}")
        return Response({
            'error': f'An unexpected error occurred: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
