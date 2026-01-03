"""
Additional views for transaction management.
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from adminPanel.permissions import IsAuthenticatedUser
from adminPanel.models import Transaction, TradingAccount, CustomUser
from adminPanel.models import ActivityLog
from adminPanel.serializers import TransactionSerializer
from django.utils import timezone
from django.db import models
from decimal import Decimal
import logging
from adminPanel.mt5.services import MT5ManagerActions

logger = logging.getLogger(__name__)

@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def create_transaction(request):
    """
    Create a new transaction for a user.
    Expects data:
    {
        "user_id": 123,
        "transaction_type": "deposit_trading",
        "amount": "100.00",
        "trading_account_id": "12345", // optional
        "description": "Manual transaction",
        "source": "Bank", // optional
        "payout_to": "bank", // optional for withdrawals
        "external_account": "****1234" // optional for withdrawals
    }
    """
    try:
        data = request.data
        
        # Validate required fields
        user_id = data.get('user_id')
        transaction_type = data.get('transaction_type')
        amount = data.get('amount')
        
        if not all([user_id, transaction_type, amount]):
            return Response({
                'error': 'user_id, transaction_type, and amount are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get user
        try:
            user = CustomUser.objects.get(user_id=user_id)
        except CustomUser.DoesNotExist:
            return Response({
                'error': f'User with ID {user_id} not found'
            }, status=status.HTTP_404_NOT_FOUND)

        # KYC check for withdrawals
        if transaction_type in ['withdraw_trading', 'commission_withdrawal']:
            if not user.user_verified:
                # Log blocked withdrawal attempt
                ActivityLog.objects.create(
                    user=user,
                    activity=f"Blocked withdrawal attempt: KYC incomplete for user {user.email}",
                    ip_address=request.META.get('REMOTE_ADDR', ''),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )
                return Response({
                    'error': 'Withdrawal blocked: Please complete KYC verification before making withdrawals.'
                }, status=status.HTTP_403_FORBIDDEN)
        
        # Validate transaction type
        valid_types = [choice[0] for choice in Transaction.TRANSACTION_TYPE_CHOICES]
        if transaction_type not in valid_types:
            return Response({
                'error': f'Invalid transaction type. Valid options: {valid_types}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate amount
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                raise ValueError("Amount must be positive")
        except (ValueError, TypeError):
            return Response({
                'error': 'Invalid amount. Must be a positive number'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create transaction data
        transaction_data = {
            'user': user,
            'transaction_type': transaction_type,
            'amount': amount,
            'description': data.get('description', f'{transaction_type.replace("_", " ").title()} transaction'),
            'source': data.get('source', ''),
        }
        
        # Handle trading account
        trading_account_id = data.get('trading_account_id')
        if trading_account_id:
            try:
                trading_account = TradingAccount.objects.get(
                    account_id=trading_account_id,
                    user=user
                )
                transaction_data['trading_account'] = trading_account
            except TradingAccount.DoesNotExist:
                return Response({
                    'error': f'Trading account {trading_account_id} not found for user'
                }, status=status.HTTP_404_NOT_FOUND)
        
        # Handle withdrawal details
        if transaction_type in ['withdraw_trading', 'commission_withdrawal']:
            payout_to = data.get('payout_to')
            external_account = data.get('external_account')
            
            if payout_to:
                if payout_to not in ['bank', 'crypto']:
                    return Response({
                        'error': 'payout_to must be either "bank" or "crypto"'
                    }, status=status.HTTP_400_BAD_REQUEST)
                transaction_data['payout_to'] = payout_to
            
            if external_account:
                transaction_data['external_account'] = external_account
        
        # Handle internal transfers
        if transaction_type == 'internal_transfer':
            from_account_id = data.get('from_account_id')
            to_account_id = data.get('to_account_id')
            
            if not from_account_id or not to_account_id:
                return Response({
                    'error': 'Internal transfers require from_account_id and to_account_id'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                from_account = TradingAccount.objects.get(account_id=from_account_id)
                to_account = TradingAccount.objects.get(account_id=to_account_id)
                
                transaction_data['from_account'] = from_account
                transaction_data['to_account'] = to_account
            except TradingAccount.DoesNotExist:
                return Response({
                    'error': 'One or both trading accounts not found'
                }, status=status.HTTP_404_NOT_FOUND)
        
        # Create the transaction
        transaction = Transaction.objects.create(**transaction_data)
        
        # Serialize and return
        serializer = TransactionSerializer(transaction)
        
        logger.info(f"Created transaction {transaction.id} for user {user_id}")
        
        return Response({
            'message': 'Transaction created successfully',
            'transaction': serializer.data
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Error creating transaction: {str(e)}")
        return Response({
            'error': f'Failed to create transaction: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def approve_transaction(request, transaction_id):
    """
    Approve or reject a transaction.
    Expects data:
    {
        "action": "approve" or "reject",
        "note": "Optional approval note"
    }
    """
    try:
        # Check if this is an approve endpoint or reject endpoint based on URL
        if 'approve' in request.path:
            action = 'approve'
        elif 'reject' in request.path:
            action = 'reject'
        else:
            # Fall back to the action in the request body
            action = request.data.get('action')
        
        # Log the request path and determined action
        logger.info(f"Request path: {request.path}, Determined action: {action}")
        
        # Get note/comment from request data
        note = request.data.get('note') or request.data.get('comment', '')
        logger.info(f"Extracted note/comment: '{note}'")
        
        if action not in ['approve', 'reject']:
            return Response({
                'error': 'action must be either "approve" or "reject"'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get transaction
        try:
            transaction = Transaction.objects.get(id=transaction_id)
        except Transaction.DoesNotExist:
            return Response({
                'error': f'Transaction {transaction_id} not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Check if already processed
        if transaction.status != 'pending':
            return Response({
                'error': f'Transaction is already {transaction.status}'
            }, status=status.HTTP_400_BAD_REQUEST)
        

        # We will only mark the transaction as approved after any external
        # side-effects (MT5 deposit/withdraw) succeed. Prepare approval metadata
        # but don't persist `status` yet so we don't incorrectly count withdrawals
        # as approved if the external call fails.
        transaction.approved_by = request.user
        transaction.approved_at = timezone.now()

        # Create notification for user
        try:
            from adminPanel.utils.notification_utils import create_bank_transaction_notification
            transaction_type_map = {
                'deposit_trading': 'deposit',
                'withdraw_trading': 'withdrawal',
                'commission_withdrawal': 'withdrawal'
            }
            mapped_type = transaction_type_map.get(transaction.transaction_type, 'deposit')
            create_bank_transaction_notification(
                user=transaction.user,
                transaction_type=mapped_type,
                amount=transaction.amount,
                status='approved' if action == 'approve' else 'rejected'
            )
        except Exception as e:
            import logging
            logging.error(f"Error creating transaction notification: {str(e)}")

        mt5_result = None
        mt5_error = None
        mt5_debug = {}
        # Only perform MT5 balance update if approving
        if action == 'approve':
            try:
                # Ensure we have a valid TradingAccount object
                trading_account = transaction.trading_account
                if not trading_account and hasattr(transaction, 'account_id') and transaction.account_id:
                    try:
                        trading_account = TradingAccount.objects.get(account_id=transaction.account_id)
                        transaction.trading_account = trading_account
                        transaction.save(update_fields=['trading_account'])
                    except TradingAccount.DoesNotExist:
                        mt5_error = f"TradingAccount with account_id {transaction.account_id} not found."
                        logger.error(mt5_error)
                # Handle standard trading deposits/withdrawals
                if trading_account and transaction.transaction_type in ['deposit_trading', 'withdraw_trading']:
                    mt5 = MT5ManagerActions()
                    login_id = trading_account.account_id
                    amount = float(transaction.amount)
                    comment = f"Admin approval TX#{transaction.id}"
                    mt5_debug['login_id'] = login_id
                    mt5_debug['amount'] = amount
                    mt5_debug['comment'] = comment
                    mt5_debug['transaction_type'] = transaction.transaction_type
                    if transaction.transaction_type == 'deposit_trading':
                        mt5_result = mt5.deposit_funds(login_id, amount, comment)
                        mt5_debug['mt5_result'] = mt5_result
                    elif transaction.transaction_type == 'withdraw_trading':
                        mt5_result = mt5.withdraw_funds(login_id, amount, comment)
                        mt5_debug['mt5_result'] = mt5_result
                    logger.info(f"MT5ManagerActions called: {mt5_debug}")
                # Handle commission withdrawals: deposit commission amount into
                # the provided trading account for the IB (if available).
                elif transaction.transaction_type == 'commission_withdrawal':
                    # Verify sufficient commission balance
                    try:
                        available = transaction.user.total_earnings - transaction.user.total_commission_withdrawals
                    except Exception:
                        available = None

                    if available is None or transaction.amount <= available:
                        try:
                            if not trading_account or not trading_account.account_id:
                                raise Exception('No trading account specified for commission withdrawal')
                            mt5 = MT5ManagerActions()
                            login_id = trading_account.account_id
                            amount = float(transaction.amount)
                            comment = f"Commission withdrawal TX#{transaction.id}"
                            mt5_debug['login_id'] = login_id
                            mt5_debug['amount'] = amount
                            mt5_debug['comment'] = comment
                            mt5_debug['transaction_type'] = transaction.transaction_type
                            mt5_result = mt5.deposit_funds(int(login_id), amount, comment)
                            mt5_debug['mt5_result'] = mt5_result
                            logger.info(f"MT5 deposit for commission withdrawal: {mt5_debug}")
                        except Exception as e:
                            mt5_error = str(e)
                            logger.error(f"MT5 deposit error for commission withdrawal: {mt5_error} | Debug: {mt5_debug}")
                            return Response({'error': f'Failed to perform MT5 deposit for commission withdrawal: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    else:
                        logger.warning(f"Insufficient commission balance for TX#{transaction.id}: requested={transaction.amount}, available={available}")
                        return Response({'error': 'Insufficient commission balance.'}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                mt5_error = str(e)
                logger.error(f"MT5ManagerActions error: {mt5_error} | Debug: {mt5_debug}")


        # Only save the admin's entered comment, no template or default text
        # Debug logging for request data and comment fields
        logger.info(f"Request data: {request.data}")
        logger.info(f"Note value: '{note}'")
        
        if note is not None:
            transaction.admin_comment = note
            logger.info(f"Set admin_comment to: '{transaction.admin_comment}'")

        # Set final status only after external operations succeeded
        transaction.status = 'approved' if action == 'approve' else 'rejected'

        # Force update fields to ensure admin_comment and approval metadata are saved
        transaction.save(update_fields=['status', 'approved_by', 'approved_at', 'admin_comment'])
        logger.info(f"After save - Transaction {transaction_id} admin_comment: '{transaction.admin_comment}'")

        # Read directly from database to verify save
        fresh_tx = Transaction.objects.get(id=transaction_id)
        logger.info(f"After fresh DB query - Transaction {transaction_id} admin_comment: '{fresh_tx.admin_comment}'")

        # Serialize and return
        serializer = TransactionSerializer(transaction)

        logger.info(f"Transaction {transaction_id} {action}d by user {request.user.username}")

        response_data = {
            'message': f'Transaction {action}d successfully',
            'transaction': serializer.data,
            'debug_test': 'MT5 integration block reached',
        }

        if mt5_result is not None:
            response_data['mt5_result'] = mt5_result
        if mt5_error is not None:
            response_data['mt5_error'] = mt5_error
        if mt5_debug:
            response_data['mt5_debug'] = mt5_debug

        return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error {action}ing transaction {transaction_id}: {str(e)}")
        return Response({
            'error': f'Failed to {action} transaction: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def transaction_summary(request):
    """
    Get transaction summary statistics.
    """
    try:
        from django.db.models import Count, Sum, Q
        
        # Get summary stats
        summary = Transaction.objects.aggregate(
            total_count=Count('id'),
            total_amount=Sum('amount'),
            pending_count=Count('id', filter=Q(status='pending')),
            approved_count=Count('id', filter=Q(status='approved')),
            rejected_count=Count('id', filter=Q(status='rejected')),
            pending_amount=Sum('amount', filter=Q(status='pending')),
            approved_amount=Sum('amount', filter=Q(status='approved')),
        )
        
        # Get recent transactions
        recent_transactions = Transaction.objects.select_related(
            'user', 'trading_account', 'approved_by'
        ).order_by('-created_at')[:10]
        
        recent_data = TransactionSerializer(recent_transactions, many=True).data
        
        return Response({
            'summary': summary,
            'recent_transactions': recent_data
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting transaction summary: {str(e)}")
        return Response({
            'error': f'Failed to get transaction summary: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
