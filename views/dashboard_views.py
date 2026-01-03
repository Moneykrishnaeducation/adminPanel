from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from django.utils import timezone
from django.db import models
from datetime import timedelta
from ..decorators import role_required
from ..roles import UserRole
from ..models import CustomUser, TradingAccount, Transaction, CommissioningProfile, IBRequest
from rest_framework.permissions import IsAuthenticated
from ..permissions import IsAdminOrManager

@api_view(['GET'])
@role_required(['admin', 'manager'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def admin_dashboard_view(request):
    """Admin Dashboard API endpoint"""
    return Response({
        "message": "Admin dashboard data",
        "status": "success",
        "user": request.user.username
    }, status=status.HTTP_200_OK)

@api_view(['GET'])
@role_required(['manager'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def manager_dashboard_view(request):
    """Manager Dashboard API endpoint"""
    return Response({
        "message": "Manager dashboard data",
        "status": "success",
        "user": request.user.username
    }, status=status.HTTP_200_OK)

@api_view(['GET'])
@role_required(['client'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def client_dashboard_view(request):
    """Client Dashboard API endpoint"""
    return Response({
        "message": "Client dashboard data",
        "status": "success",
        "user": request.user.username
    }, status=status.HTTP_200_OK)

@api_view(['GET'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def dashboard_stats(request):
    """Get dashboard statistics from database"""
    try:
        # --- Custom Dashboard Metrics ---
        total_users = CustomUser.objects.all().count()
        pending_transactions = Transaction.objects.filter(status='pending').count()
        pending_tickets = 0  # Update with real logic if available
        pending_requests = IBRequest.objects.filter(status='pending').count()
        active_mam_accounts = TradingAccount.objects.filter(account_type='mam', status='active').count()
        total_trading_accounts = TradingAccount.objects.filter(account_type='standard').count()
        # Debug: print all account types
        all_types = list(TradingAccount.objects.values_list('account_type', flat=True))
        print('All TradingAccount types:', all_types)
        # Case-insensitive count for demo accounts
        from django.db.models.functions import Lower
        total_demo_accounts = TradingAccount.objects.annotate(type_lower=Lower('account_type')).filter(type_lower='demo').count()
        mam_investor_accounts = TradingAccount.objects.filter(account_type='mam_investment').count()
        total_prop_accounts = TradingAccount.objects.filter(account_type='prop').count()
        # Count managers and IBs
        total_managers = CustomUser.objects.filter(role='manager').count()
        total_ibs = CustomUser.objects.filter(IB_status=True).count()
        return Response({
            'total_users': total_users,
            'total_managers': total_managers,
            'total_ibs': total_ibs,
            'pending_transactions': pending_transactions,
            'pending_tickets': pending_tickets,
            'pending_requests': pending_requests,
            'active_mam_accounts': active_mam_accounts,
            'total_trading_accounts': total_trading_accounts,
            'total_demo_accounts': total_demo_accounts,
            'mam_investor_accounts': mam_investor_accounts,
            'total_prop_accounts': total_prop_accounts,
            'last_updated': timezone.now().isoformat()
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': f'Error fetching dashboard stats: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def recent_activity(request):
    """Get recent activity from database"""
    try:
        activities = []

        # Determine if we should scope to a manager's clients
        manager_user = None
        if getattr(request.user, 'role', None) == 'manager':
            manager_user = request.user
        elif getattr(request.user, 'role', None) == 'admin' and request.GET.get('manager_id'):
            try:
                manager_id = int(request.GET.get('manager_id'))
                mgr = CustomUser.objects.filter(id=manager_id, role='manager').first()
                if mgr:
                    manager_user = mgr
            except Exception:
                manager_user = None

        # If manager_user is set, limit activity to their clients
        client_qs = None
        client_ids = None
        if manager_user:
            from django.db.models import Q
            client_qs = CustomUser.objects.filter(role='client').filter(
                Q(created_by=manager_user) | Q(parent_ib=manager_user)
            )
            client_ids = list(client_qs.values_list('id', flat=True))

        # Get recent user registrations (clients only when scoped)
        recent_users_qs = CustomUser.objects.filter(
            date_joined__gte=timezone.now() - timedelta(days=7)
        )
        if client_qs is not None:
            recent_users_qs = recent_users_qs.filter(id__in=client_ids)
        recent_users = recent_users_qs.order_by('-date_joined')[:5]

        for user in recent_users:
            activities.append({
                'type': 'user_registration',
                'message': f'New user registered: {user.username}',
                'timestamp': user.date_joined.isoformat(),
                'user': user.username
            })

        # Get recent trading accounts (scope to client_ids when available)
        recent_accounts_qs = TradingAccount.objects.filter(
            created_at__gte=timezone.now() - timedelta(days=7)
        )
        if client_ids is not None:
            recent_accounts_qs = recent_accounts_qs.filter(user_id__in=client_ids)
        recent_accounts = recent_accounts_qs.order_by('-created_at')[:5]

        for account in recent_accounts:
            activities.append({
                'type': 'trading_account',
                'message': f'New {account.account_type} account created: {getattr(account, "account_id", account.id)}',
                'timestamp': account.created_at.isoformat() if getattr(account, 'created_at', None) else '',
                'user': account.user.username if getattr(account, 'user', None) else 'Unknown'
            })

        # Get recent transactions (scope to client_ids when available)
        try:
            recent_transactions_qs = Transaction.objects.filter(
                created_at__gte=timezone.now() - timedelta(days=7)
            )
            if client_ids is not None:
                # Include transactions with user_id in clients or transactions linked to trading accounts owned by clients
                recent_transactions_qs = recent_transactions_qs.filter(
                    models.Q(user_id__in=client_ids) | models.Q(trading_account__user_id__in=client_ids)
                )
            recent_transactions = recent_transactions_qs.order_by('-created_at')[:5]

            for transaction in recent_transactions:
                activities.append({
                    'type': 'transaction',
                    'message': f'{transaction.transaction_type.title()} of ${transaction.amount} - {transaction.status}',
                    'timestamp': transaction.created_at.isoformat() if getattr(transaction, 'created_at', None) else '',
                    'user': transaction.user.username if getattr(transaction, 'user', None) else (transaction.trading_account.user.username if getattr(transaction, 'trading_account', None) and getattr(transaction.trading_account, 'user', None) else 'Unknown')
                })
        except Exception:
            # If there's an unexpected schema, skip transactions
            pass
        
        # Sort activities by timestamp (newest first)
        activities.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return Response({
            'activities': activities[:10],  # Return top 10 activities
            'last_updated': timezone.now().isoformat()
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': f'Error fetching recent activity: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
