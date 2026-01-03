from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from adminPanel.models import TradingAccount, Transaction
from adminPanel.serializers import TransactionSerializer
from adminPanel.permissions import IsAuthenticatedUser
import time

@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def trading_account_history_view(request, account_id):
    """
    Returns transaction history for a trading account (for account history modal).
    """
    try:
        account = TradingAccount.objects.get(account_id=account_id)
    except TradingAccount.DoesNotExist:
        return Response({'detail': 'Trading account not found.'}, status=status.HTTP_404_NOT_FOUND)

    user = request.user
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
    
    # Check permissions
    if is_admin:
        # Admins can see all trading accounts
        pass
    elif is_manager:
        # Managers can only see trading accounts of users they created or their IB clients
        from django.db.models import Q
        if not (account.user.created_by == user or account.user.parent_ib == user):
            return Response({'detail': 'Access denied. You can only view accounts of clients you created or your IB clients.'}, 
                          status=status.HTTP_403_FORBIDDEN)
    else:
        # Regular users can only see their own accounts
        if account.user != user:
            return Response({'detail': 'Access denied. You can only view your own accounts.'}, 
                          status=status.HTTP_403_FORBIDDEN)

    # Get transactions from database
    db_transactions = Transaction.objects.filter(trading_account=account).order_by('-created_at')
    
    # Get MT5 deals for comprehensive history
    mt5_transactions = []
    try:
        from adminPanel.mt5.services import MT5ManagerActions
        mt5 = MT5ManagerActions()
        
        # Add logging for performance monitoring
        import logging
        logger = logging.getLogger(__name__)
        start_time = time.time()
        logger.info(f"Starting MT5 deal request for account {account_id}")
        
    # Get deals with configurable date range (default to last 30 days for better performance)
        from datetime import datetime, timedelta
        
        # Allow frontend to specify date range via query parameters
        days_back = int(request.GET.get('days_back', 30))  # Default 30 days, max 90
        days_back = min(days_back, 90)  # Cap at 90 days to prevent excessive queries
        
        from_date = datetime.now() - timedelta(days=days_back)
        to_date = datetime.now()
        
        # Add timeout protection for MT5 request
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError("MT5 request timed out")
        
        # Set signal handler for timeout (only on Unix-like systems)
        try:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(15)  # 15 second timeout for MT5 operation
            deals = mt5.manager.DealRequest(int(account_id), int(from_date.timestamp()), int(to_date.timestamp()))
            signal.alarm(0)  # Cancel the alarm
        except (AttributeError, OSError):
            # On Windows or if signal not available, proceed without timeout
            deals = mt5.manager.DealRequest(int(account_id), int(from_date.timestamp()), int(to_date.timestamp()))
        
        if deals:
            for deal in deals:
                try:
                    # Convert MT5 deal to transaction-like format
                    deal_action = getattr(deal, 'Action', None)
                    deal_profit = getattr(deal, 'Profit', 0.0)
                    deal_comment = getattr(deal, 'Comment', '')
                    deal_time = getattr(deal, 'Time', 0)
                    deal_id = getattr(deal, 'Deal', None)
                    
                    # Filter for balance operations (Action == 2)
                    if deal_action == 2:
                        # Determine transaction type based on profit
                        if deal_profit > 0:
                            trans_type = 'deposit_trading'
                            type_display = 'Deposit'
                        elif deal_profit < 0:
                            trans_type = 'withdraw_trading'
                            type_display = 'Withdrawal'
                        else:
                            continue  # Skip zero amounts
                        
                        # Convert MT5 timestamp to datetime
                        try:
                            from django.utils import timezone as django_timezone
                            deal_datetime = datetime.fromtimestamp(deal_time) if deal_time else datetime.now()
                            # Make timezone-aware to match Django model datetimes
                            if deal_datetime.tzinfo is None:
                                deal_datetime = django_timezone.make_aware(deal_datetime)
                        except (ValueError, OSError):
                            deal_datetime = django_timezone.now()
                        
                        # Create pseudo-transaction object for MT5 deal
                        mt5_transaction = {
                            'id': f"mt5_{deal_id}",
                            'transaction_type': trans_type,
                            'amount': abs(deal_profit),
                            'description': f"MT5 {type_display}: {deal_comment}" if deal_comment else f"MT5 {type_display}",
                            'status': 'approved',
                            'created_at': deal_datetime,
                            'approved_at': deal_datetime,
                            'source': 'MT5 Server',
                            'user': account.user,
                            'approved_by': None,
                            'is_mt5_deal': True,
                            'deal_id': deal_id,
                            'mt5_comment': deal_comment,
                        }
                        
                        mt5_transactions.append(mt5_transaction)
                        
                except Exception as deal_error:
                    # Log warning but continue processing other deals
                    logger.warning(f"Error processing deal {deal_id if 'deal_id' in locals() else 'unknown'}: {deal_error}")
                    continue
        
        elapsed_time = time.time() - start_time
        logger.info(f"Completed MT5 deal request for account {account_id}, found {len(mt5_transactions)} transactions in {elapsed_time:.2f} seconds")
                    
    except TimeoutError:
        logger.warning(f"MT5 request timed out for account {account_id}, proceeding with database transactions only")
        mt5_transactions = []
    except Exception as mt5_error:
        # If MT5 is not available, continue with database transactions only
        logger.warning(f"MT5 error for account {account_id}: {mt5_error}")
        mt5_transactions = []
    
    # Combine database transactions with MT5 deals
    all_transactions = []
    
    # Add database transactions
    for tx in db_transactions:
        all_transactions.append({
            'id': tx.id,
            'transaction_type': tx.transaction_type,
            'amount': f"{float(tx.amount):.2f}",
            'description': tx.description or '',
            'status': tx.status,
            'created_at': tx.created_at.isoformat() if tx.created_at else '',
            'approved_at': tx.approved_at.isoformat() if tx.approved_at else '',
            'source': tx.source or 'Database',
            'user': tx.user.email if tx.user else 'Unknown',
            'approved_by': tx.approved_by.email if tx.approved_by else '',
            'is_mt5_deal': False,
        })
    
    # Add MT5 transactions
    for mt5_tx in mt5_transactions:
        all_transactions.append({
            'id': mt5_tx['id'],
            'transaction_type': mt5_tx['transaction_type'],
            'amount': f"{float(mt5_tx['amount']):.2f}",
            'description': mt5_tx['description'],
            'status': mt5_tx['status'],
            'created_at': mt5_tx['created_at'].isoformat(),
            'approved_at': mt5_tx['approved_at'].isoformat(),
            'source': mt5_tx['source'],
            'user': mt5_tx['user'].email if hasattr(mt5_tx['user'], 'email') else str(mt5_tx['user']),
            'approved_by': 'MT5 System',
            'is_mt5_deal': True,
        })
    
    # Sort by date (newest first)
    all_transactions.sort(key=lambda x: x['created_at'], reverse=True)

    # Get balance and equity from TradingAccount model
    balance = float(account.balance) if hasattr(account, 'balance') else 0.0
    equity = float(account.equity) if hasattr(account, 'equity') else 0.0

    # Try to get open positions from MT5 if possible, else fallback to []
    positions = []
    open_positions_count = 0
    try:
        from adminPanel.mt5.services import MT5ManagerActions
        mt5 = MT5ManagerActions()
        positions = mt5.get_open_positions(int(account.account_id))
        open_positions_count = len(positions)
    except Exception as e:
        positions = []
        open_positions_count = 0

    # Support both account_summary and flat fields for frontend compatibility
    return Response({
        'transactions': all_transactions,
        'results': all_transactions,
        'balance': balance,
        'equity': equity,
        'positions': positions,
        'open_positions': open_positions_count,
        'account_summary': {
            'balance': balance,
            'equity': equity,
            'open_positions': open_positions_count,
        },
        'mt5_deals_count': len(mt5_transactions),
        'db_transactions_count': len(list(db_transactions)),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def trading_account_positions_view(request, account_id):
    """
    Returns open positions for a trading account. Uses MT5ManagerActions if available.
    Endpoint: GET /api/trading-account/<account_id>/positions/
    """
    try:
        account = TradingAccount.objects.get(account_id=account_id)
    except TradingAccount.DoesNotExist:
        return Response({'detail': 'Trading account not found.'}, status=status.HTTP_404_NOT_FOUND)

    user = request.user
    user_role = getattr(user, 'role', None)
    user_status = getattr(user, 'manager_admin_status', None)
    is_superuser = getattr(user, 'is_superuser', False)

    # Determine permissions similar to trading_account_history_view
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
        pass
    elif is_manager:
        # Managers can only see trading accounts of clients they created or their IB clients
        from django.db.models import Q
        if not (account.user.created_by == user or account.user.parent_ib == user):
            return Response({'detail': 'Access denied. You can only view accounts of clients you created or your IB clients.'}, status=status.HTTP_403_FORBIDDEN)
    else:
        if account.user != user:
            return Response({'detail': 'Access denied. You can only view your own accounts.'}, status=status.HTTP_403_FORBIDDEN)

    # Try to fetch open positions from MT5
    positions = []
    try:
        from adminPanel.mt5.services import MT5ManagerActions
        mt5 = MT5ManagerActions()
        positions = mt5.get_open_positions(int(account.account_id))
    except Exception as e:
        # If MT5 is unavailable, return empty positions and log warning
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"MT5 error while fetching positions for account {account_id}: {e}")
        positions = []

    return Response({'positions': positions, 'open_positions': len(positions)})
