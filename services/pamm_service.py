"""
PAMM Service Layer
Core business logic for PAMM operations
Production-grade unit-based PAMM accounting
"""

from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from adminPanel.models_pamm import (
    PAMMAccount, PAMMParticipant, PAMMTransaction, PAMMEquitySnapshot
)
from django.core.exceptions import ValidationError
from adminPanel.mt5.services import MT5ManagerActions
import logging

logger = logging.getLogger(__name__)


class PAMMService:
    """Service class containing all PAMM business logic"""
    
    @staticmethod
    @transaction.atomic
    def create_pamm_manager(user, name, profit_share, leverage, master_password, invest_password):
        """
        Create a new PAMM account with manager
        
        Args:
            user: Manager user object
            name: PAMM account name
            profit_share: Manager's profit share percentage (0-100)
            leverage: Trading leverage
            master_password: Master password for trading
            invest_password: Investor password for view access
            
        Returns:
            PAMMAccount object
        """
        # Validate inputs
        profit_share = Decimal(str(profit_share))
        if profit_share < 0 or profit_share > 100:
            raise ValidationError("Profit share must be between 0 and 100")
        
        # Create PAMM account (without MT5 ID initially)
        pamm = PAMMAccount.objects.create(
            name=name,
            manager=user,
            profit_share=profit_share,
            leverage=leverage,
            master_password=master_password,
            invest_password=invest_password,
            status='ACTIVE',
            is_accepting_investors=True
        )
        
        # Create MT5 account for the PAMM (matching trading account creation pattern)
        try:
            # Get default trading group (same logic as trading account creation)
            from adminPanel.models import TradeGroup
            from adminPanel.mt5.models import ServerSetting
            
            trade_group = TradeGroup.objects.filter(is_default=True, is_active=True).first()
            if trade_group and trade_group.name:
                group_name = trade_group.name
            else:
                # Fallback to a standard group name
                group_name = "standard"
            
            # Log which MT5 server will be used
            server_setting = ServerSetting.objects.filter(server_type=True).order_by('-created_at').first()
            if server_setting:
                logger.info(f"🔵 PAMM MT5 Account Creation - Server: {server_setting.get_decrypted_server_ip()}, Manager Login: {server_setting.real_account_login}")
            
            logger.info(f"🔵 Creating MT5 REAL account for PAMM '{name}' - Group: '{group_name}', Leverage: {leverage}, User: {user.email}")
            
            # Create new instance like trading account creation does
            mt5_service = MT5ManagerActions()
            
            # Check if MT5 manager is connected
            if not mt5_service.manager:
                error_msg = mt5_service.connection_error or "MT5 manager not available"
                logger.error(f"❌ MT5 Manager not connected for PAMM creation: {error_msg}")
                logger.error(f"⚠️ PAMM '{name}' created WITHOUT MT5 account - admin must create manually")
                # Don't fail PAMM creation, continue without MT5 account
            else:
                logger.info(f"✅ MT5 Manager connected, calling create_account...")
                # Call create_account with same parameters as trading account
                account_result = mt5_service.create_account(
                    name=f"{user.first_name} {user.last_name}".strip() or user.email,
                    email=user.email,
                    phone=getattr(user, 'phone_number', ''),
                    group=group_name,
                    leverage=int(leverage),
                    password=master_password,
                    investor_password=invest_password,
                    account_type='real'  # ⚠️ CREATING ON REAL SERVER
                )
                
                if account_result and account_result.get('login'):
                    pamm.mt5_account_id = str(account_result.get('login'))
                    pamm.save()
                    logger.info(f"✅ SUCCESS! MT5 REAL account {pamm.mt5_account_id} created for PAMM: {name}")
                    logger.info(f"   📋 Account Details - Login: {pamm.mt5_account_id}, Group: {account_result.get('group')}")
                    logger.info(f"   🔑 Master Password: {account_result.get('master_password')}")
                    logger.info(f"   👁️ Investor Password: {account_result.get('investor_password')}")
                    logger.info(f"   ⚠️ CHECK REAL MT5 SERVER (not demo) for account {pamm.mt5_account_id}")
                else:
                    logger.warning(f"⚠️ MT5 create_account returned no login for PAMM: {name}. Result: {account_result}")
        except Exception as e:
            logger.error(f"❌ Exception creating MT5 account for PAMM '{name}': {str(e)}", exc_info=True)
            # Don't fail PAMM creation if MT5 account creation fails
            # Admin can manually create MT5 account later
        
        # Create manager participant record
        PAMMParticipant.objects.create(
            user=user,
            pamm=pamm,
            role='MANAGER',
            units=Decimal('0.00000000')
        )
        
        logger.info(f"Created PAMM account: {name} for manager {user.email}")
        return pamm
    
    @staticmethod
    @transaction.atomic
    def manager_deposit(pamm, manager_participant, amount, payment_method='internal', payment_proof=None):
        """
        Process manager deposit
        
        Args:
            pamm: PAMMAccount object
            manager_participant: PAMMParticipant object (role=MANAGER)
            amount: Deposit amount (USD)
            payment_method: Payment method (usdt, manual, internal)
            payment_proof: File object for payment proof
            
        Returns:
            dict with transaction details
        """
        amount = Decimal(str(amount))
        
        if amount <= 0:
            raise ValidationError("Deposit amount must be positive")
        
        if manager_participant.role != 'MANAGER':
            raise ValidationError("Only manager can use manager deposit")
        
        # Get unit price at deposit time
        unit_price = pamm.unit_price()
        units_added = amount / unit_price
        
        # Create transaction record
        txn = PAMMTransaction.objects.create(
            pamm=pamm,
            participant=manager_participant,
            transaction_type='MANAGER_DEPOSIT',
            amount=amount,
            units_added=units_added,
            units_removed=Decimal('0.00000000'),
            unit_price_at_transaction=unit_price,
            payment_method=payment_method,
            payment_proof=payment_proof,
            status='PENDING'
        )
        
        logger.info(f"Created manager deposit request: ${amount} for PAMM {pamm.name}")
        
        return {
            "transaction_id": txn.id,
            "type": "MANAGER_DEPOSIT",
            "amount": str(amount),
            "unit_price": str(unit_price),
            "units_to_add": str(units_added),
            "status": "PENDING",
            "message": "Deposit request submitted. Awaiting admin approval."
        }
    
    @staticmethod
    @transaction.atomic
    def approve_manager_deposit(transaction_id, approved_by):
        """
        Approve and execute manager deposit
        
        Args:
            transaction_id: PAMMTransaction ID
            approved_by: Admin user approving the transaction
        """
        try:
            txn = PAMMTransaction.objects.select_for_update().get(
                id=transaction_id,
                transaction_type='MANAGER_DEPOSIT',
                status='PENDING'
            )
        except PAMMTransaction.DoesNotExist:
            raise ValidationError("Transaction not found or already processed")
        
        pamm = txn.pamm
        participant = txn.participant
        
        # Credit MT5 account first
        if pamm.mt5_account_id:
            try:
                mt5_manager = MT5ManagerActions()
                deposit_result = mt5_manager.deposit_funds(
                    login_id=int(pamm.mt5_account_id),
                    amount=float(txn.amount),
                    comment=f"PAMM Manager Deposit | {participant.user.email} | {pamm.name} | ${txn.amount}"
                )
                if not deposit_result:
                    raise ValidationError("Failed to credit MT5 account")
                logger.info(f"✅ Credited ${txn.amount} to MT5 account {pamm.mt5_account_id}")
            except Exception as e:
                logger.error(f"❌ MT5 deposit failed for PAMM {pamm.name}: {e}")
                raise ValidationError(f"MT5 deposit failed: {str(e)}")
        else:
            logger.warning(f"⚠️ PAMM {pamm.name} has no MT5 account - skipping MT5 deposit")
        
        # Recalculate unit price at approval time (equity may have changed)
        unit_price = pamm.unit_price()
        units_added = txn.amount / unit_price
        
        # Update participant
        participant.units += units_added
        participant.total_deposited += txn.amount
        participant.last_transaction_at = timezone.now()
        participant.save()
        
        # Update PAMM pool
        pamm.total_units += units_added
        pamm.total_equity += txn.amount
        pamm.save()
        
        # Update transaction
        txn.units_added = units_added
        txn.unit_price_at_transaction = unit_price
        txn.status = 'COMPLETED'
        txn.approved_by = approved_by
        txn.approved_at = timezone.now()
        txn.completed_at = timezone.now()
        txn.save()
        
        # Create equity snapshot
        PAMMService._create_equity_snapshot(pamm)
        
        logger.info(f"✅ Approved manager deposit: ${txn.amount} for PAMM {pamm.name}")
        
        return {
            "transaction_id": txn.id,
            "unit_price": str(unit_price),
            "units_added": str(units_added),
            "total_units": str(pamm.total_units),
            "total_equity": str(pamm.total_equity)
        }
    
    @staticmethod
    @transaction.atomic
    def manager_withdraw(pamm, manager_participant, amount, payment_method='manual'):
        """
        Process manager withdrawal
        
        Args:
            pamm: PAMMAccount object
            manager_participant: PAMMParticipant object (role=MANAGER)
            amount: Withdrawal amount (USD)
            payment_method: Payment method (usdt, manual)
            
        Returns:
            dict with transaction details
        """
        amount = Decimal(str(amount))
        
        if amount <= 0:
            raise ValidationError("Withdrawal amount must be positive")
        
        if manager_participant.role != 'MANAGER':
            raise ValidationError("Only manager can use manager withdrawal")
        
        # Get unit price
        unit_price = pamm.unit_price()
        units_required = amount / unit_price
        
        # Check if manager has sufficient balance
        manager_balance = manager_participant.current_balance()
        if amount > manager_balance:
            raise ValidationError(f"Insufficient balance. Available: ${manager_balance}")
        
        if units_required > manager_participant.units:
            raise ValidationError("Insufficient units")
        
        # Create withdrawal request
        txn = PAMMTransaction.objects.create(
            pamm=pamm,
            participant=manager_participant,
            transaction_type='MANAGER_WITHDRAW',
            amount=amount,
            units_added=Decimal('0.00000000'),
            units_removed=units_required,
            unit_price_at_transaction=unit_price,
            payment_method=payment_method,
            status='PENDING'
        )
        
        logger.info(f"Created manager withdrawal request: ${amount} for PAMM {pamm.name}")
        
        return {
            "transaction_id": txn.id,
            "type": "MANAGER_WITHDRAW",
            "amount": str(amount),
            "unit_price": str(unit_price),
            "units_to_remove": str(units_required),
            "status": "PENDING",
            "message": "Withdrawal request submitted. Awaiting admin approval."
        }
    
    @staticmethod
    @transaction.atomic
    def approve_manager_withdraw(transaction_id, approved_by):
        """
        Approve and execute manager withdrawal
        
        Args:
            transaction_id: PAMMTransaction ID
            approved_by: Admin user approving the transaction
        """
        try:
            txn = PAMMTransaction.objects.select_for_update().get(
                id=transaction_id,
                transaction_type='MANAGER_WITHDRAW',
                status='PENDING'
            )
        except PAMMTransaction.DoesNotExist:
            raise ValidationError("Transaction not found or already processed")
        
        pamm = txn.pamm
        participant = txn.participant
        
        # Recalculate at approval time
        unit_price = pamm.unit_price()
        units_removed = txn.amount / unit_price
        
        # Check again if sufficient units
        if units_removed > participant.units:
            txn.status = 'REJECTED'
            txn.rejection_reason = 'Insufficient units at approval time'
            txn.approved_by = approved_by
            txn.approved_at = timezone.now()
            txn.save()
            raise ValidationError("Insufficient units at approval time")
        
        # Withdraw from MT5 account first
        if pamm.mt5_account_id:
            try:
                mt5_manager = MT5ManagerActions()
                withdraw_result = mt5_manager.withdraw_funds(
                    login_id=int(pamm.mt5_account_id),
                    amount=float(txn.amount),
                    comment=f"PAMM Manager Withdrawal | {participant.user.email} | {pamm.name} | ${txn.amount}"
                )
                if not withdraw_result:
                    raise ValidationError("Failed to withdraw from MT5 account")
                logger.info(f"✅ Withdrew ${txn.amount} from MT5 account {pamm.mt5_account_id}")
            except Exception as e:
                logger.error(f"❌ MT5 withdrawal failed for PAMM {pamm.name}: {e}")
                raise ValidationError(f"MT5 withdrawal failed: {str(e)}")
        else:
            logger.warning(f"⚠️ PAMM {pamm.name} has no MT5 account - skipping MT5 withdrawal")
        
        # Update participant
        participant.units -= units_removed
        participant.total_withdrawn += txn.amount
        participant.last_transaction_at = timezone.now()
        participant.save()
        
        # Update PAMM pool
        pamm.total_units -= units_removed
        pamm.total_equity -= txn.amount
        pamm.save()
        
        # Update transaction
        txn.units_removed = units_removed
        txn.unit_price_at_transaction = unit_price
        txn.status = 'COMPLETED'
        txn.approved_by = approved_by
        txn.approved_at = timezone.now()
        txn.completed_at = timezone.now()
        txn.save()
        
        # Create equity snapshot
        PAMMService._create_equity_snapshot(pamm)
        
        logger.info(f"✅ Approved manager withdrawal: ${txn.amount} from PAMM {pamm.name}")
        
        return {
            "transaction_id": txn.id,
            "unit_price": str(unit_price),
            "units_removed": str(units_removed),
            "remaining_units": str(participant.units)
        }
    
    @staticmethod
    @transaction.atomic
    def create_investor(user, pamm):
        """
        Create investor participant (join PAMM)
        
        Args:
            user: Investor user object
            pamm: PAMMAccount object
            
        Returns:
            PAMMParticipant object
        """
        if pamm.status != 'ACTIVE':
            raise ValidationError("PAMM account is not active")
        
        if not pamm.is_accepting_investors:
            raise ValidationError("PAMM is not accepting new investors")
        
        # Get or create investor participant
        investor, created = PAMMParticipant.objects.get_or_create(
            user=user,
            pamm=pamm,
            role='INVESTOR',
            defaults={'units': Decimal('0.00000000')}
        )
        
        if created:
            logger.info(f"Investor {user.email} joined PAMM {pamm.name}")
        
        return investor
    
    @staticmethod
    @transaction.atomic
    def investor_deposit(pamm, investor_participant, amount, payment_method='manual', payment_proof=None):
        """
        Process investor deposit
        
        Args:
            pamm: PAMMAccount object
            investor_participant: PAMMParticipant object (role=INVESTOR)
            amount: Deposit amount (USD)
            payment_method: Payment method (usdt, manual)
            payment_proof: File object for payment proof
            
        Returns:
            dict with transaction details
        """
        amount = Decimal(str(amount))
        
        if amount < Decimal('10.00'):
            raise ValidationError("Minimum deposit is $10")
        
        if investor_participant.role != 'INVESTOR':
            raise ValidationError("Only investors can use investor deposit")
        
        # Get unit price at deposit time
        unit_price = pamm.unit_price()
        units_added = amount / unit_price
        
        # Create transaction record
        txn = PAMMTransaction.objects.create(
            pamm=pamm,
            participant=investor_participant,
            transaction_type='INVESTOR_DEPOSIT',
            amount=amount,
            units_added=units_added,
            units_removed=Decimal('0.00000000'),
            unit_price_at_transaction=unit_price,
            payment_method=payment_method,
            payment_proof=payment_proof,
            status='PENDING'
        )
        
        logger.info(f"Created investor deposit request: ${amount} for PAMM {pamm.name}")
        
        return {
            "transaction_id": txn.id,
            "type": "INVESTOR_DEPOSIT",
            "amount": str(amount),
            "unit_price": str(unit_price),
            "units_to_add": str(units_added),
            "status": "PENDING",
            "message": "Deposit request submitted. Awaiting admin approval."
        }
    
    @staticmethod
    @transaction.atomic
    def approve_investor_deposit(transaction_id, approved_by):
        """
        Approve and execute investor deposit
        
        Args:
            transaction_id: PAMMTransaction ID
            approved_by: Admin user approving the transaction
        """
        try:
            txn = PAMMTransaction.objects.select_for_update().get(
                id=transaction_id,
                transaction_type='INVESTOR_DEPOSIT',
                status='PENDING'
            )
        except PAMMTransaction.DoesNotExist:
            raise ValidationError("Transaction not found or already processed")
        
        pamm = txn.pamm
        participant = txn.participant
        
        # Credit MT5 account first
        if pamm.mt5_account_id:
            try:
                mt5_manager = MT5ManagerActions()
                deposit_result = mt5_manager.deposit_funds(
                    login_id=int(pamm.mt5_account_id),
                    amount=float(txn.amount),
                    comment=f"PAMM Investor Deposit | {participant.user.email} | {pamm.name} | ${txn.amount}"
                )
                if not deposit_result:
                    raise ValidationError("Failed to credit MT5 account")
                logger.info(f"✅ Credited ${txn.amount} to MT5 account {pamm.mt5_account_id}")
            except Exception as e:
                logger.error(f"❌ MT5 deposit failed for PAMM {pamm.name}: {e}")
                raise ValidationError(f"MT5 deposit failed: {str(e)}")
        else:
            logger.warning(f"⚠️ PAMM {pamm.name} has no MT5 account - skipping MT5 deposit")
        
        # Recalculate unit price at approval time
        unit_price = pamm.unit_price()
        units_added = txn.amount / unit_price
        
        # Update participant
        participant.units += units_added
        participant.total_deposited += txn.amount
        participant.last_transaction_at = timezone.now()
        participant.save()
        
        # Update PAMM pool
        pamm.total_units += units_added
        pamm.total_equity += txn.amount
        pamm.save()
        
        # Update transaction
        txn.units_added = units_added
        txn.unit_price_at_transaction = unit_price
        txn.status = 'COMPLETED'
        txn.approved_by = approved_by
        txn.approved_at = timezone.now()
        txn.completed_at = timezone.now()
        txn.save()
        
        # Create equity snapshot
        PAMMService._create_equity_snapshot(pamm)
        
        logger.info(f"✅ Approved investor deposit: ${txn.amount} for PAMM {pamm.name}")
        
        return {
            "transaction_id": txn.id,
            "unit_price": str(unit_price),
            "units_added": str(units_added),
            "investor_units": str(participant.units)
        }
    
    @staticmethod
    @transaction.atomic
    def investor_withdraw(pamm, investor_participant, amount, payment_method='manual'):
        """
        Process investor withdrawal
        
        Args:
            pamm: PAMMAccount object
            investor_participant: PAMMParticipant object (role=INVESTOR)
            amount: Withdrawal amount (USD)
            payment_method: Payment method (usdt, manual)
            
        Returns:
            dict with transaction details
        """
        amount = Decimal(str(amount))
        
        if amount <= 0:
            raise ValidationError("Withdrawal amount must be positive")
        
        if investor_participant.role != 'INVESTOR':
            raise ValidationError("Only investors can use investor withdrawal")
        
        # Get unit price
        unit_price = pamm.unit_price()
        units_required = amount / unit_price
        
        # Check if investor has sufficient balance
        investor_balance = investor_participant.current_balance()
        if amount > investor_balance:
            raise ValidationError(f"Insufficient balance. Available: ${investor_balance}")
        
        if units_required > investor_participant.units:
            raise ValidationError("Insufficient units")
        
        # Create withdrawal request
        txn = PAMMTransaction.objects.create(
            pamm=pamm,
            participant=investor_participant,
            transaction_type='INVESTOR_WITHDRAW',
            amount=amount,
            units_added=Decimal('0.00000000'),
            units_removed=units_required,
            unit_price_at_transaction=unit_price,
            payment_method=payment_method,
            status='PENDING'
        )
        
        logger.info(f"Created investor withdrawal request: ${amount} for PAMM {pamm.name}")
        
        return {
            "transaction_id": txn.id,
            "type": "INVESTOR_WITHDRAW",
            "amount": str(amount),
            "unit_price": str(unit_price),
            "units_to_remove": str(units_required),
            "status": "PENDING",
            "message": "Withdrawal request submitted. Awaiting admin approval."
        }
    
    @staticmethod
    @transaction.atomic
    def approve_investor_withdraw(transaction_id, approved_by):
        """
        Approve and execute investor withdrawal
        
        Args:
            transaction_id: PAMMTransaction ID
            approved_by: Admin user approving the transaction
        """
        try:
            txn = PAMMTransaction.objects.select_for_update().get(
                id=transaction_id,
                transaction_type='INVESTOR_WITHDRAW',
                status='PENDING'
            )
        except PAMMTransaction.DoesNotExist:
            raise ValidationError("Transaction not found or already processed")
        
        pamm = txn.pamm
        participant = txn.participant
        
        # Recalculate at approval time
        unit_price = pamm.unit_price()
        units_removed = txn.amount / unit_price
        
        # Check again if sufficient units
        if units_removed > participant.units:
            txn.status = 'REJECTED'
            txn.rejection_reason = 'Insufficient units at approval time'
            txn.approved_by = approved_by
            txn.approved_at = timezone.now()
            txn.save()
            raise ValidationError("Insufficient units at approval time")
        
        # Withdraw from MT5 account first
        if pamm.mt5_account_id:
            try:
                mt5_manager = MT5ManagerActions()
                withdraw_result = mt5_manager.withdraw_funds(
                    login_id=int(pamm.mt5_account_id),
                    amount=float(txn.amount),
                    comment=f"PAMM Investor Withdrawal | {participant.user.email} | {pamm.name} | ${txn.amount}"
                )
                if not withdraw_result:
                    raise ValidationError("Failed to withdraw from MT5 account")
                logger.info(f"✅ Withdrew ${txn.amount} from MT5 account {pamm.mt5_account_id}")
            except Exception as e:
                logger.error(f"❌ MT5 withdrawal failed for PAMM {pamm.name}: {e}")
                raise ValidationError(f"MT5 withdrawal failed: {str(e)}")
        else:
            logger.warning(f"⚠️ PAMM {pamm.name} has no MT5 account - skipping MT5 withdrawal")
        
        # Update participant
        participant.units -= units_removed
        participant.total_withdrawn += txn.amount
        participant.last_transaction_at = timezone.now()
        participant.save()
        
        # Update PAMM pool
        pamm.total_units -= units_removed
        pamm.total_equity -= txn.amount
        pamm.save()
        
        # Update transaction
        txn.units_removed = units_removed
        txn.unit_price_at_transaction = unit_price
        txn.status = 'COMPLETED'
        txn.approved_by = approved_by
        txn.approved_at = timezone.now()
        txn.completed_at = timezone.now()
        txn.save()
        
        # Create equity snapshot
        PAMMService._create_equity_snapshot(pamm)
        
        logger.info(f"✅ Approved investor withdrawal: ${txn.amount} from PAMM {pamm.name}")
        
        return {
            "transaction_id": txn.id,
            "unit_price": str(unit_price),
            "units_removed": str(units_removed),
            "remaining_units": str(participant.units)
        }
    
    @staticmethod
    @transaction.atomic
    def reject_transaction(transaction_id, rejected_by, reason):
        """
        Reject a pending transaction
        
        Args:
            transaction_id: PAMMTransaction ID
            rejected_by: Admin user rejecting the transaction
            reason: Rejection reason
        """
        try:
            txn = PAMMTransaction.objects.get(id=transaction_id, status='PENDING')
        except PAMMTransaction.DoesNotExist:
            raise ValidationError("Transaction not found or already processed")
        
        txn.status = 'REJECTED'
        txn.rejection_reason = reason
        txn.approved_by = rejected_by
        txn.approved_at = timezone.now()
        txn.save()
        
        logger.info(f"Rejected transaction {transaction_id}: {reason}")
        
        return {"message": "Transaction rejected", "transaction_id": txn.id}
    
    @staticmethod
    @transaction.atomic
    def update_pamm_equity(pamm_id, new_equity):
        """
        Update PAMM equity from MT5 sync
        This changes unit price but NOT units
        
        Args:
            pamm_id: PAMMAccount ID
            new_equity: New equity value from MT5
        """
        new_equity = Decimal(str(new_equity))
        
        try:
            pamm = PAMMAccount.objects.select_for_update().get(id=pamm_id)
        except PAMMAccount.DoesNotExist:
            raise ValidationError("PAMM account not found")
        
        old_equity = pamm.total_equity
        pamm.total_equity = new_equity
        pamm.last_equity_update = timezone.now()
        pamm.save()
        
        # Create snapshot
        PAMMService._create_equity_snapshot(pamm)
        
        logger.info(f"Updated PAMM {pamm.name} equity: ${old_equity} -> ${new_equity}")
        
        return {
            "pamm_id": pamm.id,
            "old_equity": str(old_equity),
            "new_equity": str(new_equity),
            "unit_price": str(pamm.unit_price())
        }
    
    @staticmethod
    @transaction.atomic
    def calculate_manager_fee(pamm_id):
        """
        Calculate and apply manager performance fee (high-water mark)
        
        Args:
            pamm_id: PAMMAccount ID
            
        Returns:
            dict with fee details
        """
        try:
            pamm = PAMMAccount.objects.select_for_update().get(id=pamm_id)
        except PAMMAccount.DoesNotExist:
            raise ValidationError("PAMM account not found")
        
        # Check if equity exceeds high-water mark
        if pamm.total_equity <= pamm.high_water_mark:
            return {
                "fee_applied": False,
                "message": "No fee - equity below high-water mark",
                "current_equity": str(pamm.total_equity),
                "high_water_mark": str(pamm.high_water_mark)
            }
        
        # Calculate fee
        profit_above_hwm = pamm.total_equity - pamm.high_water_mark
        manager_fee = profit_above_hwm * (pamm.profit_share / Decimal('100.00'))
        
        # Update high-water mark
        pamm.high_water_mark = pamm.total_equity
        
        # Remove fee from total equity (redistributes to manager via unit price change)
        pamm.total_equity -= manager_fee
        pamm.save()
        
        # Record fee transaction
        try:
            manager_participant = pamm.participants.get(user=pamm.manager, role='MANAGER')
        except PAMMParticipant.DoesNotExist:
            manager_participant = None
        
        PAMMTransaction.objects.create(
            pamm=pamm,
            participant=manager_participant,
            transaction_type='MANAGER_FEE',
            amount=manager_fee,
            units_added=Decimal('0.00000000'),
            units_removed=Decimal('0.00000000'),
            unit_price_at_transaction=pamm.unit_price(),
            status='COMPLETED',
            completed_at=timezone.now(),
            notes=f"Performance fee: {pamm.profit_share}% on profit above HWM"
        )
        
        logger.info(f"Applied manager fee: ${manager_fee} for PAMM {pamm.name}")
        
        return {
            "fee_applied": True,
            "manager_fee": str(manager_fee),
            "profit_above_hwm": str(profit_above_hwm),
            "profit_share_percentage": str(pamm.profit_share),
            "new_high_water_mark": str(pamm.high_water_mark)
        }
    
    @staticmethod
    def _create_equity_snapshot(pamm):
        """Create an equity snapshot for historical tracking"""
        manager_units = pamm.participants.filter(role='MANAGER').aggregate(
            total=models.Sum('units')
        )['total'] or Decimal('0.00000000')
        
        investor_units = pamm.participants.filter(role='INVESTOR').aggregate(
            total=models.Sum('units')
        )['total'] or Decimal('0.00000000')
        
        investor_count = pamm.participants.filter(role='INVESTOR', units__gt=0).count()
        
        PAMMEquitySnapshot.objects.create(
            pamm=pamm,
            equity=pamm.total_equity,
            total_units=pamm.total_units,
            unit_price=pamm.unit_price(),
            manager_units=manager_units,
            investor_units=investor_units,
            investor_count=investor_count
        )


# Required import for snapshot creation
from django.db.models import Sum
from django.db import models
