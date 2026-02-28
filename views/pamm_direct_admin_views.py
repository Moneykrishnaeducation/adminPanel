"""
Admin Direct PAMM Transaction Views
Direct deposit/withdrawal operations for PAMM accounts (similar to trading account operations)
No approval workflow - instant execution
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from django.db import transaction as db_transaction
from django.core.exceptions import ValidationError as DjangoValidationError

from adminPanel.models_pamm import PAMMAccount, PAMMParticipant, PAMMTransaction
from adminPanel.services.pamm_service import PAMMService
from adminPanel.permissions import IsAdminOrManager
from adminPanel.mt5.services import MT5ManagerActions
from adminPanel.models import ActivityLog
from adminPanel.views.views import get_client_ip

import logging

logger = logging.getLogger(__name__)


class AdminDirectPAMMDepositView(APIView):
    """
    Direct PAMM deposit by admin (no approval needed)
    Similar to trading account DepositView
    """
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def post(self, request):
        """
        Direct deposit to PAMM account
        
        Request body:
        - pamm_id: PAMM account ID
        - participant_type: 'MANAGER' or 'INVESTOR'
        - participant_id: PAMMParticipant ID (optional if manager)
        - amount: Deposit amount
        - comment: Optional comment
        """
        pamm_id = request.data.get('pamm_id')
        participant_type = request.data.get('participant_type', 'MANAGER').upper()
        participant_id = request.data.get('participant_id')
        amount = request.data.get('amount')
        comment = request.data.get('comment', 'Admin direct deposit')
        
        # Validation
        if not pamm_id or not amount:
            return Response({
                "error": "pamm_id and amount are required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if participant_type not in ['MANAGER', 'INVESTOR']:
            return Response({
                "error": "participant_type must be 'MANAGER' or 'INVESTOR'"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                return Response({
                    "error": "Amount must be greater than zero"
                }, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError, InvalidOperation):
            return Response({
                "error": "Invalid amount format"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Get PAMM account
            pamm = PAMMAccount.objects.get(id=pamm_id)
            
            # Get participant
            if participant_type == 'MANAGER':
                participant = PAMMParticipant.objects.get(
                    pamm=pamm,
                    role='MANAGER'
                )
            elif participant_id:
                participant = PAMMParticipant.objects.get(
                    id=participant_id,
                    pamm=pamm,
                    role='INVESTOR'
                )
            else:
                return Response({
                    "error": "participant_id is required for investor deposits"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Execute direct deposit (skip approval workflow)
            with db_transaction.atomic():
                # Get current unit price
                unit_price = pamm.unit_price()
                
                # Calculate units to add
                units_to_add = amount / unit_price
                
                # Update participant units
                participant.units += units_to_add
                participant.total_deposited += amount
                participant.last_transaction_at = timezone.now()
                participant.save()
                
                # Update PAMM totals
                pamm.total_equity += amount
                pamm.total_units += units_to_add
                pamm.save()
                
                # Deposit to MT5 account if MT5 account exists
                mt5_success = False
                mt5_error = None
                if pamm.mt5_account_id:
                    try:
                        mt5_manager = MT5ManagerActions()
                        mt5_success = mt5_manager.deposit_funds(
                            login_id=int(pamm.mt5_account_id),
                            amount=float(amount),
                            comment=comment
                        )
                        
                        if mt5_success:
                            logger.info(f"✅ MT5 deposit successful for PAMM {pamm.name} (MT5: {pamm.mt5_account_id})")
                        else:
                            logger.warning(f"⚠️ MT5 deposit failed for PAMM {pamm.name}, but database updated")
                            mt5_error = "MT5 deposit operation failed"
                    except Exception as mt5_exception:
                        logger.error(f"❌ MT5 error during PAMM deposit: {str(mt5_exception)}")
                        mt5_error = str(mt5_exception)
                
                # Create transaction record
                txn = PAMMTransaction.objects.create(
                    pamm=pamm,
                    participant=participant,
                    transaction_type=f'{participant_type}_DEPOSIT',
                    amount=amount,
                    units_added=units_to_add,
                    units_removed=Decimal('0.00000000'),
                    unit_price_at_transaction=unit_price,
                    status='COMPLETED',
                    approved_by=request.user,
                    approved_at=timezone.now(),
                    completed_at=timezone.now(),
                    notes=comment + (" (MT5 Failed - Database Only)" if not mt5_success else "")
                )
                
                # Create activity log
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Direct PAMM deposit: ${amount} to {pamm.name} ({participant_type}). New equity: ${pamm.total_equity}",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=pamm.id,
                    related_object_type="PAMMAccount"
                )
                
                # Create equity snapshot
                PAMMService._create_equity_snapshot(pamm)
                
                logger.info(f"✅ Direct PAMM deposit completed: {txn.id} - ${amount} to {pamm.name}")
            
            return Response({
                "success": True,
                "message": "Direct deposit completed successfully" + (" (MT5 integration failed)" if not mt5_success else ""),
                "transaction_id": txn.id,
                "pamm_id": pamm.id,
                "pamm_name": pamm.name,
                "participant_type": participant_type,
                "participant_email": participant.user.email,
                "amount": str(amount),
                "units_added": str(units_to_add),
                "unit_price": str(unit_price),
                "new_participant_balance": str(participant.current_balance()),
                "new_participant_units": str(participant.units),
                "new_pamm_equity": str(pamm.total_equity),
                "new_pamm_total_units": str(pamm.total_units),
                "mt5_integration": mt5_success,
                "mt5_error": mt5_error if not mt5_success else None,
                "created_at": txn.created_at.isoformat()
            }, status=status.HTTP_201_CREATED)
            
        except PAMMAccount.DoesNotExist:
            return Response({
                "error": "PAMM account not found"
            }, status=status.HTTP_404_NOT_FOUND)
        except PAMMParticipant.DoesNotExist:
            return Response({
                "error": "Participant not found"
            }, status=status.HTTP_404_NOT_FOUND)
        except (ValueError, DjangoValidationError) as e:
            logger.error(f"Validation error in direct PAMM deposit: {str(e)}")
            return Response({
                "error": str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error in direct PAMM deposit: {str(e)}", exc_info=True)
            return Response({
                "error": f"Internal server error: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminDirectPAMMWithdrawView(APIView):
    """
    Direct PAMM withdrawal by admin (no approval needed)
    Similar to trading account WithdrawView
    """
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def post(self, request):
        """
        Direct withdrawal from PAMM account
        
        Request body:
        - pamm_id: PAMM account ID
        - participant_type: 'MANAGER' or 'INVESTOR'
        - participant_id: PAMMParticipant ID (optional if manager)
        - amount: Withdrawal amount
        - comment: Optional comment
        """
        pamm_id = request.data.get('pamm_id')
        participant_type = request.data.get('participant_type', 'MANAGER').upper()
        participant_id = request.data.get('participant_id')
        amount = request.data.get('amount')
        comment = request.data.get('comment', 'Admin direct withdrawal')
        
        # Validation
        if not pamm_id or not amount:
            return Response({
                "error": "pamm_id and amount are required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if participant_type not in ['MANAGER', 'INVESTOR']:
            return Response({
                "error": "participant_type must be 'MANAGER' or 'INVESTOR'"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                return Response({
                    "error": "Amount must be greater than zero"
                }, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError, InvalidOperation):
            return Response({
                "error": "Invalid amount format"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Get PAMM account
            pamm = PAMMAccount.objects.get(id=pamm_id)
            
            # Get participant
            if participant_type == 'MANAGER':
                participant = PAMMParticipant.objects.get(
                    pamm=pamm,
                    role='MANAGER'
                )
            elif participant_id:
                participant = PAMMParticipant.objects.get(
                    id=participant_id,
                    pamm=pamm,
                    role='INVESTOR'
                )
            else:
                return Response({
                    "error": "participant_id is required for investor withdrawals"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Execute direct withdrawal
            with db_transaction.atomic():
                # Get current unit price
                unit_price = pamm.unit_price()
                
                # Calculate units to remove
                units_to_remove = amount / unit_price
                
                # Check if participant has sufficient units
                if participant.units < units_to_remove:
                    return Response({
                        "error": f"Insufficient units. Available: {participant.units:.8f} units (${participant.current_balance():.2f}), Required: {units_to_remove:.8f} units (${amount:.2f})"
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # Update participant units
                participant.units -= units_to_remove
                participant.total_withdrawn += amount
                participant.last_transaction_at = timezone.now()
                participant.save()
                
                # Update PAMM totals
                pamm.total_equity -= amount
                pamm.total_units -= units_to_remove
                pamm.save()
                
                # Withdraw from MT5 account if MT5 account exists
                mt5_success = False
                mt5_error = None
                if pamm.mt5_account_id:
                    try:
                        mt5_manager = MT5ManagerActions()
                        mt5_success = mt5_manager.withdraw_funds(
                            login_id=int(pamm.mt5_account_id),
                            amount=float(amount),
                            comment=comment
                        )
                        
                        if mt5_success:
                            logger.info(f"✅ MT5 withdrawal successful for PAMM {pamm.name} (MT5: {pamm.mt5_account_id})")
                        else:
                            logger.warning(f"⚠️ MT5 withdrawal failed for PAMM {pamm.name}, but database updated")
                            mt5_error = "MT5 withdrawal operation failed"
                    except Exception as mt5_exception:
                        logger.error(f"❌ MT5 error during PAMM withdrawal: {str(mt5_exception)}")
                        mt5_error = str(mt5_exception)
                
                # Create transaction record
                txn = PAMMTransaction.objects.create(
                    pamm=pamm,
                    participant=participant,
                    transaction_type=f'{participant_type}_WITHDRAW',
                    amount=amount,
                    units_added=Decimal('0.00000000'),
                    units_removed=units_to_remove,
                    unit_price_at_transaction=unit_price,
                    status='COMPLETED',
                    approved_by=request.user,
                    approved_at=timezone.now(),
                    completed_at=timezone.now(),
                    notes=comment + (" (MT5 Failed - Database Only)" if not mt5_success else "")
                )
                
                # Create activity log
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Direct PAMM withdrawal: ${amount} from {pamm.name} ({participant_type}). New equity: ${pamm.total_equity}",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=pamm.id,
                    related_object_type="PAMMAccount"
                )
                
                # Create equity snapshot
                PAMMService._create_equity_snapshot(pamm)
                
                logger.info(f"✅ Direct PAMM withdrawal completed: {txn.id} - ${amount} from {pamm.name}")
            
            return Response({
                "success": True,
                "message": "Direct withdrawal completed successfully" + (" (MT5 integration failed)" if not mt5_success else ""),
                "transaction_id": txn.id,
                "pamm_id": pamm.id,
                "pamm_name": pamm.name,
                "participant_type": participant_type,
                "participant_email": participant.user.email,
                "amount": str(amount),
                "units_removed": str(units_to_remove),
                "unit_price": str(unit_price),
                "new_participant_balance": str(participant.current_balance()),
                "new_participant_units": str(participant.units),
                "new_pamm_equity": str(pamm.total_equity),
                "new_pamm_total_units": str(pamm.total_units),
                "mt5_integration": mt5_success,
                "mt5_error": mt5_error if not mt5_success else None,
                "created_at": txn.created_at.isoformat()
            }, status=status.HTTP_201_CREATED)
            
        except PAMMAccount.DoesNotExist:
            return Response({
                "error": "PAMM account not found"
            }, status=status.HTTP_404_NOT_FOUND)
        except PAMMParticipant.DoesNotExist:
            return Response({
                "error": "Participant not found"
            }, status=status.HTTP_404_NOT_FOUND)
        except (ValueError, DjangoValidationError) as e:
            logger.error(f"Validation error in direct PAMM withdrawal: {str(e)}")
            return Response({
                "error": str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error in direct PAMM withdrawal: {str(e)}", exc_info=True)
            return Response({
                "error": f"Internal server error: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminDirectPAMMCreditInView(APIView):
    """
    Direct credit-in to PAMM account (add equity without participant allocation)
    Similar to trading account credit operations
    """
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def post(self, request):
        """
        Direct credit-in to PAMM pool (increases total equity without changing units)
        
        Request body:
        - pamm_id: PAMM account ID
        - amount: Credit amount
        - comment: Optional comment
        """
        pamm_id = request.data.get('pamm_id')
        amount = request.data.get('amount')
        comment = request.data.get('comment', 'Admin credit-in')
        
        # Validation
        if not pamm_id or not amount:
            return Response({
                "error": "pamm_id and amount are required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                return Response({
                    "error": "Amount must be greater than zero"
                }, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError, InvalidOperation):
            return Response({
                "error": "Invalid amount format"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            pamm = PAMMAccount.objects.get(id=pamm_id)
            
            with db_transaction.atomic():
                old_equity = pamm.total_equity
                old_unit_price = pamm.unit_price()
                
                # Update total equity (units stay the same, so unit price increases)
                pamm.total_equity += amount
                pamm.save()
                
                new_unit_price = pamm.unit_price()
                
                # Deposit to MT5 if account exists
                mt5_success = False
                mt5_error = None
                if pamm.mt5_account_id:
                    try:
                        mt5_manager = MT5ManagerActions()
                        mt5_success = mt5_manager.deposit_funds(
                            login_id=int(pamm.mt5_account_id),
                            amount=float(amount),
                            comment=comment
                        )
                        if mt5_success:
                            logger.info(f"✅ MT5 credit-in successful for PAMM {pamm.name}")
                        else:
                            mt5_error = "MT5 credit operation failed"
                    except Exception as e:
                        logger.error(f"❌ MT5 error during credit-in: {str(e)}")
                        mt5_error = str(e)
                
                # Create transaction record
                txn = PAMMTransaction.objects.create(
                    pamm=pamm,
                    participant=None,  # No specific participant
                    transaction_type='CREDIT_IN',
                    amount=amount,
                    units_added=Decimal('0.00000000'),
                    units_removed=Decimal('0.00000000'),
                    unit_price_at_transaction=new_unit_price,
                    status='COMPLETED',
                    approved_by=request.user,
                    approved_at=timezone.now(),
                    completed_at=timezone.now(),
                    notes=comment
                )
                
                # Create activity log
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"PAMM Credit-In: ${amount} to {pamm.name}. Unit price: ${old_unit_price:.8f} → ${new_unit_price:.8f}",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=pamm.id,
                    related_object_type="PAMMAccount"
                )
                
                # Create equity snapshot
                PAMMService._create_equity_snapshot(pamm)
                
                logger.info(f"✅ PAMM credit-in completed: ${amount} to {pamm.name}")
            
            return Response({
                "success": True,
                "message": "Credit-in completed successfully",
                "transaction_id": txn.id,
                "pamm_id": pamm.id,
                "pamm_name": pamm.name,
                "amount": str(amount),
                "old_equity": str(old_equity),
                "new_equity": str(pamm.total_equity),
                "old_unit_price": str(old_unit_price),
                "new_unit_price": str(new_unit_price),
                "mt5_integration": mt5_success,
                "mt5_error": mt5_error if not mt5_success else None,
                "created_at": txn.created_at.isoformat()
            }, status=status.HTTP_201_CREATED)
            
        except PAMMAccount.DoesNotExist:
            return Response({
                "error": "PAMM account not found"
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error in PAMM credit-in: {str(e)}", exc_info=True)
            return Response({
                "error": f"Internal server error: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminDirectPAMMCreditOutView(APIView):
    """
    Direct credit-out from PAMM account (remove equity without participant deduction)
    Similar to trading account credit operations
    """
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    
    def post(self, request):
        """
        Direct credit-out from PAMM pool (decreases total equity without changing units)
        
        Request body:
        - pamm_id: PAMM account ID
        - amount: Credit amount
        - comment: Optional comment
        """
        pamm_id = request.data.get('pamm_id')
        amount = request.data.get('amount')
        comment = request.data.get('comment', 'Admin credit-out')
        
        # Validation
        if not pamm_id or not amount:
            return Response({
                "error": "pamm_id and amount are required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                return Response({
                    "error": "Amount must be greater than zero"
                }, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError, InvalidOperation):
            return Response({
                "error": "Invalid amount format"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            pamm = PAMMAccount.objects.get(id=pamm_id)
            
            # Check if PAMM has sufficient equity
            if pamm.total_equity < amount:
                return Response({
                    "error": f"Insufficient equity. Available: ${pamm.total_equity:.2f}, Requested: ${amount:.2f}"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            with db_transaction.atomic():
                old_equity = pamm.total_equity
                old_unit_price = pamm.unit_price()
                
                # Update total equity (units stay the same, so unit price decreases)
                pamm.total_equity -= amount
                pamm.save()
                
                new_unit_price = pamm.unit_price()
                
                # Withdraw from MT5 if account exists
                mt5_success = False
                mt5_error = None
                if pamm.mt5_account_id:
                    try:
                        mt5_manager = MT5ManagerActions()
                        mt5_success = mt5_manager.withdraw_funds(
                            login_id=int(pamm.mt5_account_id),
                            amount=float(amount),
                            comment=comment
                        )
                        if mt5_success:
                            logger.info(f"✅ MT5 credit-out successful for PAMM {pamm.name}")
                        else:
                            mt5_error = "MT5 credit operation failed"
                    except Exception as e:
                        logger.error(f"❌ MT5 error during credit-out: {str(e)}")
                        mt5_error = str(e)
                
                # Create transaction record
                txn = PAMMTransaction.objects.create(
                    pamm=pamm,
                    participant=None,  # No specific participant
                    transaction_type='CREDIT_OUT',
                    amount=amount,
                    units_added=Decimal('0.00000000'),
                    units_removed=Decimal('0.00000000'),
                    unit_price_at_transaction=new_unit_price,
                    status='COMPLETED',
                    approved_by=request.user,
                    approved_at=timezone.now(),
                    completed_at=timezone.now(),
                    notes=comment
                )
                
                # Create activity log
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"PAMM Credit-Out: ${amount} from {pamm.name}. Unit price: ${old_unit_price:.8f} → ${new_unit_price:.8f}",
                    ip_address=get_client_ip(request),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=pamm.id,
                    related_object_type="PAMMAccount"
                )
                
                # Create equity snapshot
                PAMMService._create_equity_snapshot(pamm)
                
                logger.info(f"✅ PAMM credit-out completed: ${amount} from {pamm.name}")
            
            return Response({
                "success": True,
                "message": "Credit-out completed successfully",
                "transaction_id": txn.id,
                "pamm_id": pamm.id,
                "pamm_name": pamm.name,
                "amount": str(amount),
                "old_equity": str(old_equity),
                "new_equity": str(pamm.total_equity),
                "old_unit_price": str(old_unit_price),
                "new_unit_price": str(new_unit_price),
                "mt5_integration": mt5_success,
                "mt5_error": mt5_error if not mt5_success else None,
                "created_at": txn.created_at.isoformat()
            }, status=status.HTTP_201_CREATED)
            
        except PAMMAccount.DoesNotExist:
            return Response({
                "error": "PAMM account not found"
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error in PAMM credit-out: {str(e)}", exc_info=True)
            return Response({
                "error": f"Internal server error: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
