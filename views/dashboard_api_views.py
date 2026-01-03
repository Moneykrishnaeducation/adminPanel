#!/usr/bin/env python3
"""
Dashboard API Views
Serves dashboard data from database instead of direct MT5 calls
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Sum, Count
from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.core.cache import cache
from django.db.models.functions import Lower
import json
import logging
import time

from adminPanel.models import CustomUser, TradingAccount, Transaction
from adminPanel.decorators import role_required
from adminPanel.roles import UserRole
from rest_framework.permissions import IsAuthenticated
from adminPanel.permissions import IsAdminOrManager

logger = logging.getLogger(__name__)
# Cache TTL in seconds (default 5 minutes). Can be tuned.
DASHBOARD_CACHE_TTL = 300

@api_view(['GET'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def get_dashboard_data(request):
    """
    Get dashboard statistics from database cache
    """
    try:
        # Check if user is manager to apply filtering
        is_manager = hasattr(request.user, 'role') and request.user.role == 'manager'

        # Allow admins to request a specific manager or managers by `manager_status` (manager_admin_status value)
        manager_status = request.GET.get('manager_status') if request.user and getattr(request.user, 'role', None) == 'admin' else None

        # Create unique cache key for manager vs admin data. If admin requests a specific manager_status, include it.
        if manager_status:
            cache_key = f'dashboard_stats_manager_status_{manager_status}_by_admin'
        else:
            cache_key = f'dashboard_stats_manager_{request.user.id}' if is_manager else 'dashboard_stats_admin'

        # Allow callers to force a refresh and bypass cache for immediate data (useful for debugging)
        force_refresh = request.GET.get('force_refresh') in ['1', 'true', 'True']

        # Try to get from cache first (unless forced)
        cached_data = None if force_refresh else cache.get(cache_key)

        if cached_data:
            logger.info(f"📊 Serving dashboard data from cache for {'manager' if is_manager else 'admin'}")
            return Response({
                'status': 'success',
                'data': cached_data,
                'source': 'cache',
                'user_type': 'manager' if is_manager else 'admin'
            })

        # If no cache (or forced), generate fresh data and measure timing
        start_ts = time.time()

        # Generate data depending on role or requested manager
        if is_manager:
            data = generate_manager_dashboard_data(request.user)
        elif manager_status:
            # Admin requested stats for managers matching a specific manager_admin_status
            try:
                managers_qs = CustomUser.objects.filter(role='manager', manager_admin_status=manager_status)
                if not managers_qs.exists():
                    return Response({'status': 'error', 'message': 'No managers found with requested status'}, status=status.HTTP_404_NOT_FOUND)
                data = generate_manager_dashboard_for_managers(managers_qs)
            except Exception as e:
                logger.error(f"Error finding managers for status {manager_status}: {e}")
                return Response({'status': 'error', 'message': 'Error fetching managers'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            data = generate_dashboard_data()

        # Cache for configured TTL
        cache.set(cache_key, data, DASHBOARD_CACHE_TTL)
        elapsed = time.time() - start_ts

        return Response({
            'status': 'success',
            'data': data,
            'source': 'database',
            'user_type': 'manager' if is_manager else 'admin'
        })

    except Exception as e:
        logger.error(f"❌ Error getting dashboard data: {e}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def generate_manager_dashboard_data(manager_user):
    """
    Generate dashboard statistics for a specific manager (only their assigned clients' data)
    """
    try:
        # Get only clients assigned to this manager using both created_by and parent_ib relationships
        from django.db.models import Q
        manager_clients = CustomUser.objects.filter(
            role='client'
        ).filter(
            Q(created_by=manager_user) | Q(parent_ib=manager_user)
        )
        
        client_ids = list(manager_clients.values_list('id', flat=True))
        
        # Get trading accounts data for manager's clients only
        # Note: TradingAccount.ACCOUNT_TYPE_CHOICES uses 'standard' for real/live accounts.
        # Use 'standard' as the canonical live account type. For demo accounts, accept
        # case-insensitive variants (some records/scripts may have different casing).
        live_accounts = TradingAccount.objects.filter(
            account_type='standard',
            user_id__in=client_ids
        ) if client_ids else TradingAccount.objects.none()

        demo_accounts = TradingAccount.objects.annotate(type_lower=Lower('account_type')).filter(
            type_lower='demo',
            user_id__in=client_ids
        ) if client_ids else TradingAccount.objects.none()
        
        live_count = live_accounts.count()
        demo_count = demo_accounts.count()
        
        # Calculate total balance (live accounts only) for manager's clients
        total_balance = live_accounts.aggregate(
            total=Sum('balance')
        )['total'] or 0
        
        # Get IB clients count for this manager
        ib_clients = manager_clients.filter(IB_status=True).count()
        
        # Get deposits from last 30 days for manager's clients
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
        total_deposits = Transaction.objects.filter(
            transaction_type='deposit_trading',
            status='approved',
            created_at__gte=thirty_days_ago,
            user_id__in=client_ids
        ).aggregate(
            total=Sum('amount')
        )['total'] or 0 if client_ids else 0
        # Also compute overall (all-time) deposits for these clients
        total_deposits_alltime = Transaction.objects.filter(
            transaction_type='deposit_trading',
            status='approved',
            user_id__in=client_ids
        ).aggregate(total=Sum('amount'))['total'] or 0 if client_ids else 0
        
        # Get MAM funds for manager's clients
        mam_accounts = TradingAccount.objects.filter(
            account_type='mam',
            user_id__in=client_ids
        ) if client_ids else TradingAccount.objects.none()
        
        mam_funds = mam_accounts.aggregate(
            total=Sum('balance')
        )['total'] or 0
        
        # Get IB earnings for manager's clients
        ib_earnings = Transaction.objects.filter(
            transaction_type='commission',
            status='completed',
            user_id__in=client_ids
        ).aggregate(
            total=Sum('amount')
        )['total'] or 0 if client_ids else 0
        
        # Get withdrawable commission for manager's clients
        withdrawable_commission = Transaction.objects.filter(
            transaction_type='commission',
            status='completed',
            user_id__in=client_ids
        ).aggregate(
            total=Sum('amount')
        )['total'] or 0 if client_ids else 0
        
        # Get pending counts for manager's clients
        pending_transactions = Transaction.objects.filter(
            status='pending',
            user_id__in=client_ids
        ).count() if client_ids else 0

        # Calculate total withdrawn (approved withdrawals) for manager's clients
        withdraw_types = ['withdraw_trading', 'credit_out']
        total_withdrawn = Transaction.objects.filter(
            transaction_type__in=withdraw_types,
            status='approved',
            user_id__in=client_ids
        ).aggregate(total=Sum('amount'))['total'] or 0 if client_ids else 0
        
        # You may need to adjust these based on your ticket/request models
        pending_tickets = 0  # Implement based on your ticket system
        pending_requests = 0  # Implement based on your request system
        
        logger.info(f"✅ Manager dashboard data generated for {manager_user.username}: {len(client_ids)} clients, {live_count} live accounts, {demo_count} demo accounts")
        
        return {
            # Standardized fields expected by frontend
            'live_accounts': live_count,
            'demo_accounts': demo_count,
            'total_balance': float(total_balance),
            'ib_clients': ib_clients,
            'total_clients': manager_clients.count(),
            'total_deposits': float(total_deposits_alltime),
            'total_deposits_30d': float(total_deposits),
            'mam_funds': float(mam_funds),
            'mam_managed_funds': float(mam_funds),  # You may need separate logic
            'ib_earnings': float(ib_earnings),
            'withdrawable_commission': float(withdrawable_commission),
            'total_withdrawn': float(total_withdrawn),
            'pending_transactions': pending_transactions,
            'pending_tickets': pending_tickets,
            'pending_requests': pending_requests,
            'manager_id': manager_user.id,
            'manager_name': manager_user.get_full_name(),
            'client_count': len(client_ids),
            'client_ids': client_ids,  # For debugging
            'last_updated': timezone.now().isoformat(),
            # Add global-style totals so frontend can display overview tiles when admin views a manager
            'total_users': CustomUser.objects.count(),
            'total_managers': CustomUser.objects.filter(role='manager').count(),
            'total_ibs': CustomUser.objects.filter(IB_status=True).count(),
            'total_trading_accounts': TradingAccount.objects.count(),
            'total_demo_accounts': TradingAccount.objects.annotate(type_lower=Lower('account_type')).filter(type_lower='demo').count(),
            'active_mam_accounts': TradingAccount.objects.filter(account_type='mam', status='active').count(),
            'mam_investor_accounts': TradingAccount.objects.filter(account_type='mam_investment').count(),
            'total_prop_accounts': TradingAccount.objects.filter(account_type='prop').count(),
        }
        
    except Exception as e:
        logger.error(f"❌ Error generating manager dashboard data: {e}")
        # Return empty data structure in case of error
        return {
            'live_accounts': 0,
            'demo_accounts': 0,
            'total_balance': 0.0,
            'ib_clients': 0,
            'total_clients': 0,
            'total_deposits': 0.0,
            'mam_funds': 0.0,
            'mam_managed_funds': 0.0,
            'ib_earnings': 0.0,
            'withdrawable_commission': 0.0,
            'pending_transactions': 0,
            'pending_tickets': 0,
            'pending_requests': 0,
            'manager_id': manager_user.id,
            'manager_name': str(manager_user),
            'client_count': 0,
            'error': str(e),
            'last_updated': timezone.now().isoformat()
        }

def generate_dashboard_data():
    """
    Generate dashboard statistics from database
    """
    # Get trading accounts data
    # Use 'standard' for live/real trading accounts; demo accounts may be stored
    # in varying case so perform a case-insensitive match.
    live_accounts = TradingAccount.objects.filter(account_type='standard')
    demo_accounts = TradingAccount.objects.annotate(type_lower=Lower('account_type')).filter(type_lower='demo')
    
    live_count = live_accounts.count()
    demo_count = demo_accounts.count()
    
    # Calculate total balance (live accounts only)
    total_balance = live_accounts.aggregate(
        total=Sum('balance')
    )['total'] or 0
    
    # Get IB clients count
    ib_clients = CustomUser.objects.filter(
        role='client'
    ).exclude(manager_admin_status='None').count()
    
    # Get deposits from last 30 days
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    total_deposits = Transaction.objects.filter(
        transaction_type='deposit_trading',
        status='approved',
        created_at__gte=thirty_days_ago
    ).aggregate(
        total=Sum('amount')
    )['total'] or 0
    # Also compute overall (all-time) deposits
    total_deposits_alltime = Transaction.objects.filter(
        transaction_type='deposit_trading',
        status='approved'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Get MAM funds
    mam_accounts = TradingAccount.objects.filter(account_type='mam')
    mam_funds = mam_accounts.aggregate(
        total=Sum('balance')
    )['total'] or 0
    
    # Get IB earnings
    ib_earnings = Transaction.objects.filter(
        transaction_type='commission',
        status='completed'
    ).aggregate(
        total=Sum('amount')
    )['total'] or 0
    
    # Get withdrawable commission
    withdrawable_commission = Transaction.objects.filter(
        transaction_type='commission',
        status='completed',
        # Add your withdrawal logic here
    ).aggregate(
        total=Sum('amount')
    )['total'] or 0
    
    # Get pending counts
    pending_transactions = Transaction.objects.filter(
        status='pending'
    ).count()
    
    # You may need to adjust these based on your ticket/request models
    pending_tickets = 0  # Implement based on your ticket system
    pending_requests = 0  # Implement based on your request system

    # Calculate total withdrawn globally (approved withdraw types)
    withdraw_types = ['withdraw_trading', 'credit_out']
    total_withdrawn = Transaction.objects.filter(
        transaction_type__in=withdraw_types,
        status='approved'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    return {
        'live_accounts': live_count,
        'demo_accounts': demo_count,
        'total_balance': float(total_balance),
        'ib_clients': ib_clients,
    'total_deposits': float(total_deposits_alltime),
    'total_deposits_30d': float(total_deposits),
        'mam_funds': float(mam_funds),
        'mam_managed_funds': float(mam_funds),  # You may need separate logic
        'ib_earnings': float(ib_earnings),
        'withdrawable_commission': float(withdrawable_commission),
        'pending_transactions': pending_transactions,
        'pending_tickets': pending_tickets,
        'pending_requests': pending_requests,
    'last_updated': timezone.now().isoformat(),
    'total_withdrawn': float(total_withdrawn),
        # Add global totals expected by frontend tiles
        'total_users': CustomUser.objects.count(),
        'total_managers': CustomUser.objects.filter(role='manager').count(),
        'total_ibs': CustomUser.objects.filter(IB_status=True).count(),
        'total_trading_accounts': TradingAccount.objects.count(),
        'total_demo_accounts': demo_accounts.count(),
        'active_mam_accounts': TradingAccount.objects.filter(account_type='mam', status='active').count(),
        'mam_investor_accounts': TradingAccount.objects.filter(account_type='mam_investment').count(),
        'total_prop_accounts': TradingAccount.objects.filter(account_type='prop').count(),
    }

@api_view(['GET'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def get_recent_activity(request):
    """
    Get recent activity from database
    """
    try:
        # Get recent transactions
        recent_transactions = Transaction.objects.select_related('user', 'trading_account').order_by('-created_at')[:10]
        
        activity_list = []
        
        for transaction in recent_transactions:
            activity_list.append({
                'id': transaction.id,
                'type': transaction.transaction_type,
                'amount': float(transaction.amount),
                'user': transaction.user.username if transaction.user else 'Unknown',
                'account': transaction.trading_account.login if transaction.trading_account else 'N/A',
                'status': transaction.status,
                'created_at': transaction.created_at.isoformat(),
                'description': f"{transaction.transaction_type.title()} of ${transaction.amount} by {transaction.user.username if transaction.user else 'Unknown'}"
            })
        
        return Response({
            'status': 'success',
            'data': activity_list
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting recent activity: {e}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def refresh_dashboard_cache(request):
    """
    Manually refresh dashboard cache
    """
    try:
        logger.info("🔄 Manually refreshing dashboard cache")
        # If admin wants to clear all caches (useful after bulk updates), send clear_all=true
        clear_all = request.data.get('clear_all') in [True, '1', 'true', 'True']
        if clear_all:
            logger.info("🧹 Clearing entire cache as requested by admin")
            cache.clear()

        data = generate_dashboard_data()
        cache.set('dashboard_stats_admin', data, DASHBOARD_CACHE_TTL)

        return Response({
            'status': 'success',
            'message': 'Dashboard cache refreshed successfully',
            'data': data
        })

    except Exception as e:
        logger.error(f"❌ Error refreshing dashboard cache: {e}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def get_dashboard_health(request):
    """
    Get dashboard health status and cache info
    """
    try:
        cached_data = cache.get('dashboard_stats')
        
        health_data = {
            'cache_status': 'active' if cached_data else 'empty',
            'last_updated': cached_data.get('last_updated') if cached_data else None,
            'data_source': 'cache' if cached_data else 'database',
            'total_users': CustomUser.objects.count(),
            'total_trading_accounts': TradingAccount.objects.count(),
            'total_transactions': Transaction.objects.count(),
            'server_time': timezone.now().isoformat()
        }

        return Response({
            'status': 'success',
            'data': health_data
        })
    except Exception as e:
        logger.error(f"❌ Error getting dashboard health: {e}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def generate_manager_dashboard_for_managers(managers_qs):
    """
    Aggregate dashboard statistics for multiple managers (union of their clients).
    `managers_qs` is a queryset of CustomUser objects with role='manager'.
    """
    try:
        from django.db.models import Q
        manager_ids = list(managers_qs.values_list('id', flat=True))

        # Get all clients assigned to any of these managers (created_by or parent_ib)
        clients_qs = CustomUser.objects.filter(role='client').filter(
            Q(created_by_id__in=manager_ids) | Q(parent_ib_id__in=manager_ids)
        )

        client_ids = list(clients_qs.values_list('id', flat=True))

        # Reuse logic from single-manager generator but operate on client_ids
        live_accounts = TradingAccount.objects.filter(account_type='standard', user_id__in=client_ids) if client_ids else TradingAccount.objects.none()
        demo_accounts = TradingAccount.objects.annotate(type_lower=Lower('account_type')).filter(type_lower='demo', user_id__in=client_ids) if client_ids else TradingAccount.objects.none()

        live_count = live_accounts.count()
        demo_count = demo_accounts.count()

        total_balance = live_accounts.aggregate(total=Sum('balance'))['total'] or 0

        ib_clients = clients_qs.filter(IB_status=True).count()

        thirty_days_ago = timezone.now() - timedelta(days=30)
        total_deposits = Transaction.objects.filter(
            transaction_type='deposit_trading', status='approved', created_at__gte=thirty_days_ago, user_id__in=client_ids
        ).aggregate(total=Sum('amount'))['total'] or 0 if client_ids else 0
        # Also compute overall (all-time) deposits for these clients
        total_deposits_alltime = Transaction.objects.filter(
            transaction_type='deposit_trading', status='approved', user_id__in=client_ids
        ).aggregate(total=Sum('amount'))['total'] or 0 if client_ids else 0

        mam_accounts = TradingAccount.objects.filter(account_type='mam', user_id__in=client_ids) if client_ids else TradingAccount.objects.none()
        mam_funds = mam_accounts.aggregate(total=Sum('balance'))['total'] or 0

        ib_earnings = Transaction.objects.filter(transaction_type='commission', status='completed', user_id__in=client_ids).aggregate(total=Sum('amount'))['total'] or 0 if client_ids else 0

        withdrawable_commission = Transaction.objects.filter(transaction_type='commission', status='completed', user_id__in=client_ids).aggregate(total=Sum('amount'))['total'] or 0 if client_ids else 0

        pending_transactions = Transaction.objects.filter(status='pending', user_id__in=client_ids).count() if client_ids else 0

        pending_tickets = 0
        pending_requests = 0

        # Calculate total withdrawn across these clients
        withdraw_types = ['withdraw_trading', 'credit_out']
        total_withdrawn = Transaction.objects.filter(
            transaction_type__in=withdraw_types,
            status='approved',
            user_id__in=client_ids
        ).aggregate(total=Sum('amount'))['total'] or 0 if client_ids else 0

        return {
            'live_accounts': live_count,
            'demo_accounts': demo_count,
            'total_balance': float(total_balance),
            'ib_clients': ib_clients,
            'total_clients': clients_qs.count(),
            'total_deposits': float(total_deposits_alltime),
            'total_deposits_30d': float(total_deposits),
            'mam_funds': float(mam_funds),
            'mam_managed_funds': float(mam_funds),
            'ib_earnings': float(ib_earnings),
            'withdrawable_commission': float(withdrawable_commission),
            'total_withdrawn': float(total_withdrawn),
            'pending_transactions': pending_transactions,
            'pending_tickets': pending_tickets,
            'pending_requests': pending_requests,
            'manager_ids': manager_ids,
            'manager_count': managers_qs.count(),
            'client_ids': client_ids,
            'client_count': len(client_ids),
            'last_updated': timezone.now().isoformat(),
            'total_users': CustomUser.objects.count(),
            'total_managers': CustomUser.objects.filter(role='manager').count(),
            'total_ibs': CustomUser.objects.filter(IB_status=True).count(),
            'total_trading_accounts': TradingAccount.objects.count(),
            'total_demo_accounts': TradingAccount.objects.annotate(type_lower=Lower('account_type')).filter(type_lower='demo').count(),
            'active_mam_accounts': TradingAccount.objects.filter(account_type='mam', status='active').count(),
            'mam_investor_accounts': TradingAccount.objects.filter(account_type='mam_investment').count(),
            'total_prop_accounts': TradingAccount.objects.filter(account_type='prop').count(),
        }
    except Exception as e:
        logger.error(f"❌ Error generating aggregated manager dashboard data: {e}")
        return {
            'live_accounts': 0,
            'demo_accounts': 0,
            'total_balance': 0.0,
            'ib_clients': 0,
            'total_clients': 0,
            'total_deposits': 0.0,
            'mam_funds': 0.0,
            'mam_managed_funds': 0.0,
            'ib_earnings': 0.0,
            'withdrawable_commission': 0.0,
            'pending_transactions': 0,
            'pending_tickets': 0,
            'pending_requests': 0,
            'manager_ids': [],
            'manager_count': 0,
            'client_ids': [],
            'client_count': 0,
            'last_updated': timezone.now().isoformat(),
            'total_users': CustomUser.objects.count(),
            'total_managers': CustomUser.objects.filter(role='manager').count(),
        }
