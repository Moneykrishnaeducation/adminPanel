"""
Admin Portal PAMM Views
Handles PAMM administration and transaction approvals
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Sum, Count
from django.db import transaction
from decimal import Decimal
from django.core.exceptions import ValidationError as DjangoValidationError

from adminPanel.models_pamm import PAMMAccount, PAMMParticipant, PAMMTransaction, PAMMEquitySnapshot
from adminPanel.serializers_pamm import (
    PAMMAccountSerializer,
    PAMMParticipantSerializer,
    PAMMTransactionSerializer,
    PAMMDetailSerializer,
    PAMMEquitySnapshotSerializer
)
from adminPanel.services.pamm_service import PAMMService
from adminPanel.permissions import IsAdminOrManager

import logging

logger = logging.getLogger(__name__)


class AdminPAMMListView(APIView):
    """List all PAMM accounts (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def get(self, request):
        search = request.query_params.get('search', '').strip()
        status_filter = request.query_params.get('status', '').strip()
        
        pamms = PAMMAccount.objects.all().select_related('manager')
        
        if search:
            pamms = pamms.filter(
                Q(name__icontains=search) |
                Q(manager__email__icontains=search) |
                Q(mt5_account_id__icontains=search)
            )
        
        if status_filter:
            pamms = pamms.filter(status=status_filter.upper())
        
        # Annotate with statistics
        pamms = pamms.annotate(
            investor_count=Count('participants', filter=Q(participants__role='INVESTOR', participants__units__gt=0))
        )
        
        serializer = PAMMAccountSerializer(pamms, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminPAMMDetailView(APIView):
    """Get detailed PAMM information (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def get(self, request, pamm_id):
        try:
            pamm = PAMMAccount.objects.get(id=pamm_id)
            serializer = PAMMDetailSerializer(pamm)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except PAMMAccount.DoesNotExist:
            return Response(
                {"error": "PAMM account not found"},
                status=status.HTTP_404_NOT_FOUND
            )


class AdminPAMMTransactionListView(APIView):
    """List all PAMM transactions (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def get(self, request):
        pamm_id = request.query_params.get('pamm_id')
        status_filter = request.query_params.get('status', 'PENDING').strip()
        transaction_type = request.query_params.get('type', '').strip()
        
        transactions = PAMMTransaction.objects.all().select_related(
            'pamm', 'participant__user', 'approved_by'
        )
        
        if pamm_id:
            transactions = transactions.filter(pamm_id=pamm_id)
        
        if status_filter:
            transactions = transactions.filter(status=status_filter.upper())
        
        if transaction_type:
            transactions = transactions.filter(transaction_type=transaction_type.upper())
        
        transactions = transactions.order_by('-created_at')
        
        serializer = PAMMTransactionSerializer(transactions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminApprovePAMMTransactionView(APIView):
    """Approve a pending PAMM transaction (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def post(self, request):
        transaction_id = request.data.get('transaction_id')
        
        if not transaction_id:
            return Response(
                {"error": "transaction_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            transaction = PAMMTransaction.objects.get(id=transaction_id)
            
            if transaction.status != 'PENDING':
                return Response(
                    {"error": f"Transaction is already {transaction.status}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Route to appropriate approval method
            if transaction.transaction_type == 'MANAGER_DEPOSIT':
                result = PAMMService.approve_manager_deposit(transaction_id, request.user)
            elif transaction.transaction_type == 'MANAGER_WITHDRAW':
                result = PAMMService.approve_manager_withdraw(transaction_id, request.user)
            elif transaction.transaction_type == 'INVESTOR_DEPOSIT':
                result = PAMMService.approve_investor_deposit(transaction_id, request.user)
            elif transaction.transaction_type == 'INVESTOR_WITHDRAW':
                result = PAMMService.approve_investor_withdraw(transaction_id, request.user)
            else:
                return Response(
                    {"error": "Unknown transaction type"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get updated transaction
            transaction.refresh_from_db()
            serializer = PAMMTransactionSerializer(transaction)
            
            return Response({
                "success": True,
                "message": "Transaction approved successfully",
                "transaction": serializer.data,
                "details": result
            }, status=status.HTTP_200_OK)
            
        except PAMMTransaction.DoesNotExist:
            return Response(
                {"error": "Transaction not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except (ValueError, DjangoValidationError) as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error approving transaction: {str(e)}")
            return Response(
                {"error": "Failed to approve transaction"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminRejectPAMMTransactionView(APIView):
    """Reject a pending PAMM transaction (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def post(self, request):
        transaction_id = request.data.get('transaction_id')
        reason = request.data.get('reason', 'Rejected by admin').strip()
        
        if not transaction_id:
            return Response(
                {"error": "transaction_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            result = PAMMService.reject_transaction(
                transaction_id=transaction_id,
                rejected_by=request.user,
                reason=reason
            )
            
            # Get updated transaction
            transaction = PAMMTransaction.objects.get(id=transaction_id)
            serializer = PAMMTransactionSerializer(transaction)
            
            return Response({
                "success": True,
                "message": "Transaction rejected",
                "transaction": serializer.data
            }, status=status.HTTP_200_OK)
            
        except (PAMMTransaction.DoesNotExist, DjangoValidationError) as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_404_NOT_FOUND
            )


class AdminUpdatePAMMEquityView(APIView):
    """Update PAMM equity from MT5 (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def post(self, request):
        pamm_id = request.data.get('pamm_id')
        new_equity = request.data.get('equity')
        
        if not pamm_id or new_equity is None:
            return Response(
                {"error": "pamm_id and equity are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            result = PAMMService.update_pamm_equity(
                pamm_id=pamm_id,
                new_equity=Decimal(str(new_equity))
            )
            
            return Response({
                "success": True,
                "message": "Equity updated successfully",
                **result
            }, status=status.HTTP_200_OK)
            
        except (ValueError, DjangoValidationError) as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class AdminCalculateManagerFeeView(APIView):
    """Calculate and apply manager performance fee (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def post(self, request):
        pamm_id = request.data.get('pamm_id')
        
        if not pamm_id:
            return Response(
                {"error": "pamm_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            result = PAMMService.calculate_manager_fee(pamm_id=pamm_id)
            
            return Response({
                "success": True,
                **result
            }, status=status.HTTP_200_OK)
            
        except (ValueError, DjangoValidationError) as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class AdminPAMMParticipantsView(APIView):
    """List all participants in a PAMM (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def get(self, request, pamm_id):
        try:
            pamm = PAMMAccount.objects.get(id=pamm_id)
            
            participants = PAMMParticipant.objects.filter(pamm=pamm).select_related('user')
            serializer = PAMMParticipantSerializer(participants, many=True)
            
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except PAMMAccount.DoesNotExist:
            return Response(
                {"error": "PAMM account not found"},
                status=status.HTTP_404_NOT_FOUND
            )


class AdminPAMMEquityHistoryView(APIView):
    """Get PAMM equity history for charting (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def get(self, request, pamm_id):
        try:
            pamm = PAMMAccount.objects.get(id=pamm_id)
            
            # Get last N snapshots
            limit = int(request.query_params.get('limit', 100))
            snapshots = PAMMEquitySnapshot.objects.filter(pamm=pamm)[:limit]
            
            serializer = PAMMEquitySnapshotSerializer(snapshots, many=True)
            
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except PAMMAccount.DoesNotExist:
            return Response(
                {"error": "PAMM account not found"},
                status=status.HTTP_404_NOT_FOUND
            )


class AdminPAMMStatisticsView(APIView):
    """Get overall PAMM statistics (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def get(self, request):
        # Overall statistics
        total_pamms = PAMMAccount.objects.count()
        active_pamms = PAMMAccount.objects.filter(status='ACTIVE').count()
        
        total_equity = PAMMAccount.objects.aggregate(
            total=Sum('total_equity')
        )['total'] or Decimal('0.00')
        
        total_investors = PAMMParticipant.objects.filter(
            role='INVESTOR',
            units__gt=0
        ).count()
        
        pending_transactions = PAMMTransaction.objects.filter(
            status='PENDING'
        ).count()
        
        pending_deposits = PAMMTransaction.objects.filter(
            status='PENDING',
            transaction_type__in=['MANAGER_DEPOSIT', 'INVESTOR_DEPOSIT']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        pending_withdrawals = PAMMTransaction.objects.filter(
            status='PENDING',
            transaction_type__in=['MANAGER_WITHDRAW', 'INVESTOR_WITHDRAW']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        return Response({
            "total_pamms": total_pamms,
            "active_pamms": active_pamms,
            "total_equity": str(total_equity),
            "total_investors": total_investors,
            "pending_transactions": pending_transactions,
            "pending_deposits": str(pending_deposits),
            "pending_withdrawals": str(pending_withdrawals)
        }, status=status.HTTP_200_OK)


class AdminTogglePAMMStatusView(APIView):
    """Toggle PAMM status (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def post(self, request):
        pamm_id = request.data.get('pamm_id')
        new_status = request.data.get('status', '').upper()
        
        if not pamm_id:
            return Response(
                {"error": "pamm_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        valid_statuses = ['ACTIVE', 'DISABLED', 'CLOSED']
        if new_status and new_status not in valid_statuses:
            return Response(
                {"error": f"Status must be one of {valid_statuses}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            pamm = PAMMAccount.objects.get(id=pamm_id)
            
            if new_status:
                pamm.status = new_status
            else:
                # Toggle between ACTIVE and DISABLED
                pamm.status = 'DISABLED' if pamm.status == 'ACTIVE' else 'ACTIVE'
            
            pamm.save()
            
            serializer = PAMMAccountSerializer(pamm)
            
            return Response({
                "success": True,
                "message": f"PAMM status updated to {pamm.status}",
                "pamm": serializer.data
            }, status=status.HTTP_200_OK)
            
        except PAMMAccount.DoesNotExist:
            return Response(
                {"error": "PAMM account not found"},
                status=status.HTTP_404_NOT_FOUND
            )


class AdminTogglePAMMAcceptingInvestorsView(APIView):
    """Toggle PAMM accepting investors (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def post(self, request):
        pamm_id = request.data.get('pamm_id')
        accepting = request.data.get('accepting')
        
        if not pamm_id:
            return Response(
                {"error": "pamm_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            pamm = PAMMAccount.objects.get(id=pamm_id)
            
            if accepting is not None:
                pamm.is_accepting_investors = bool(accepting)
            else:
                # Toggle
                pamm.is_accepting_investors = not pamm.is_accepting_investors
            
            pamm.save()
            
            serializer = PAMMAccountSerializer(pamm)
            
            return Response({
                "success": True,
                "message": f"PAMM is {'now' if pamm.is_accepting_investors else 'no longer'} accepting investors",
                "pamm": serializer.data
            }, status=status.HTTP_200_OK)
            
        except PAMMAccount.DoesNotExist:
            return Response(
                {"error": "PAMM account not found"},
                status=status.HTTP_404_NOT_FOUND
            )


class AdminPAMMTransactionDetailsView(APIView):
    """Get detailed transaction information (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def get(self, request, transaction_id):
        try:
            transaction = PAMMTransaction.objects.select_related(
                'pamm', 'participant__user', 'approved_by'
            ).get(id=transaction_id)
            
            serializer = PAMMTransactionSerializer(transaction)
            
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except PAMMTransaction.DoesNotExist:
            return Response(
                {"error": "Transaction not found"},
                status=status.HTTP_404_NOT_FOUND
            )


class AdminBulkApprovePAMMTransactionsView(APIView):
    """Bulk approve multiple transactions (Admin only)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def post(self, request):
        transaction_ids = request.data.get('transaction_ids', [])
        
        if not transaction_ids or not isinstance(transaction_ids, list):
            return Response(
                {"error": "transaction_ids must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        results = []
        errors = []
        
        for txn_id in transaction_ids:
            try:
                transaction = PAMMTransaction.objects.get(id=txn_id, status='PENDING')
                
                # Route to appropriate approval method
                if transaction.transaction_type == 'MANAGER_DEPOSIT':
                    PAMMService.approve_manager_deposit(txn_id, request.user)
                elif transaction.transaction_type == 'MANAGER_WITHDRAW':
                    PAMMService.approve_manager_withdraw(txn_id, request.user)
                elif transaction.transaction_type == 'INVESTOR_DEPOSIT':
                    PAMMService.approve_investor_deposit(txn_id, request.user)
                elif transaction.transaction_type == 'INVESTOR_WITHDRAW':
                    PAMMService.approve_investor_withdraw(txn_id, request.user)
                
                results.append({"transaction_id": txn_id, "status": "approved"})
                
            except Exception as e:
                errors.append({"transaction_id": txn_id, "error": str(e)})
        
        return Response({
            "success": len(errors) == 0,
            "approved_count": len(results),
            "error_count": len(errors),
            "results": results,
            "errors": errors
        }, status=status.HTTP_200_OK)


class AdminPAMMAccountsTableView(APIView):
    """PAMM Accounts table view with pagination (Admin Panel Table)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def get(self, request):
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        search = request.query_params.get('search', '').strip()
        
        # Base queryset
        pamms = PAMMAccount.objects.all().select_related('manager')
        
        # Search filter
        if search:
            pamms = pamms.filter(
                Q(name__icontains=search) |
                Q(manager__email__icontains=search) |
                Q(mt5_account_id__icontains=search) |
                Q(manager__first_name__icontains=search) |
                Q(manager__last_name__icontains=search)
            )
        
        # Get total count
        total = pamms.count()
        
        # Pagination
        start = (page - 1) * page_size
        end = start + page_size
        pamms = pamms[start:end]
        
        # Build response data
        data = []
        for pamm in pamms:
            # Get manager participant
            manager_participant = PAMMParticipant.objects.filter(
                pamm=pamm, role='MANAGER'
            ).first()
            
            # Get all participants for calculations
            participants = PAMMParticipant.objects.filter(pamm=pamm)
            investors = participants.filter(role='INVESTOR', units__gt=0)
            
            # Calculate totals
            total_deposited = sum(p.total_deposited for p in participants)
            total_withdrawn = sum(p.total_withdrawn for p in participants)
            net_invested = total_deposited - total_withdrawn
            total_profit = float(pamm.total_equity - net_invested)
            
            # Get transaction counts
            transaction_stats = PAMMTransaction.objects.filter(pamm=pamm).aggregate(
                total_transactions=Count('id'),
                deposits=Count('id', filter=Q(transaction_type__in=['MANAGER_DEPOSIT', 'INVESTOR_DEPOSIT'])),
                withdrawals=Count('id', filter=Q(transaction_type__in=['MANAGER_WITHDRAW', 'INVESTOR_WITHDRAW'])),
            )
            
            # Calculate performance metrics
            profit_percentage = (total_profit / float(net_invested) * 100) if net_invested > 0 else 0
            unit_price = float(pamm.unit_price())
            unit_price_change = ((unit_price - 1.0) / 1.0 * 100) if unit_price > 0 else 0
            
            # Build participant details
            participant_details = []
            for p in participants:
                participant_details.append({
                    'user_id': p.user.id,
                    'email': p.user.email,
                    'name': f"{p.user.first_name} {p.user.last_name}".strip() or p.user.email,
                    'role': p.role,
                    'units': float(p.units),
                    'current_balance': float(p.current_balance()),
                    'total_deposited': float(p.total_deposited),
                    'total_withdrawn': float(p.total_withdrawn),
                    'net_invested': float(p.total_deposited - p.total_withdrawn),
                    'profit_loss': float(p.profit_loss()),
                    'share_percentage': float(p.share_percentage()),
                    'joined_at': p.joined_at.isoformat() if p.joined_at else None,
                })
            
            data.append({
                'id': pamm.id,
                'name': pamm.name,
                'manager_name': f"{pamm.manager.first_name} {pamm.manager.last_name}".strip() or pamm.manager.email,
                'manager_email': pamm.manager.email,
                'manager_id': pamm.manager.id,
                'mt5_login': pamm.mt5_account_id,
                'pool_balance': float(pamm.total_equity),
                'manager_capital': float(manager_participant.current_balance()) if manager_participant else 0,
                'total_profit': total_profit,
                'profit_percentage': round(profit_percentage, 2),
                'profit_share': float(pamm.profit_share),
                'leverage': pamm.leverage,
                'risk_level': 'Medium',  # Placeholder
                'payout_frequency': 'Monthly',  # Placeholder
                'account_id': pamm.mt5_account_id,
                'is_enabled': pamm.is_accepting_investors,
                'status': pamm.status,
                'investor_count': investors.count(),
                'created_at': pamm.created_at.isoformat() if pamm.created_at else None,
                'last_equity_update': pamm.last_equity_update.isoformat() if pamm.last_equity_update else None,
                
                # Unit-based metrics
                'total_units': float(pamm.total_units),
                'unit_price': unit_price,
                'unit_price_change_pct': round(unit_price_change, 2),
                'high_water_mark': float(pamm.high_water_mark),
                
                # Financial summary
                'total_deposited': float(total_deposited),
                'total_withdrawn': float(total_withdrawn),
                'net_invested': float(net_invested),
                
                # Transaction stats
                'total_transactions': transaction_stats['total_transactions'] or 0,
                'total_deposits': transaction_stats['deposits'] or 0,
                'total_withdrawals': transaction_stats['withdrawals'] or 0,
                
                # Participant details (optional, can be verbose)
                'participants': participant_details,
                'participant_count': len(participant_details),
            })
        
        return Response({
            'data': data,
            'total': total,
            'page': page,
            'page_size': page_size,
        }, status=status.HTTP_200_OK)


class AdminPAMMInvestorsTableView(APIView):
    """PAMM Investors table view with pagination (Admin Panel Table)"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def get(self, request):
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        search = request.query_params.get('search', '').strip()
        
        # Base queryset - only investors
        participants = PAMMParticipant.objects.filter(
            role='INVESTOR'
        ).select_related('user', 'pamm', 'pamm__manager')
        
        # Search filter
        if search:
            participants = participants.filter(
                Q(user__email__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(pamm__name__icontains=search) |
                Q(pamm__manager__email__icontains=search)
            )
        
        # Get total count
        total = participants.count()
        
        # Pagination
        start = (page - 1) * page_size
        end = start + page_size
        participants = participants[start:end]
        
        # Build response data
        data = []
        for participant in participants:
            net_invested = participant.total_deposited - participant.total_withdrawn
            current_value = participant.current_balance()
            profit_loss = participant.profit_loss()
            # ROI based on original investment (total_deposited) rather than net_invested
            # This gives consistent ROI even when withdrawals exceed deposits
            roi_percentage = (float(profit_loss) / float(participant.total_deposited) * 100) if participant.total_deposited > 0 else 0
            
            # Get participant's transaction counts
            txn_stats = PAMMTransaction.objects.filter(participant=participant).aggregate(
                total_txns=Count('id'),
                deposits=Count('id', filter=Q(transaction_type='INVESTOR_DEPOSIT')),
                withdrawals=Count('id', filter=Q(transaction_type='INVESTOR_WITHDRAW')),
            )
            
            data.append({
                'id': participant.id,
                'user_id': participant.user.id,
                'investor_name': f"{participant.user.first_name} {participant.user.last_name}".strip() or participant.user.email,
                'investor_email': participant.user.email,
                'investorEmail': participant.user.email,  # Legacy field
                
                # PAMM details
                'pamm_id': participant.pamm.id,
                'pamm_name': participant.pamm.name,
                'manager_name': f"{participant.pamm.manager.first_name} {participant.pamm.manager.last_name}".strip() or participant.pamm.manager.email,
                'manager_email': participant.pamm.manager.email,
                'pamm_mt5_login': participant.pamm.mt5_account_id,
                'tradingAccountId': participant.pamm.mt5_account_id,
                
                # Financial details
                'amount': float(participant.total_deposited),
                'amountInvested': float(participant.total_deposited),  # Legacy
                'amount_invested': float(participant.total_deposited),
                'total_withdrawn': float(participant.total_withdrawn),
                'net_invested': float(net_invested),
                'current_value': float(current_value),
                'net_profit_loss': float(profit_loss),
                'profit': float(profit_loss),  # Legacy
                'roi_percentage': round(roi_percentage, 2),
                
                # Unit-based data
                'units': float(participant.units),
                'share_percentage': float(participant.share_percentage()),
                'unit_price': float(participant.pamm.unit_price()),
                
                # Transaction stats
                'total_transactions': txn_stats['total_txns'] or 0,
                'total_deposits': txn_stats['deposits'] or 0,
                'total_withdrawals': txn_stats['withdrawals'] or 0,
                
                # Metadata
                'joined_at': participant.joined_at.isoformat() if participant.joined_at else None,
                'last_transaction_at': participant.last_transaction_at.isoformat() if participant.last_transaction_at else None,
                'is_enabled': True,  # Investors don't have individual enable/disable
                'pam_account': participant.pamm.id,
                'investor': participant.user.id,
            })
        
        return Response({
            'data': data,
            'total': total,
            'page': page,
            'page_size': page_size,
        }, status=status.HTTP_200_OK)


class AdminDirectPAMMDepositView(APIView):
    """Direct PAMM deposit (no approval workflow) - Admin only"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    @transaction.atomic
    def post(self, request):
        account_id = request.data.get('account_id')  # MT5 account ID
        amount = request.data.get('amount')
        comment = request.data.get('comment', '')
        role = request.data.get('role', 'MANAGER')  # MANAGER or INVESTOR
        user_id = request.data.get('user_id')  # Required for INVESTOR role
        
        if not account_id or not amount:
            return Response(
                {"error": "account_id and amount are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                return Response(
                    {"error": "Amount must be greater than zero"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid amount format"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Find PAMM by MT5 account ID
            pamm = PAMMAccount.objects.get(mt5_account_id=account_id)
            
            # Find participant based on role
            if role == 'INVESTOR':
                if not user_id:
                    return Response(
                        {"error": "user_id is required for investor deposits"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                participant = PAMMParticipant.objects.get(
                    pamm=pamm,
                    user_id=user_id,
                    role='INVESTOR'
                )
            else:
                # Manager deposit
                participant = PAMMParticipant.objects.get(
                    pamm=pamm,
                    role='MANAGER'
                )
            
            # STEP 1: Perform MT5 deposit FIRST
            try:
                from adminPanel.mt5.services import MT5ManagerActions
                mt5 = MT5ManagerActions()
                mt5_success = mt5.deposit_funds(
                    login_id=int(account_id),
                    amount=float(amount),
                    comment=comment or f'PAMM {role} deposit'
                )
                
                if not mt5_success:
                    return Response(
                        {"error": "MT5 deposit failed. Database not updated."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
                
                logger.info(f"MT5 deposit successful for PAMM {pamm.name}")
            except Exception as mt5_error:
                logger.error(f"MT5 deposit failed for PAMM {pamm.name}: {str(mt5_error)}")
                return Response(
                    {"error": f"MT5 deposit failed: {str(mt5_error)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # STEP 2: MT5 succeeded, now update database
            # Calculate units at current unit price
            unit_price = pamm.unit_price()
            units_added = amount / unit_price
            
            # Update participant units and totals
            participant.units += units_added
            participant.total_deposited += amount
            participant.save()
            
            # Update PAMM totals
            pamm.total_units += units_added
            pamm.total_equity += amount
            pamm.save()
            
            # Create completed transaction record
            transaction = PAMMTransaction.objects.create(
                pamm=pamm,
                participant=participant,
                transaction_type='MANAGER_DEPOSIT' if role == 'MANAGER' else 'INVESTOR_DEPOSIT',
                amount=amount,
                units_added=units_added,
                units_removed=Decimal('0.00000000'),
                unit_price_at_transaction=unit_price,
                status='COMPLETED',
                approved_by=request.user,
                notes=comment or f'Direct admin deposit - {role}'
            )
            
            logger.info(f"Direct PAMM deposit completed: {pamm.name}, {role}, ${amount}")
            
            return Response({
                "success": True,
                "message": f"PAMM {role.lower()} deposit completed",
                "transaction_id": transaction.id,
                "amount": str(amount),
                "status": "completed",
                "participant_balance": str(participant.current_balance()),
                "participant_units": str(participant.units),
                "pamm_equity": str(pamm.total_equity),
                "unit_price": str(unit_price),
                "units_added": str(units_added)
            }, status=status.HTTP_201_CREATED)
            
        except PAMMAccount.DoesNotExist:
            return Response(
                {"error": f"PAMM account with MT5 ID {account_id} not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except PAMMParticipant.DoesNotExist:
            return Response(
                {"error": f"{role} participant not found for this PAMM"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error in direct PAMM deposit: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminDirectPAMMWithdrawView(APIView):
    """Direct PAMM withdrawal (no approval workflow) - Admin only"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    @transaction.atomic
    def post(self, request):
        account_id = request.data.get('account_id')  # MT5 account ID
        amount = request.data.get('amount')
        comment = request.data.get('comment', '')
        role = request.data.get('role', 'MANAGER')  # MANAGER or INVESTOR
        user_id = request.data.get('user_id')  # Required for INVESTOR role
        
        if not account_id or not amount:
            return Response(
                {"error": "account_id and amount are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                return Response(
                    {"error": "Amount must be greater than zero"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid amount format"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Find PAMM by MT5 account ID
            pamm = PAMMAccount.objects.get(mt5_account_id=account_id)
            
            # Find participant based on role
            if role == 'INVESTOR':
                if not user_id:
                    return Response(
                        {"error": "user_id is required for investor withdrawals"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                participant = PAMMParticipant.objects.get(
                    pamm=pamm,
                    user_id=user_id,
                    role='INVESTOR'
                )
            else:
                # Manager withdrawal
                participant = PAMMParticipant.objects.get(
                    pamm=pamm,
                    role='MANAGER'
                )
            
            # Pre-check validations
            unit_price = pamm.unit_price()
            units_removed = amount / unit_price
            
            # Check if participant has sufficient units
            if units_removed > participant.units:
                return Response(
                    {"error": f"Insufficient units. Available: {participant.units}, Required: {units_removed}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check if PAMM has sufficient equity
            if amount > pamm.total_equity:
                return Response(
                    {"error": f"Insufficient PAMM equity. Available: {pamm.total_equity}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # STEP 1: Perform MT5 withdrawal FIRST
            try:
                from adminPanel.mt5.services import MT5ManagerActions
                mt5 = MT5ManagerActions()
                mt5_success = mt5.withdraw_funds(
                    login_id=int(account_id),
                    amount=float(amount),
                    comment=comment or f'PAMM {role} withdrawal'
                )
                
                if not mt5_success:
                    return Response(
                        {"error": "MT5 withdrawal failed. Database not updated."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
                
                logger.info(f"MT5 withdrawal successful for PAMM {pamm.name}")
            except Exception as mt5_error:
                logger.error(f"MT5 withdrawal failed for PAMM {pamm.name}: {str(mt5_error)}")
                return Response(
                    {"error": f"MT5 withdrawal failed: {str(mt5_error)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # STEP 2: MT5 succeeded, now update database
            # Update participant units and totals
            participant.units -= units_removed
            participant.total_withdrawn += amount
            participant.save()
            
            # Update PAMM totals
            pamm.total_units -= units_removed
            pamm.total_equity -= amount
            pamm.save()
            
            # Create completed transaction record
            transaction = PAMMTransaction.objects.create(
                pamm=pamm,
                participant=participant,
                transaction_type='MANAGER_WITHDRAW' if role == 'MANAGER' else 'INVESTOR_WITHDRAW',
                amount=amount,
                units_added=Decimal('0.00000000'),
                units_removed=units_removed,
                unit_price_at_transaction=unit_price,
                status='COMPLETED',
                approved_by=request.user,
                notes=comment or f'Direct admin withdrawal - {role}'
            )
            
            logger.info(f"Direct PAMM withdrawal completed: {pamm.name}, {role}, ${amount}")
            
            return Response({
                "success": True,
                "message": f"PAMM {role.lower()} withdrawal completed",
                "transaction_id": transaction.id,
                "amount": str(amount),
                "status": "completed",
                "participant_balance": str(participant.current_balance()),
                "participant_units": str(participant.units),
                "pamm_equity": str(pamm.total_equity),
                "unit_price": str(unit_price),
                "units_removed": str(units_removed)
            }, status=status.HTTP_201_CREATED)
            
        except PAMMAccount.DoesNotExist:
            return Response(
                {"error": f"PAMM account with MT5 ID {account_id} not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except PAMMParticipant.DoesNotExist:
            return Response(
                {"error": f"{role} participant not found for this PAMM"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error in direct PAMM withdrawal: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminDirectPAMMCreditInView(APIView):
    """Direct PAMM credit in (equity adjustment) - Admin only"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    @transaction.atomic
    def post(self, request):
        account_id = request.data.get('account_id')  # MT5 account ID
        amount = request.data.get('amount')
        comment = request.data.get('comment', 'Admin credit in - equity adjustment')
        
        if not account_id or not amount:
            return Response(
                {"error": "account_id and amount are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                return Response(
                    {"error": "Amount must be greater than zero"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid amount format"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Find PAMM by MT5 account ID
            pamm = PAMMAccount.objects.get(mt5_account_id=account_id)
            old_equity = pamm.total_equity
            
            # **MT5 OPERATION FIRST** - Perform MT5 credit in BEFORE database update
            try:
                from adminPanel.mt5.services import MT5ManagerActions
                mt5 = MT5ManagerActions()
                mt5.deposit_funds(
                    login_id=int(account_id),
                    amount=float(amount),
                    comment=comment
                )
                logger.info(f"MT5 credit in successful for PAMM {pamm.name}")
            except Exception as mt5_error:
                logger.error(f"MT5 credit in failed for PAMM {pamm.name}: {str(mt5_error)}")
                return Response(
                    {"error": f"MT5 credit in operation failed: {str(mt5_error)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # **DATABASE UPDATE SECOND** - Update PAMM equity (increases unit price, doesn't add units)
            pamm.total_equity += amount
            pamm.save()
            
            logger.info(f"Direct PAMM credit in: {pamm.name}, ${amount}, equity: ${old_equity} -> ${pamm.total_equity}")
            
            return Response({
                "success": True,
                "message": "PAMM credit in completed",
                "amount": str(amount),
                "status": "completed",
                "old_equity": str(old_equity),
                "new_equity": str(pamm.total_equity),
                "unit_price": str(pamm.unit_price())
            }, status=status.HTTP_201_CREATED)
            
        except PAMMAccount.DoesNotExist:
            return Response(
                {"error": f"PAMM account with MT5 ID {account_id} not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error in direct PAMM credit in: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminDirectPAMMCreditOutView(APIView):
    """Direct PAMM credit out (equity adjustment) - Admin only"""
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    @transaction.atomic
    def post(self, request):
        account_id = request.data.get('account_id')  # MT5 account ID
        amount = request.data.get('amount')
        comment = request.data.get('comment', 'Admin credit out - equity adjustment')
        
        if not account_id or not amount:
            return Response(
                {"error": "account_id and amount are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                return Response(
                    {"error": "Amount must be greater than zero"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid amount format"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Find PAMM by MT5 account ID
            pamm = PAMMAccount.objects.get(mt5_account_id=account_id)
            
            # Check if PAMM has sufficient equity
            if amount > pamm.total_equity:
                return Response(
                    {"error": f"Insufficient PAMM equity. Available: {pamm.total_equity}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            old_equity = pamm.total_equity
            
            # **MT5 OPERATION FIRST** - Perform MT5 credit out BEFORE database update
            try:
                from adminPanel.mt5.services import MT5ManagerActions
                mt5 = MT5ManagerActions()
                mt5.withdraw_funds(
                    login_id=int(account_id),
                    amount=float(amount),
                    comment=comment
                )
                logger.info(f"MT5 credit out successful for PAMM {pamm.name}")
            except Exception as mt5_error:
                logger.error(f"MT5 credit out failed for PAMM {pamm.name}: {str(mt5_error)}")
                return Response(
                    {"error": f"MT5 credit out operation failed: {str(mt5_error)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # **DATABASE UPDATE SECOND** - Update PAMM equity (decreases unit price, doesn't remove units)
            pamm.total_equity -= amount
            pamm.save()
            
            logger.info(f"Direct PAMM credit out: {pamm.name}, ${amount}, equity: ${old_equity} -> ${pamm.total_equity}")
            
            return Response({
                "success": True,
                "message": "PAMM credit out completed",
                "amount": str(amount),
                "status": "completed",
                "old_equity": str(old_equity),
                "new_equity": str(pamm.total_equity),
                "unit_price": str(pamm.unit_price())
            }, status=status.HTTP_201_CREATED)
            
        except PAMMAccount.DoesNotExist:
            return Response(
                {"error": f"PAMM account with MT5 ID {account_id} not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error in direct PAMM credit out: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


