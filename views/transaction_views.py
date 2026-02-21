from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django.utils import timezone
from ..decorators import role_required
from ..roles import UserRole
from ..models import Transaction
from ..serializers import TransactionSerializer
from ..permissions import OrPermission, IsAdmin, IsManager, IsAdminOrManager

@api_view(['GET'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def transaction_history(request):
    try:
        if request.user.manager_admin_status == 'Admin':
            transactions = Transaction.objects.all()
        else:
            # For managers, only show transactions of their assigned clients (created_by)
            transactions = Transaction.objects.filter(user__created_by=request.user)
            
        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def transaction_details(request, transaction_id):
    try:
        transaction = Transaction.objects.get(id=transaction_id)
        
        # Check if user has permission to view this transaction
        if request.user.manager_admin_status == 'Manager' and getattr(transaction.user, 'created_by', None) != request.user:
            return Response({"error": "You don't have permission to view this transaction"}, 
                          status=status.HTTP_403_FORBIDDEN)
            
        serializer = TransactionSerializer(transaction)
        return Response(serializer.data)
    except Transaction.DoesNotExist:
        return Response({"error": "Transaction not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def transaction_approve(request, transaction_id):
    return Response({"message": f"Transaction {transaction_id} approved"})

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def transaction_reject(request, transaction_id):
    return Response({"message": f"Transaction {transaction_id} rejected"})

@api_view(['GET'])
@permission_classes([IsAuthenticated])  # Temporarily use basic auth for testing
def get_recent_deposits(request):
    """
    Get recent deposit transactions for admin dashboard
    """
    try:
        user = request.user
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        
        # Grab search param if provided
        search = request.GET.get('search', '')

        # Filter deposits based on user role
        if user.manager_admin_status == 'Admin':
            deposits = Transaction.objects.filter(
                transaction_type='deposit_trading'
            ).order_by('-created_at')
        else:
                # For managers, only show transactions of their assigned clients (created_by)
            deposits = Transaction.objects.filter(
                transaction_type='deposit_trading',
                user__created_by=user
            ).order_by('-created_at')

        # Exclude CheesePay transactions and only include approved deposits
        deposits = deposits.exclude(Q(source='CheesePay') & Q(status__in=['pending', 'failed']))

        # Apply search filtering (username, email, trading account id, id, description)
        if search:
            deposits = deposits.filter(
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search) |
                Q(trading_account__account_id__icontains=search) |
                Q(id__icontains=search) |
                Q(description__icontains=search)
            )

        # Pagination
        start = (page - 1) * page_size
        end = start + page_size
        paginated_deposits = deposits[start:end]
        
        serializer = TransactionSerializer(paginated_deposits, many=True)
        return Response({
            "results": serializer.data,
            "total": deposits.count(),
            "page": page,
            "page_size": page_size
        })
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def get_recent_withdrawals(request):
    """
    Get recent withdrawal transactions for admin dashboard
    """
    try:
        user = request.user
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        
        # Grab search param if provided
        search = request.GET.get('search', '')

        # Filter withdrawals based on user role
        if user.manager_admin_status == 'Admin':
            withdrawals = Transaction.objects.filter(
                Q(transaction_type='withdraw_trading') | 
                Q(transaction_type='commission_withdrawal')
            ).order_by('-created_at')
        else:
                # For managers, only show transactions of their assigned clients (created_by)
            withdrawals = Transaction.objects.filter(
                Q(transaction_type='withdraw_trading') | 
                Q(transaction_type='commission_withdrawal'),
                user__created_by=user
            ).order_by('-created_at')
        

        # Apply search filtering (username, email, trading account id, id, description)
        if search:
            withdrawals = withdrawals.filter(
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search) |
                Q(trading_account__account_id__icontains=search) |
                Q(id__icontains=search) |
                Q(description__icontains=search)
            )

        # Pagination
        start = (page - 1) * page_size
        end = start + page_size
        paginated_withdrawals = withdrawals[start:end]
        
        serializer = TransactionSerializer(paginated_withdrawals, many=True)
        return Response({
            "results": serializer.data,
            "total": withdrawals.count(),
            "page": page,
            "page_size": page_size
        })
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def get_recent_internal_transfers(request):
    """
    Get recent internal transfer transactions for admin dashboard
    """
    try:
        user = request.user
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        
        # Grab search param if provided
        search = request.GET.get('search', '')

        # Filter transfers based on user role
        if user.manager_admin_status == 'Admin':
            transfers = Transaction.objects.filter(
                transaction_type='internal_transfer'
            ).order_by('-created_at')
        else:
                # For managers, only show transactions of their assigned clients (created_by)
            transfers = Transaction.objects.filter(
                transaction_type='internal_transfer',
                user__created_by=user
            ).order_by('-created_at')
        

        # Apply search filtering (username, email, trading account id, id, description)
        if search:
            transfers = transfers.filter(
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search) |
                Q(trading_account__account_id__icontains=search) |
                Q(id__icontains=search) |
                Q(description__icontains=search)
            )

        # Pagination
        start = (page - 1) * page_size
        end = start + page_size
        paginated_transfers = transfers[start:end]
        
        serializer = TransactionSerializer(paginated_transfers, many=True)
        return Response({
            "results": serializer.data,
            "total": transfers.count(),
            "page": page,
            "page_size": page_size
        })
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])  # Temporarily use basic auth for testing
def admin_transactions_list(request):
    """
    Get all transactions for admin transactions page with filtering and pagination
    """
    try:
        user = request.user
        transaction_type = request.GET.get('type', 'all')  # all, deposits, withdrawals, transfers
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        search = request.GET.get('search', '')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        status_filter = request.GET.get('status')
        
        # Base queryset based on user role
        if user.manager_admin_status == 'Admin':
            transactions = Transaction.objects.all()
        else:
            # For managers, only show transactions of their assigned clients (created_by)
            transactions = Transaction.objects.filter(user__created_by=user)

        # Exclude CheesePay transactions and only include approved transactions
            transactions = transactions.exclude(Q(source='CheesePay') & Q(status__in=['pending', 'failed']))
        # Filter by transaction type
        if transaction_type == 'deposits':
            transactions = transactions.filter(
                Q(transaction_type='deposit_trading') | Q(transaction_type='deposit_prop')
            )
        elif transaction_type == 'withdrawals':
            transactions = transactions.filter(
                Q(transaction_type='withdraw_trading') | 
                Q(transaction_type='withdraw_prop') |
                Q(transaction_type='commission_withdrawal')
            )
        elif transaction_type == 'transfers':
            transactions = transactions.filter(transaction_type='internal_transfer')
        
        # Apply search filter
        if search:
            transactions = transactions.filter(
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search) |
                Q(trading_account__account_id__icontains=search) |
                Q(id__icontains=search) |
                Q(description__icontains=search)
            )
        
        # Apply date filters
        if start_date:
            transactions = transactions.filter(created_at__gte=start_date)
        if end_date:
            transactions = transactions.filter(created_at__lte=end_date)
        
        # Apply status filter
        if status_filter:
            transactions = transactions.filter(status=status_filter)
        
        # Order by creation date (newest first)
        transactions = transactions.order_by('-created_at')
        
        # Get total count before pagination
        total_count = transactions.count()
        
        # Apply pagination
        start = (page - 1) * page_size
        end = start + page_size
        paginated_transactions = transactions[start:end]
        
        # Serialize data
        serializer = TransactionSerializer(paginated_transactions, many=True)
        
        return Response({
            "results": serializer.data,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size
        })
        
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def pending_deposits_view(request):
    """Get pending deposit transactions"""
    try:
        # Filter for pending deposits (including PAMM deposits)
        deposits = Transaction.objects.filter(
            transaction_type__in=['deposit', 'deposit_trading', 'deposit_commission'],
            status='pending'
        ).select_related('user', 'trading_account')
        
        # Apply date filters if provided
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        search = request.GET.get('search')
        
        if start_date:
            deposits = deposits.filter(created_at__gte=start_date)
        if end_date:
            deposits = deposits.filter(created_at__lte=end_date)
        if search:
            deposits = deposits.filter(
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search) |
                Q(trading_account__account_id__icontains=search)
            )
        
        # For managers, only show transactions of their assigned clients (created_by)
        if request.user.manager_admin_status == 'Manager':
            deposits = deposits.filter(user__created_by=request.user)
        
        deposits = deposits.order_by('-created_at')

        # Pagination for pending endpoints
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        total = deposits.count()
        start = (page - 1) * page_size
        end = start + page_size
        paginated = deposits[start:end]

        # Use the TransactionSerializer to include document_url and other fields
        serializer = TransactionSerializer(paginated, many=True, context={'request': request})
        return Response({
            "results": serializer.data,
            "total": total,
            "page": page,
            "page_size": page_size
        })
        
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
@api_view(['GET'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def pending_withdrawals_view(request):
    """Get pending withdrawal transactions"""
    try:
        # Filter for pending withdrawals (including PAMM withdrawals)
        withdrawals = Transaction.objects.filter(
            status='pending',
            transaction_type__in=['withdrawal', 'withdraw_trading', 'commission_withdrawal']
        ).select_related('user', 'trading_account')
        
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Total pending withdrawals found: {withdrawals.count()}")
        logger.info(f"Transaction types: {list(withdrawals.values_list('transaction_type', flat=True))}")
        
        # Apply date filters if provided
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        search = request.GET.get('search')
        
        if start_date:
            withdrawals = withdrawals.filter(created_at__gte=start_date)
        if end_date:
            withdrawals = withdrawals.filter(created_at__lte=end_date)
        if search:
            withdrawals = withdrawals.filter(
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search) |
                Q(trading_account__account_id__icontains=search)
            )
        
        # Remove manager filtering: always show all pending withdrawals for admins and managers
        
        withdrawals = withdrawals.order_by('-created_at')

        # Pagination for pending endpoints
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        total = withdrawals.count()
        start = (page - 1) * page_size
        end = start + page_size
        paginated = withdrawals[start:end]

        # Use TransactionSerializer for consistent frontend keys
        serializer = TransactionSerializer(paginated, many=True)
        return Response({
            "results": serializer.data,
            "total": total,
            "page": page,
            "page_size": page_size
        })
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error in pending_withdrawals_view: {e}", exc_info=True)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def pending_transfers_view(request):
    """Get pending transfer transactions (commission transfers)"""
    try:
        # Filter for pending transfers/commission transfers
        transfers = Transaction.objects.filter(status='pending').filter(
            Q(transaction_type='internal_transfer') | Q(transaction_type='commission_transfer')
            
        ).select_related('user', 'trading_account')
        
        # Apply date filters if provided
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        search = request.GET.get('search')
        
        if start_date:
            transfers = transfers.filter(created_at__gte=start_date)
        if end_date:
            transfers = transfers.filter(created_at__lte=end_date)
        if search:
            transfers = transfers.filter(
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search) |
                Q(trading_account__account_id__icontains=search)
            )
        
        # For managers, only show transactions of their assigned clients (created_by)
        if request.user.manager_admin_status == 'Manager':
            transfers = transfers.filter(user__created_by=request.user)
        
        transfers = transfers.order_by('-created_at')

        # Pagination for pending endpoints
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        total = transfers.count()
        start = (page - 1) * page_size
        end = start + page_size
        paginated = transfers[start:end]

        # Format data for frontend
        data = []
        for transfer in paginated:
            data.append({
                'id': transfer.id,
                'created_at': transfer.created_at,
                'user_name': transfer.user.username,
                'user_email': transfer.user.email,
                'account_id': transfer.trading_account.account_id if transfer.trading_account else 'N/A',
                'amount': transfer.amount,
                'status': transfer.status,
                'notes': transfer.notes or '',
                'payment_method': getattr(transfer, 'payment_method', 'N/A')
            })

        return Response({
            "results": data,
            "total": total,
            "page": page,
            "page_size": page_size
        })
        
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def transaction_details_api(request, transaction_id):
    """Get detailed transaction information for API"""
    try:
        transaction = Transaction.objects.select_related('user', 'trading_account').get(id=transaction_id)
        
        # Check if user has permission to view this transaction
        if request.user.manager_admin_status == 'Manager' and getattr(transaction.user, 'created_by', None) != request.user:
            return Response({"error": "You don't have permission to view this transaction"}, 
                          status=status.HTTP_403_FORBIDDEN)
        
        data = {
            'id': transaction.id,
            'created_at': transaction.created_at,
            'user_name': transaction.user.username,
            'user_email': transaction.user.email,
            'account_id': transaction.trading_account.account_id if transaction.trading_account else 'N/A',
            'trading_account_id': transaction.trading_account.account_id if transaction.trading_account else 'N/A',
            'amount': transaction.amount,
            'payment_method': transaction.payment_method or 'N/A',
            'method': transaction.payment_method or 'N/A',
            'status': transaction.status,
            'transaction_type': transaction.transaction_type,
            'notes': transaction.notes or '',
            'approved_at': transaction.approved_at,
            'approved_by': transaction.approved_by.username if transaction.approved_by else None
        }
        
        return Response(data)
        
    except Transaction.DoesNotExist:
        return Response({"error": "Transaction not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def approve_transaction_api(request):
    """Approve a transaction via API"""
    try:
        transaction_id = request.data.get('transaction_id')
        transaction_type = request.data.get('transaction_type')
        
        if not transaction_id:
            return Response({"error": "Transaction ID is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        transaction = Transaction.objects.get(id=transaction_id)
        
        # Check if user has permission to approve this transaction
        if request.user.manager_admin_status == 'Manager' and getattr(transaction.user, 'created_by', None) != request.user:
            return Response({"error": "You don't have permission to approve this transaction"}, 
                          status=status.HTTP_403_FORBIDDEN)
        
        # Handle PAMM manager capital adjustments and MT5 operations
        if transaction.source in ['PAMM_MANAGER', 'PAMM']:
            from clientPanel.models import PAMAccount, PAMInvestment
            from decimal import Decimal
            
            # Find the PAMM account by mt5_login from trading_account
            if transaction.trading_account:
                pamm_account = PAMAccount.objects.filter(
                    mt5_login=transaction.trading_account.account_id
                ).first()
                
                if pamm_account:
                    # Handle MANAGER deposits/withdrawals
                    if transaction.source == 'PAMM_MANAGER':
                        # Manager deposit approved - increase manager_capital + MT5 deposit
                        if transaction.transaction_type == 'deposit_trading':
                            pamm_account.manager_capital = Decimal(str(pamm_account.manager_capital)) + Decimal(str(transaction.amount))
                            pamm_account.save()
                            
                            # Perform MT5 deposit
                            try:
                                from adminPanel.mt5.services import MT5ManagerActions
                                mt5_manager = MT5ManagerActions()
                                mt5_manager.deposit_funds(
                                    login_id=int(transaction.trading_account.account_id),
                                    amount=float(transaction.amount),
                                    comment=f"Manager deposit to PAMM {pamm_account.name}"
                                )
                                # Update TradingAccount balance
                                new_balance = mt5_manager.get_balance(int(transaction.trading_account.account_id))
                                if new_balance is not None:
                                    transaction.trading_account.balance = Decimal(str(new_balance))
                                    transaction.trading_account.save()
                            except Exception as e:
                                import logging
                                logging.getLogger(__name__).warning(f"MT5 deposit failed for manager PAMM deposit: {e}")
                        
                        # Manager withdrawal approved - decrease manager_capital + MT5 withdrawal
                        elif transaction.transaction_type == 'withdraw_trading':
                            current_capital = Decimal(str(pamm_account.manager_capital))
                            withdrawal_amount = Decimal(str(transaction.amount))
                            # Reduce capital (min 0)
                            pamm_account.manager_capital = max(current_capital - withdrawal_amount, Decimal('0'))
                            pamm_account.save()
                            
                            # Perform MT5 withdrawal
                            try:
                                from adminPanel.mt5.services import MT5ManagerActions
                                mt5_manager = MT5ManagerActions()
                                mt5_manager.withdraw_funds(
                                    login_id=int(transaction.trading_account.account_id),
                                    amount=float(transaction.amount),
                                    comment=f"Manager withdrawal from PAMM {pamm_account.name}"
                                )
                                # Update TradingAccount balance
                                new_balance = mt5_manager.get_balance(int(transaction.trading_account.account_id))
                                if new_balance is not None:
                                    transaction.trading_account.balance = Decimal(str(new_balance))
                                    transaction.trading_account.save()
                            except Exception as e:
                                import logging
                                logging.getLogger(__name__).warning(f"MT5 withdrawal failed for manager PAMM withdrawal: {e}")
                    
                    # Handle INVESTOR deposits/withdrawals
                    elif transaction.source == 'PAMM':
                        # Find the investor's PAMInvestment
                        investment = PAMInvestment.objects.filter(
                            pam_account=pamm_account,
                            investor=transaction.user
                        ).first()
                        
                        if investment:
                            # Investor deposit approved - increase investment amount + MT5 deposit
                            if transaction.transaction_type == 'deposit_trading':
                                investment.amount = Decimal(str(investment.amount)) + Decimal(str(transaction.amount))
                                investment.save()
                                
                                # Perform MT5 deposit to the PAMM pool
                                import logging
                                logger = logging.getLogger(__name__)
                                logger.info(f"[PAMM INVESTOR DEPOSIT] Starting MT5 deposit for transaction {transaction.id}: ${transaction.amount} to account {transaction.trading_account.account_id}")
                                
                                mt5_success = False
                                try:
                                    from adminPanel.mt5.services import MT5ManagerActions
                                    mt5_manager = MT5ManagerActions()
                                    
                                    # Get balance before deposit
                                    balance_before = mt5_manager.get_balance(int(transaction.trading_account.account_id))
                                    logger.info(f"[PAMM INVESTOR DEPOSIT] MT5 balance BEFORE deposit: ${balance_before}")
                                    
                                    # Perform deposit
                                    mt5_success = mt5_manager.deposit_funds(
                                        login_id=int(transaction.trading_account.account_id),
                                        amount=float(transaction.amount),
                                        comment=f"Investor deposit to PAMM {pamm_account.name}"
                                    )
                                    
                                    logger.info(f"[PAMM INVESTOR DEPOSIT] MT5 deposit result: {'SUCCESS' if mt5_success else 'FAILED'}")
                                    
                                    # Update TradingAccount balance
                                    new_balance = mt5_manager.get_balance(int(transaction.trading_account.account_id))
                                    logger.info(f"[PAMM INVESTOR DEPOSIT] MT5 balance AFTER deposit: ${new_balance} (expected: ${balance_before + float(transaction.amount) if balance_before else 'N/A'})")
                                    
                                    if new_balance is not None:
                                        transaction.trading_account.balance = Decimal(str(new_balance))
                                        transaction.trading_account.save()
                                        logger.info(f"[PAMM INVESTOR DEPOSIT] TradingAccount balance updated to ${new_balance}")
                                    else:
                                        logger.warning(f"[PAMM INVESTOR DEPOSIT] Could not retrieve new balance from MT5")
                                        
                                except Exception as e:
                                    logger.error(f"[PAMM INVESTOR DEPOSIT] MT5 deposit FAILED with exception: {e}", exc_info=True)
                                
                                # Add note to transaction if MT5 failed
                                if not mt5_success:
                                    transaction.notes = (transaction.notes or '') + f"\n[WARNING] MT5 deposit may have failed - please verify account {transaction.trading_account.account_id} balance manually."
                                    transaction.save()
                            
                            # Investor withdrawal approved - decrease investment amount + MT5 withdrawal
                            elif transaction.transaction_type == 'withdraw_trading':
                                current_amount = Decimal(str(investment.amount))
                                withdrawal_amount = Decimal(str(transaction.amount))
                                # Reduce investment (min 0)
                                investment.amount = max(current_amount - withdrawal_amount, Decimal('0'))
                                investment.save()
                                
                                # Perform MT5 withdrawal from the PAMM pool
                                try:
                                    from adminPanel.mt5.services import MT5ManagerActions
                                    mt5_manager = MT5ManagerActions()
                                    mt5_manager.withdraw_funds(
                                        login_id=int(transaction.trading_account.account_id),
                                        amount=float(transaction.amount),
                                        comment=f"Investor withdrawal from PAMM {pamm_account.name}"
                                    )
                                    # Update TradingAccount balance
                                    new_balance = mt5_manager.get_balance(int(transaction.trading_account.account_id))
                                    if new_balance is not None:
                                        transaction.trading_account.balance = Decimal(str(new_balance))
                                        transaction.trading_account.save()
                                except Exception as e:
                                    import logging
                                    logging.getLogger(__name__).warning(f"MT5 withdrawal failed for investor PAMM withdrawal: {e}")
        
        # Update transaction status
        transaction.status = 'approved'
        transaction.approved_by = request.user
        transaction.approved_at = timezone.now()
        transaction.save()
        
        return Response({
            "message": f"Transaction {transaction_id} approved successfully",
            "transaction_id": transaction_id,
            "status": "approved"
        })
        
    except Transaction.DoesNotExist:
        return Response({"error": "Transaction not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error approving transaction: {e}", exc_info=True)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def reject_transaction_api(request):
    """Reject a transaction via API"""
    try:
        transaction_id = request.data.get('transaction_id')
        transaction_type = request.data.get('transaction_type')
        reason = request.data.get('reason', '')
        
        if not transaction_id:
            return Response({"error": "Transaction ID is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        transaction = Transaction.objects.get(id=transaction_id)
        
        # Check if user has permission to reject this transaction
        if request.user.manager_admin_status == 'Manager' and getattr(transaction.user, 'created_by', None) != request.user:
            return Response({"error": "You don't have permission to reject this transaction"}, 
                          status=status.HTTP_403_FORBIDDEN)
        
        # Update transaction status
        transaction.status = 'rejected'
        transaction.approved_by = request.user
        transaction.approved_at = timezone.now()
        if reason:
            transaction.notes = f"{transaction.notes}\nRejection reason: {reason}" if transaction.notes else f"Rejection reason: {reason}"
        transaction.save()
        
        return Response({
            "message": f"Transaction {transaction_id} rejected successfully",
            "transaction_id": transaction_id,
            "status": "rejected",
            "reason": reason
        })
        
    except Transaction.DoesNotExist:
        return Response({"error": "Transaction not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
