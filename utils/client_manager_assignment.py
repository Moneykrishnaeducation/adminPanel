#!/usr/bin/env python3
"""
Utility functions for managing IB client to manager assignments.
These functions handle the logic for assigning clients to managers based on IB relationships.
"""

from django.db import transaction
from django.db.models import Q
from adminPanel.models import CustomUser
import logging

logger = logging.getLogger(__name__)

def assign_ib_clients_to_manager(manager_user, force_reassign=False):
    """
    Assign all IB clients to a manager based on referral and parent_ib relationships.
    
    Args:
        manager_user (CustomUser): The manager to assign clients to
        force_reassign (bool): If True, reassign clients even if they already have a manager
        
    Returns:
        dict: Summary of assignments made
    """
    if not manager_user.IB_status:
        logger.warning(f"User {manager_user.email} is not an IB - no clients to assign")
        return {'warning': 'User is not an IB', 'assigned': 0}
    
    assigned_count = 0
    skipped_count = 0
    
    with transaction.atomic():
        # Find clients through referral code relationship
        referral_clients = []
        if manager_user.referral_code:
            referral_query = CustomUser.objects.filter(
                referral_code_used=manager_user.referral_code,
                role='client'
            )
            
            if not force_reassign:
                referral_query = referral_query.filter(created_by__isnull=True)
            
            referral_clients = list(referral_query)
        
        # Find clients through parent_ib relationship
        parent_ib_query = CustomUser.objects.filter(
            parent_ib=manager_user,
            role='client'
        )
        
        if not force_reassign:
            parent_ib_query = parent_ib_query.filter(created_by__isnull=True)
        
        parent_ib_clients = list(parent_ib_query)
        
        # Combine and deduplicate clients
        all_clients = {client.id: client for client in (referral_clients + parent_ib_clients)}
        unique_clients = list(all_clients.values())
        
        # Assign clients to manager
        for client in unique_clients:
            if not force_reassign and client.created_by is not None:
                skipped_count += 1
                logger.info(f"Skipped client {client.email} - already assigned to {client.created_by.email}")
                continue
            
            old_manager = client.created_by
            client.created_by = manager_user
            client.save(update_fields=['created_by'])
            assigned_count += 1
            
            if old_manager:
                logger.info(f"Reassigned client {client.email} from {old_manager.email} to {manager_user.email}")
            else:
                logger.info(f"Assigned client {client.email} to manager {manager_user.email}")
    
    result = {
        'success': True,
        'assigned': assigned_count,
        'skipped': skipped_count,
        'manager_email': manager_user.email,
        'manager_referral_code': manager_user.referral_code
    }
    
    logger.info(f"✅ Assignment complete for manager {manager_user.email}: {assigned_count} assigned, {skipped_count} skipped")
    return result

def get_unassigned_ib_clients(manager_user=None):
    """
    Get all IB clients that are not assigned to any parent IB.
    
    Args:
        parent_ib_user (CustomUser, optional): If provided, get unassigned clients for this specific parent IB
    Returns:
        QuerySet: Unassigned client users
    """
    # Exclude IB users from unassigned clients
    base_query = CustomUser.objects.filter(
        role='client',
        created_by__isnull=True,
        IB_status=False,
        parent_ib__isnull=True
    )
    
    if manager_user:
        if not manager_user.IB_status:
            return CustomUser.objects.none()
        # Get clients related to this specific parent IB, but exclude IBs
        q_objects = Q()
        if manager_user.referral_code:
            q_objects |= Q(referral_code_used=manager_user.referral_code)
        q_objects |= Q(parent_ib=manager_user)
        return base_query.filter(q_objects)
    else:
        # Get all unassigned clients who have IB relationships, but exclude IBs
        return base_query.filter(
            Q(referral_code_used__isnull=False) | Q(parent_ib__isnull=True)
        )

def assign_client_to_manager(client_user, manager_user, force_reassign=False):
    """
    Manually assign a specific client to a manager.
    
    Args:
        client_user (CustomUser): The client to assign
        manager_user (CustomUser): The manager to assign to
        force_reassign (bool): If True, reassign even if client already has a manager
        
    Returns:
        dict: Result of the assignment
    """
    if client_user.role != 'client':
        return {'error': 'User is not a client', 'success': False}
    if not manager_user.IB_status:
        return {'error': 'Target user is not an IB', 'success': False}
    if not force_reassign and client_user.created_by is not None:
        return {
            'error': f'Client is already assigned to {client_user.created_by.email}',
            'success': False,
            'current_parent_ib': client_user.created_by.email
        }
    old_parent_ib = client_user.created_by
    client_user.created_by = manager_user
    client_user.save(update_fields=['created_by'])
    result = {
        'success': True,
        'client_email': client_user.email,
        'new_parent_ib': manager_user.email,
        'previous_parent_ib': old_parent_ib.email if old_parent_ib else None
    }
    if old_parent_ib:
        logger.info(f"Reassigned client {client_user.email} from {old_parent_ib.email} to {manager_user.email}")
    else:
        logger.info(f"Assigned client {client_user.email} to parent IB {manager_user.email}")
    return result

def get_manager_client_stats(manager_user):
    """
    Get statistics about a manager's assigned clients.
    
    Args:
        manager_user (CustomUser): The manager to get stats for
        
    Returns:
        dict: Statistics about the manager's clients
    """
    if manager_user.role != 'manager':
        return {'error': 'User is not a manager'}
    
    # Get all clients assigned to this manager
    assigned_clients = CustomUser.objects.filter(created_by=manager_user, role='client')
    
    # Get clients through IB relationship but not yet assigned
    unassigned_ib_clients = get_unassigned_ib_clients(manager_user)
    
    # Get IB relationship stats
    referral_clients_count = 0
    parent_ib_clients_count = 0
    
    if manager_user.referral_code:
        referral_clients_count = CustomUser.objects.filter(
            referral_code_used=manager_user.referral_code,
            role='client'
        ).count()
    
    if manager_user.IB_status:
        parent_ib_clients_count = CustomUser.objects.filter(
            parent_ib=manager_user,
            role='client'
        ).count()
    
    return {
        'manager_email': manager_user.email,
        'manager_is_ib': manager_user.IB_status,
        'manager_referral_code': manager_user.referral_code,
        'assigned_clients_count': assigned_clients.count(),
        'unassigned_ib_clients_count': unassigned_ib_clients.count(),
        'total_referral_clients': referral_clients_count,
        'total_parent_ib_clients': parent_ib_clients_count,
        'clients_details': [
            {
                'email': client.email,
                'user_id': client.user_id,
                'referral_code_used': client.referral_code_used,
                'parent_ib': client.parent_ib.email if client.parent_ib else None
            }
            for client in assigned_clients
        ]
    }
