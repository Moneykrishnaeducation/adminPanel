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
from ..models_pamm import PAMMTransaction
from ..serializers_pamm import PAMMTransactionSerializer

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
    """Get pending deposit transactions (including PAMM deposits)"""
    try:
        # Filter for regular pending deposits
        deposits = Transaction.objects.filter(
            transaction_type__in=['deposit', 'deposit_trading', 'deposit_commission'],
            status='pending'
        ).select_related('user', 'trading_account')
        
        # Filter for PAMM pending deposits
        pamm_deposits = PAMMTransaction.objects.filter(
            status='PENDING',
            transaction_type__in=['MANAGER_DEPOSIT', 'INVESTOR_DEPOSIT']
        ).select_related('pamm', 'participant__user', 'approved_by')
        
        # Apply date filters if provided
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        search = request.GET.get('search')
        
        if start_date:
            deposits = deposits.filter(created_at__gte=start_date)
            pamm_deposits = pamm_deposits.filter(created_at__gte=start_date)
        if end_date:
            deposits = deposits.filter(created_at__lte=end_date)
            pamm_deposits = pamm_deposits.filter(created_at__lte=end_date)
        if search:
            deposits = deposits.filter(
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search) |
                Q(trading_account__account_id__icontains=search)
            )
            pamm_deposits = pamm_deposits.filter(
                Q(participant__user__username__icontains=search) |
                Q(participant__user__email__icontains=search) |
                Q(pamm__name__icontains=search) |
                Q(pamm__mt5_account_id__icontains=search)
            )
        
        # For managers, only show transactions of their assigned clients (created_by)
        if request.user.manager_admin_status == 'Manager':
            deposits = deposits.filter(user__created_by=request.user)
            pamm_deposits = pamm_deposits.filter(participant__user__created_by=request.user)
        
        deposits = deposits.order_by('-created_at')
        pamm_deposits = pamm_deposits.order_by('-created_at')

        # Serialize both types
        regular_serializer = TransactionSerializer(deposits, many=True, context={'request': request})
        pamm_serializer = PAMMTransactionSerializer(pamm_deposits, many=True)
        
        # Combine results with a type indicator
        regular_data = regular_serializer.data
        for item in regular_data:
            item['transaction_category'] = 'REGULAR'
            
        pamm_data = pamm_serializer.data
        for item in pamm_data:
            item['transaction_category'] = 'PAMM'
            # Map PAMM fields to match regular transaction structure for frontend compatibility
            item['user_email'] = item.get('participant_email', '')
            item['user_name'] = item.get('participant_name', '')
            item['username'] = item.get('participant_name', 'PAMM User')
            item['email'] = item.get('participant_email', '')
            item['account_id'] = item.get('pamm_name', '')
            item['trading_account_id'] = item.get('pamm_name', '')
            item['document_url'] = item.get('payment_proof', '')
            item['document'] = item.get('payment_proof', '')
            item['source'] = item.get('payment_method', 'PAMM')
            item['description'] = f"PAMM {item.get('transaction_type', '')} - {item.get('pamm_name', '')}"
            # Set transaction_type_display so frontend filter doesn't exclude PAMM deposits
            item['transaction_type_display'] = 'Deposit into Trading Account'
        
        # Combine and sort by created_at
        combined = regular_data + pamm_data
        combined.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # Pagination
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        total = len(combined)
        start = (page - 1) * page_size
        end = start + page_size
        paginated = combined[start:end]

        return Response({
            "results": paginated,
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
    """Get pending withdrawal transactions (including PAMM withdrawals)"""
    try:
        # Filter for regular pending withdrawals
        withdrawals = Transaction.objects.filter(
            status='pending',
            transaction_type__in=['withdrawal', 'withdraw_trading', 'commission_withdrawal']
        ).select_related('user', 'trading_account')
        
        # Filter for PAMM pending withdrawals
        pamm_withdrawals = PAMMTransaction.objects.filter(
            status='PENDING',
            transaction_type__in=['MANAGER_WITHDRAW', 'INVESTOR_WITHDRAW']
        ).select_related('pamm', 'participant__user', 'approved_by')
        
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Total regular pending withdrawals found: {withdrawals.count()}")
        logger.info(f"Total PAMM pending withdrawals found: {pamm_withdrawals.count()}")
        
        # Apply date filters if provided
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        search = request.GET.get('search')
        
        if start_date:
            withdrawals = withdrawals.filter(created_at__gte=start_date)
            pamm_withdrawals = pamm_withdrawals.filter(created_at__gte=start_date)
        if end_date:
            withdrawals = withdrawals.filter(created_at__lte=end_date)
            pamm_withdrawals = pamm_withdrawals.filter(created_at__lte=end_date)
        if search:
            withdrawals = withdrawals.filter(
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search) |
                Q(trading_account__account_id__icontains=search)
            )
            pamm_withdrawals = pamm_withdrawals.filter(
                Q(participant__user__username__icontains=search) |
                Q(participant__user__email__icontains=search) |
                Q(pamm__name__icontains=search) |
                Q(pamm__mt5_account_id__icontains=search)
            )
        
        # Remove manager filtering: always show all pending withdrawals for admins and managers
        
        withdrawals = withdrawals.order_by('-created_at')
        pamm_withdrawals = pamm_withdrawals.order_by('-created_at')

        # Serialize both types
        regular_serializer = TransactionSerializer(withdrawals, many=True)
        pamm_serializer = PAMMTransactionSerializer(pamm_withdrawals, many=True)
        
        # Combine results with a type indicator
        regular_data = regular_serializer.data
        for item in regular_data:
            item['transaction_category'] = 'REGULAR'
            
        pamm_data = pamm_serializer.data
        for item in pamm_data:
            item['transaction_category'] = 'PAMM'
            # Map PAMM fields to match regular transaction structure for frontend compatibility
            item['user_email'] = item.get('participant_email', '')
            item['user_name'] = item.get('participant_name', '')
            item['username'] = item.get('participant_name', 'PAMM User')
            item['email'] = item.get('participant_email', '')
            item['account_id'] = item.get('pamm_name', '')
            item['trading_account_id'] = item.get('pamm_name', '')
            item['document_url'] = item.get('payment_proof', '')
            item['document'] = item.get('payment_proof', '')
            item['source'] = item.get('payment_method', 'PAMM')
            item['description'] = f"PAMM {item.get('transaction_type', '')} - {item.get('pamm_name', '')}"
            # Set transaction_type_display so frontend filter doesn't exclude PAMM withdrawals
            item['transaction_type_display'] = 'Withdrawal from Trading Account'
        
        # Combine and sort by created_at
        combined = regular_data + pamm_data
        combined.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # Pagination
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        total = len(combined)
        start = (page - 1) * page_size
        end = start + page_size
        paginated = combined[start:end]

        return Response({
            "results": paginated,
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
        
        # PAMM backend removed — PAMM-specific transaction handling deleted.
        # Any PAMM logic was removed as part of backend cleanup to avoid
        # importing deleted PAM models at runtime.
        
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
