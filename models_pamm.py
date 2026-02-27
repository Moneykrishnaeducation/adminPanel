"""
PAMM (Percentage Allocation Management Module) Models
Production-grade unit-based PAMM accounting system
"""

from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)


class PAMMAccount(models.Model):
    """
    Master PAMM Pool Account
    Tracks total equity and units for the entire PAMM pool
    """
    STATUS_CHOICES = (
        ('ACTIVE', 'Active'),
        ('DISABLED', 'Disabled'),
        ('CLOSED', 'Closed'),
    )

    name = models.CharField(max_length=100, help_text="PAMM account name")
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='managed_pamm_accounts'
    )
    
    # Profit share configuration
    profit_share = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Manager's profit share percentage (e.g., 20.00 for 20%)"
    )
    
    # Core PAMM accounting fields
    total_equity = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Current total equity (market value of entire pool)"
    )
    total_units = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        default=Decimal('0.00000000'),
        help_text="Total outstanding units"
    )
    
    # High-water mark for manager fee calculation
    high_water_mark = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Highest equity level reached (for performance fee)"
    )
    
    # MT5 Integration
    mt5_account_id = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        help_text="Associated MT5 trading account ID"
    )
    leverage = models.IntegerField(default=100, help_text="Trading leverage")
    
    # Status and configuration
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ACTIVE')
    is_accepting_investors = models.BooleanField(
        default=True,
        help_text="Whether new investors can join this PAMM"
    )
    
    # Passwords for PAMM access
    master_password = models.CharField(
        max_length=128,
        help_text="Master password for trading access"
    )
    invest_password = models.CharField(
        max_length=128,
        help_text="Investor password (view-only access)"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_equity_update = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'pamm_account'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['manager', 'status']),
            models.Index(fields=['status', 'is_accepting_investors']),
        ]

    def __str__(self):
        return f"PAMM: {self.name} (Manager: {self.manager.email})"

    def unit_price(self):
        """
        Calculate current unit price
        Unit price = total_equity / total_units
        Initial unit price is 1.0 if no units exist
        """
        if self.total_units == 0:
            return Decimal("1.0")
        return self.total_equity / self.total_units

    def clean(self):
        """Validate PAMM account data"""
        if self.profit_share < 0 or self.profit_share > 100:
            raise ValidationError("Profit share must be between 0 and 100")
        
        if self.total_equity < 0:
            raise ValidationError("Total equity cannot be negative")
        
        if self.total_units < 0:
            raise ValidationError("Total units cannot be negative")


class PAMMParticipant(models.Model):
    """
    PAMM Participant (Manager or Investor)
    Tracks individual participation in a PAMM pool via units
    """
    ROLE_CHOICES = (
        ('MANAGER', 'Manager'),
        ('INVESTOR', 'Investor'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pamm_participations'
    )
    pamm = models.ForeignKey(
        PAMMAccount,
        on_delete=models.CASCADE,
        related_name='participants'
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    
    # Unit-based balance
    units = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        default=Decimal('0.00000000'),
        help_text="Number of units owned by this participant"
    )
    
    # Tracking fields
    total_deposited = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total amount deposited (for P/L calculation)"
    )
    total_withdrawn = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total amount withdrawn"
    )
    
    # Metadata
    joined_at = models.DateTimeField(auto_now_add=True)
    last_transaction_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'pamm_participant'
        unique_together = ('user', 'pamm', 'role')
        ordering = ['-joined_at']
        indexes = [
            models.Index(fields=['pamm', 'role']),
            models.Index(fields=['user', 'role']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.role} in {self.pamm.name}"

    def current_balance(self):
        """Calculate current value of this participant's units"""
        return self.units * self.pamm.unit_price()

    def profit_loss(self):
        """Calculate total P/L for this participant"""
        current_value = self.current_balance()
        net_invested = self.total_deposited - self.total_withdrawn
        return current_value - net_invested

    def share_percentage(self):
        """Calculate participant's percentage of total pool"""
        if self.pamm.total_units == 0:
            return Decimal('0.00')
        return (self.units / self.pamm.total_units) * Decimal('100.00')


class PAMMTransaction(models.Model):
    """
    Transaction ledger for PAMM operations
    Immutable record of all deposits, withdrawals, and fee calculations
    """
    TRANSACTION_TYPE_CHOICES = (
        ('MANAGER_DEPOSIT', 'Manager Deposit'),
        ('MANAGER_WITHDRAW', 'Manager Withdrawal'),
        ('INVESTOR_DEPOSIT', 'Investor Deposit'),
        ('INVESTOR_WITHDRAW', 'Investor Withdrawal'),
        ('MANAGER_FEE', 'Manager Performance Fee'),
        ('EQUITY_UPDATE', 'Equity Update from MT5'),
    )
    
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('COMPLETED', 'Completed'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
    )
    
    PAYMENT_METHOD_CHOICES = (
        ('usdt', 'USDT'),
        ('manual', 'Manual/Bank Transfer'),
        ('internal', 'Internal Transfer'),
    )

    pamm = models.ForeignKey(
        PAMMAccount,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    participant = models.ForeignKey(
        PAMMParticipant,
        on_delete=models.CASCADE,
        related_name='transactions',
        null=True,
        blank=True
    )
    
    # Transaction details
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        help_text="Transaction amount in USD"
    )
    
    # Unit accounting
    units_added = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        default=Decimal('0.00000000'),
        help_text="Units added (for deposits)"
    )
    units_removed = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        default=Decimal('0.00000000'),
        help_text="Units removed (for withdrawals)"
    )
    unit_price_at_transaction = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        help_text="Unit price at time of transaction"
    )
    
    # Payment details
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        null=True,
        blank=True
    )
    payment_proof = models.FileField(
        upload_to='pamm/payment_proofs/',
        null=True,
        blank=True,
        help_text="Proof of payment (for deposits/withdrawals)"
    )
    
    # Status and approval
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_pamm_transactions'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'pamm_transaction'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['pamm', 'status']),
            models.Index(fields=['participant', 'transaction_type']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.transaction_type} - ${self.amount} ({self.status})"

    def clean(self):
        """Validate transaction data"""
        if self.amount <= 0:
            raise ValidationError("Transaction amount must be positive")


class PAMMEquitySnapshot(models.Model):
    """
    Historical snapshots of PAMM equity for charting and analysis
    """
    pamm = models.ForeignKey(
        PAMMAccount,
        on_delete=models.CASCADE,
        related_name='equity_snapshots'
    )
    
    equity = models.DecimalField(max_digits=20, decimal_places=2)
    total_units = models.DecimalField(max_digits=20, decimal_places=8)
    unit_price = models.DecimalField(max_digits=20, decimal_places=8)
    
    # Breakdown
    manager_units = models.DecimalField(max_digits=20, decimal_places=8, default=Decimal('0.00000000'))
    investor_units = models.DecimalField(max_digits=20, decimal_places=8, default=Decimal('0.00000000'))
    investor_count = models.IntegerField(default=0)
    
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'pamm_equity_snapshot'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['pamm', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.pamm.name} - ${self.equity} @ {self.timestamp}"
