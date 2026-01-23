import uuid
from django.db.models import Sum
import random
import string
from decimal import Decimal, InvalidOperation
from django.db import models, IntegrityError
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager, AbstractUser
from django.db.models.signals import pre_save
from django.dispatch import receiver
import logging
import os
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from adminPanel.mt5.models import ServerSetting
from adminPanel.roles import UserRole

logger = logging.getLogger(__name__)

# User model has been merged into CustomUser


class CommissioningProfile(models.Model):
    name = models.CharField(max_length=100)  
    # New dynamic levels field - comma-separated USD per lot amounts
    level_amounts_usd_per_lot = models.CharField(max_length=255, blank=True, null=True, help_text="Comma-separated USD amounts per lot for each level (e.g., '50,20,15,10')")
    
    # Dynamic levels configuration - stores array of level objects
    # Format: [{"level": 1, "percentage": 80, "usd_per_lot": 50}, {"level": 2, "percentage": 20, "usd_per_lot": 20}]
    dynamic_levels = models.JSONField(
        default=list,
        blank=True,
        help_text="Dynamic level configuration with percentage and/or USD per lot for each level"
    )
    
    # Group settings for this profile
    approved_groups = models.JSONField(
        default=list,
        blank=True,
        help_text="List of approved MT5 trading groups for this commission profile"
    )
    
    # Keep old fields for backward compatibility
    level_1_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)  
    level_2_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)  
    level_3_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)  
    commission_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  
    
    # New USD per lot fields
    level_1_usd_per_lot = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="USD commission per lot for level 1")
    level_2_usd_per_lot = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="USD commission per lot for level 2")
    level_3_usd_per_lot = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="USD commission per lot for level 3")
    
    # Legacy support flag
    use_percentage_based = models.BooleanField(default=False, help_text="Use percentage-based commission instead of USD per lot")
    
    created_at = models.DateTimeField(auto_now_add=True)

    def get_level_amounts_list(self):
        """Return list of decimal USD amounts per lot from the level_amounts_usd_per_lot string or dynamic_levels."""
        # First priority: use dynamic_levels if available
        if self.dynamic_levels:
            amounts = []
            # Sort by level to ensure correct order
            sorted_levels = sorted(self.dynamic_levels, key=lambda x: x.get('level', 0))
            for level_config in sorted_levels:
                if 'usd_per_lot' in level_config:
                    try:
                        amounts.append(Decimal(str(level_config['usd_per_lot'])))
                    except (ValueError, InvalidOperation):
                        amounts.append(Decimal('0.00'))
            if amounts:
                return amounts
        
        # Fallback to level_amounts_usd_per_lot string
        if self.level_amounts_usd_per_lot and self.level_amounts_usd_per_lot.strip():
            try:
                return [Decimal(a.strip()) for a in self.level_amounts_usd_per_lot.split(',') if a.strip()]
            except (ValueError, InvalidOperation):
                return []
        return []

    def get_level_percentages_list(self):
        """Return list of decimal percentages from dynamic_levels or individual percentage fields."""
        # First priority: use dynamic_levels if available
        if self.dynamic_levels:
            percentages = []
            # Sort by level to ensure correct order
            sorted_levels = sorted(self.dynamic_levels, key=lambda x: x.get('level', 0))
            for level_config in sorted_levels:
                if 'percentage' in level_config:
                    try:
                        percentages.append(Decimal(str(level_config['percentage'])))
                    except (ValueError, InvalidOperation):
                        percentages.append(Decimal('0.00'))
            if percentages:
                return percentages
        
        # Fallback to individual fields for backward compatibility
        percentages = []
        if self.level_1_percentage > 0:
            percentages.append(self.level_1_percentage)
        if self.level_2_percentage > 0:
            percentages.append(self.level_2_percentage)
        if self.level_3_percentage > 0:
            percentages.append(self.level_3_percentage)
        return percentages

    def get_max_levels(self):
        """Return the maximum number of levels supported by this profile."""
        # First priority: check dynamic_levels
        if self.dynamic_levels:
            return len(self.dynamic_levels)
        
        # Fallback to legacy behavior
        if self.use_percentage_based:
            return len(self.get_level_percentages_list())
        else:
            return len(self.get_level_amounts_list())

    def get_amount_for_level(self, level):
        """Get USD per lot amount for a specific level (1-based)."""
        # First priority: check dynamic_levels
        if self.dynamic_levels:
            for level_config in self.dynamic_levels:
                if level_config.get('level') == level and 'usd_per_lot' in level_config:
                    try:
                        return Decimal(str(level_config['usd_per_lot']))
                    except (ValueError, InvalidOperation):
                        return Decimal('0.00')
            return Decimal('0.00')
        
        # Fallback to legacy behavior
        amounts = self.get_level_amounts_list()
        if 1 <= level <= len(amounts):
            return amounts[level - 1]
        return Decimal('0.00')

    def get_amount_for_level_by_group(self, level, group_name=None):
        """Get USD per lot amount for a specific level (1-based) optionally for a group.
        If a group-specific CommissioningProfileGroup exists, prefer its amounts.
        """
        if group_name:
            try:
                cp_group = CommissioningProfileGroup.objects.filter(profile=self, group_name=group_name).first()
                if cp_group:
                    amounts = cp_group.get_amounts_list()
                    if 1 <= level <= len(amounts):
                        return amounts[level - 1]
            except Exception:
                pass
        return self.get_amount_for_level(level)

    def get_percentage_for_level(self, level):
        """Get percentage for a specific level (1-based) - for backward compatibility."""
        # First priority: check dynamic_levels
        if self.dynamic_levels:
            for level_config in self.dynamic_levels:
                if level_config.get('level') == level and 'percentage' in level_config:
                    try:
                        return Decimal(str(level_config['percentage']))
                    except (ValueError, InvalidOperation):
                        return Decimal('0.00')
            return Decimal('0.00')
        
        # Fallback to legacy behavior
        if self.use_percentage_based:
            percentages = self.get_level_percentages_list()
            if 1 <= level <= len(percentages):
                return percentages[level - 1]
        return Decimal('0.00')

    def is_group_approved(self, group_name):
        """Check if a trading group is approved for this commission profile."""
        if not self.approved_groups:
            return True  # If no groups specified, allow all
        return group_name in self.approved_groups

    def clean(self):
        """Validate commission settings."""
        # Validate dynamic_levels if present
        if self.dynamic_levels:
            # Validate that each level has required fields
            for level_config in self.dynamic_levels:
                level_num = level_config.get('level')
                if not level_num or not isinstance(level_num, int) or level_num < 1:
                    raise ValidationError("Each level must have a valid 'level' number (positive integer).")
                
                # Check that at least percentage or usd_per_lot is specified
                has_percentage = 'percentage' in level_config
                has_usd = 'usd_per_lot' in level_config
                
                if not has_percentage and not has_usd:
                    raise ValidationError(f"Level {level_num} must have either 'percentage' or 'usd_per_lot' specified.")
                
                # Validate percentage if present
                if has_percentage:
                    try:
                        percentage = Decimal(str(level_config['percentage']))
                        if percentage < 0 or percentage > 100:
                            raise ValidationError(f"Level {level_num} percentage must be between 0 and 100.")
                    except (ValueError, InvalidOperation):
                        raise ValidationError(f"Level {level_num} has invalid percentage value.")
                
                # Validate usd_per_lot if present
                if has_usd:
                    try:
                        usd_amount = Decimal(str(level_config['usd_per_lot']))
                        if usd_amount < 0:
                            raise ValidationError(f"Level {level_num} USD per lot cannot be negative.")
                        if usd_amount > Decimal('1000'):
                            raise ValidationError(f"Level {level_num} USD per lot ({usd_amount}) exceeds maximum of $1000.")
                    except (ValueError, InvalidOperation):
                        raise ValidationError(f"Level {level_num} has invalid usd_per_lot value.")
            
            # Check total percentage if percentage-based
            if self.use_percentage_based or any('percentage' in lc for lc in self.dynamic_levels):
                total_percentage = Decimal('0')
                for level_config in self.dynamic_levels:
                    if 'percentage' in level_config:
                        try:
                            total_percentage += Decimal(str(level_config['percentage']))
                        except (ValueError, InvalidOperation):
                            pass
                
                if total_percentage > Decimal('100'):
                    raise ValidationError(f"Total commission percentage ({total_percentage}%) cannot exceed 100%.")
        
        elif self.use_percentage_based:
            # Validate percentage-based commission using individual fields (legacy)
            total_percentage = self.level_1_percentage + self.level_2_percentage + self.level_3_percentage
            if total_percentage > Decimal(100):
                raise ValidationError("The total commission percentage across all levels cannot exceed 100%.")
        else:
            # Validate USD per lot commission (legacy)
            if self.level_amounts_usd_per_lot and self.level_amounts_usd_per_lot.strip():
                amounts = self.get_level_amounts_list()
                if not amounts:
                    raise ValidationError("Invalid format for level amounts. Use comma-separated numbers (e.g., '50,20,15,10').")
                
                # Check for reasonable amounts (max $1000 per lot per level)
                for i, amount in enumerate(amounts, 1):
                    if amount < 0:
                        raise ValidationError(f"Level {i} amount cannot be negative.")
                    if amount > Decimal('1000'):
                        raise ValidationError(f"Level {i} amount ({amount}) exceeds maximum of $1000 per lot.")

    def save(self, *args, **kwargs):
        self.clean()
        
        # If dynamic_levels is set, sync with legacy fields for backward compatibility
        if self.dynamic_levels:
            # Update legacy fields based on dynamic_levels
            for level_config in self.dynamic_levels:
                level_num = level_config.get('level')
                
                if self.use_percentage_based and 'percentage' in level_config:
                    percentage = Decimal(str(level_config['percentage']))
                    if level_num == 1:
                        self.level_1_percentage = percentage
                    elif level_num == 2:
                        self.level_2_percentage = percentage
                    elif level_num == 3:
                        self.level_3_percentage = percentage
                
                if not self.use_percentage_based and 'usd_per_lot' in level_config:
                    usd_amount = Decimal(str(level_config['usd_per_lot']))
                    if level_num == 1:
                        self.level_1_usd_per_lot = usd_amount
                    elif level_num == 2:
                        self.level_2_usd_per_lot = usd_amount
                    elif level_num == 3:
                        self.level_3_usd_per_lot = usd_amount
        
        elif not self.use_percentage_based:
            # Legacy USD per lot handling
            # Update USD per lot fields from level_amounts_usd_per_lot
            if self.level_amounts_usd_per_lot and self.level_amounts_usd_per_lot.strip():
                amounts = self.get_level_amounts_list()
                self.level_1_usd_per_lot = amounts[0] if len(amounts) > 0 else Decimal('0.00')
                self.level_2_usd_per_lot = amounts[1] if len(amounts) > 1 else Decimal('0.00')
                self.level_3_usd_per_lot = amounts[2] if len(amounts) > 2 else Decimal('0.00')
            else:
                # Create level_amounts_usd_per_lot from individual fields
                amounts = []
                if self.level_1_usd_per_lot > 0:
                    amounts.append(str(self.level_1_usd_per_lot))
                if self.level_2_usd_per_lot > 0:
                    amounts.append(str(self.level_2_usd_per_lot))
                if self.level_3_usd_per_lot > 0:
                    amounts.append(str(self.level_3_usd_per_lot))
                if amounts:
                    self.level_amounts_usd_per_lot = ','.join(amounts)
        else:
            # Legacy percentage-based handling
            # For percentage-based, ensure commission_percentage is set
            if self.commission_percentage is None:
                self.commission_percentage = self.level_1_percentage
                
        super().save(*args, **kwargs)

    def __str__(self):
        # Check if using dynamic_levels
        if self.dynamic_levels:
            sorted_levels = sorted(self.dynamic_levels, key=lambda x: x.get('level', 0))
            if self.use_percentage_based or any('percentage' in lc for lc in sorted_levels):
                # Display percentages
                levels_str = ','.join([f"L{lc.get('level')}:{lc.get('percentage', 0)}%" 
                                      for lc in sorted_levels if 'percentage' in lc])
                total = sum(Decimal(str(lc.get('percentage', 0))) for lc in sorted_levels if 'percentage' in lc)
                return f"{self.name} ({levels_str}, Total: {total}%)"
            else:
                # Display USD per lot
                levels_str = ','.join([f"L{lc.get('level')}:${lc.get('usd_per_lot', 0)}" 
                                      for lc in sorted_levels if 'usd_per_lot' in lc])
                total = sum(Decimal(str(lc.get('usd_per_lot', 0))) for lc in sorted_levels if 'usd_per_lot' in lc)
                group_info = f", Groups: {len(self.approved_groups)}" if self.approved_groups else ", Groups: All"
                return f"{self.name} ({levels_str} per lot, Max: ${total}{group_info})"
        
        # Legacy display logic
        elif not self.use_percentage_based and self.level_amounts_usd_per_lot and self.level_amounts_usd_per_lot.strip():
            amounts = self.get_level_amounts_list()
            levels_str = ','.join([f"L{i+1}:${a}" for i, a in enumerate(amounts)])
            total_str = f"${sum(amounts)}" if amounts else "$0"
            group_info = f", Groups: {len(self.approved_groups)}" if self.approved_groups else ", Groups: All"
            return f"{self.name} ({levels_str} per lot, Max: {total_str}{group_info})"
        elif self.use_percentage_based:
            percentages = self.get_level_percentages_list()
            if percentages:
                total = sum(percentages)
                levels_str = ','.join([f"L{i+1}:{p}%" for i, p in enumerate(percentages)])
                return f"{self.name} ({levels_str}, Total: {total}%)"
            else:
                # Fallback to individual fields
                total = self.level_1_percentage + self.level_2_percentage + self.level_3_percentage
                return f"{self.name} (L1: {self.level_1_percentage}%, L2: {self.level_2_percentage}%, L3: {self.level_3_percentage}%, Total: {total}%)"
        else:
            # USD per lot fallback to individual fields
            total = self.level_1_usd_per_lot + self.level_2_usd_per_lot + self.level_3_usd_per_lot
            group_info = f", Groups: {len(self.approved_groups)}" if self.approved_groups else ", Groups: All"
            return f"{self.name} (L1: ${self.level_1_usd_per_lot}, L2: ${self.level_2_usd_per_lot}, L3: ${self.level_3_usd_per_lot} per lot, Max: ${total}{group_info})"

    class Meta:
        ordering = ['-created_at']


class CommissioningProfileGroup(models.Model):
    """Stores per-profile, per-group dynamic level USD amounts as a list.
    Example: amounts = [50.00, 20.00, 10.00] corresponds to L1, L2, L3.
    """
    profile = models.ForeignKey(CommissioningProfile, on_delete=models.CASCADE, related_name='group_commissions')
    group_name = models.CharField(max_length=255, help_text="Trading group name (e.g., KRSN\\1075-USD-B)")
    amounts = models.JSONField(default=list, help_text="List of USD per lot amounts for levels, e.g. [50,20,10]")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('profile', 'group_name')

    def __str__(self):
        return f"{self.profile.name} - {self.group_name} ({','.join([str(a) for a in self.amounts])})"

    def get_amounts_list(self):
        # Ensure Decimal conversion when needed
        from decimal import Decimal
        try:
            return [Decimal(str(a)) for a in self.amounts]
        except Exception:
            return []

class CommissionTransaction(models.Model):
    client_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="commission_transactions_as_client"
    )
    client_trading_account = models.ForeignKey(
        'TradingAccount',
        on_delete=models.CASCADE,
        related_name="commission_transactions"
    )
    ib_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="commission_transactions_as_ib"
    )
    ib_level = models.PositiveIntegerField()
    total_commission = models.DecimalField(max_digits=12, decimal_places=2)
    commission_to_ib = models.DecimalField(max_digits=12, decimal_places=2)
    # CRITICAL: Add db_index for fast position lookup during duplicate detection
    position_id = models.CharField(max_length=100, db_index=True)  # MT5 Position ID
    deal_ticket = models.CharField(max_length=100, blank=True, null=True)  # MT5 Deal Ticket ID (actual close ticket)
    position_type = models.CharField(max_length=100, default='buy')
    position_symbol = models.CharField(max_length=100, default='')  
    position_direction = models.CharField(max_length=100, default='in')
    # MT5 close time - exact timestamp when position was closed in MT5
    mt5_close_time = models.DateTimeField(blank=True, null=True, help_text="Actual MT5 position close time")
    # New fields to store trade lot size and profit from MT5
    lot_size = models.FloatField(default=0.0)
    profit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    # Optional field indicating origin of commission record (e.g. 'mt5', 'backfill')
    source = models.CharField(max_length=100, default='mt5')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        # Ensure uniqueness to avoid duplicate commission records for same position
        # and account/IB level. A migration will be required after this change.
        unique_together = (('position_id', 'client_trading_account', 'ib_user', 'ib_level'),)
        
        # Add composite indexes for common queries
        indexes = [
            # Fast lookup for position duplicate detection (most common query)
            models.Index(fields=['position_id', 'client_trading_account', 'ib_user'], name='position_lookup_idx'),
            # Fast IB commission queries
            models.Index(fields=['ib_user', 'created_at'], name='ib_commissions_idx'),
            # Fast client commission queries
            models.Index(fields=['client_user', 'created_at'], name='client_commissions_idx'),
            # Fast trading account queries
            models.Index(fields=['client_trading_account', 'created_at'], name='account_commissions_idx'),
        ]

    def __str__(self):
        return f"CommissionTransaction: IB {self.ib_user.user_id}, Client {self.client_user.user_id}, Level {self.ib_level}, Commission: {self.commission_to_ib}"

    @classmethod
    def _validate_commission_creation(cls, client):
        """Validate if commission creation should proceed. Returns (ib_user, commission_profile) or (None, None)."""
        # Safety switch: allow disabling commission creation via environment variable
        import os
        if os.environ.get('DISABLE_COMMISSION_CREATION', '').lower() in ('1', 'true', 'yes'):
            return None, None

        ib_user = client.parent_ib
        if not ib_user or not ib_user.IB_status:
            return None, None

        # Get commission profile
        profile_id = getattr(ib_user, 'commissioning_profile_id', None)
        if not profile_id:
            return None, None

        try:
            commission_profile = CommissioningProfile.objects.filter(id=profile_id).only(
                'id', 'name', 'level_amounts_usd_per_lot', 'use_percentage_based',
                'level_1_usd_per_lot', 'level_2_usd_per_lot', 'level_3_usd_per_lot',
                'level_1_percentage', 'level_2_percentage', 'level_3_percentage',
                'commission_percentage', 'approved_groups', 'dynamic_levels'
            ).first()
            
            if not commission_profile:
                commission_profile = CommissioningProfile.objects.filter(id=profile_id).first()
                
            return ib_user, commission_profile
        except Exception as e:
            logger.error(f"Failed to fetch commission profile: {e}")
            return None, None

    @classmethod
    def _calculate_commission_amount(cls, commission_profile, level, abs_commission, lot_size_decimal):
        """Calculate commission amount for a specific level."""
        commission_to_ib = Decimal('0.00')
        
        if commission_profile.use_percentage_based:
            percentage = commission_profile.get_percentage_for_level(level)
            if percentage > 0:
                commission_to_ib = (abs_commission * percentage / Decimal('100')).quantize(Decimal('.01'))
        else:
            amount_per_lot = commission_profile.get_amount_for_level(level)
            if amount_per_lot > 0:
                commission_to_ib = (amount_per_lot * lot_size_decimal).quantize(Decimal('.01'))
        
        return commission_to_ib

    @classmethod
    def _create_or_get_transaction(cls, position_id, trading_account, current_ib, level, client, 
                                   abs_commission, commission_to_ib, position_type, trading_symbol, 
                                   position_direction, lot_size, profit, deal_ticket=None, mt5_close_time=None):
        """Create or get existing commission transaction. Returns (obj, created)."""
        try:
            obj, created = cls.objects.get_or_create(
                position_id=position_id,
                client_trading_account=trading_account,
                ib_user=current_ib,
                ib_level=level,
                defaults={
                    'client_user': client,
                    'total_commission': abs_commission,
                    'commission_to_ib': commission_to_ib,
                    'position_type': position_type,
                    'position_symbol': trading_symbol,
                    'position_direction': position_direction,
                    'lot_size': float(lot_size or 0.0),
                    'profit': Decimal(str(profit or 0.0)),
                    'source': 'mt5',
                    'deal_ticket': deal_ticket,  # Store MT5 Deal Ticket
                    'mt5_close_time': mt5_close_time,  # Store exact MT5 close time
                }
            )
            return obj, created
        except IntegrityError:
            # Duplicate detected - just fetch existing record (only needed fields for performance)
            obj = cls.objects.filter(
                position_id=position_id,
                client_trading_account=trading_account,
                ib_user=current_ib,
                ib_level=level
            ).only('id', 'lot_size', 'profit', 'commission_to_ib', 'deal_ticket', 'mt5_close_time').first()
            return obj, False

    @classmethod
    def _update_transaction_details(cls, obj, lot_size, profit):
        """Update lot_size and profit if missing."""
        if not obj:
            return
        
        updated = False
        if not obj.lot_size or obj.lot_size == 0.0:
            obj.lot_size = float(lot_size or 0.0)
            updated = True
        
        if not obj.profit or obj.profit == Decimal('0.00'):
            obj.profit = Decimal(str(profit or 0.0))
            updated = True
        
        if updated:
            try:
                obj.save(update_fields=['lot_size', 'profit'])
            except Exception as e:
                logger.warning(f"Failed to update transaction details: {e}")

    @classmethod
    def _credit_mt5_account(cls, current_ib, commission_to_ib, level, position_id, 
                           commission_profile, lot_size_decimal):
        """Credit MT5 account with commission."""
        try:
            from adminPanel.mt5.services import MT5ManagerActions
            
            if not hasattr(current_ib, 'account_id') or not current_ib.account_id:
                return
            
            mt5 = MT5ManagerActions()
            comment = f"IB Commission L{level} for trade {position_id}"
            if not commission_profile.use_percentage_based:
                comment += f" (${commission_profile.get_amount_for_level(level)}/lot × {lot_size_decimal} lots)"
            
            mt5.credit_in(current_ib.account_id, float(commission_to_ib), comment)
            logger.info(f"Commission credited: {commission_to_ib} to IB {current_ib.email} (L{level}) for trade {position_id}")
        except Exception as e:
            logger.error(f"Failed to credit MT5 for IB {current_ib.email}: {e}")

    @classmethod
    def create_commission(cls, client, total_commission, position_id, trading_account, 
                         trading_symbol, position_type, position_direction, lot_size=1.0, profit=0.0,
                         deal_ticket=None, mt5_close_time=None):
        """
        Creates commission transactions for the IB hierarchy.
        Supports both percentage-based and USD per lot calculations.
        Optimized for faster position detection and processing.
        
        Args:
            deal_ticket: MT5 Deal Ticket ID (actual close ticket)
            mt5_close_time: Exact MT5 position close time
        """
        # Quick validation
        ib_user, commission_profile = cls._validate_commission_creation(client)
        if not ib_user or not commission_profile:
            return

        # Exclude demo accounts from commission calculations
        # Check 1: Check account_type field directly
        if hasattr(trading_account, 'account_type') and trading_account.account_type == 'demo':
            # logger.info(f"Skipping commission for demo account - Type: demo, Account: {trading_account.account_id}")
            return
        
        # Check 2: Check if group_name matches a demo TradeGroup
        if hasattr(trading_account, 'group_name') and trading_account.group_name:
            try:
                trade_group = TradeGroup.objects.filter(name=trading_account.group_name).first()
                if trade_group and trade_group.type == 'demo':
                    # logger.info(f"Skipping commission for demo account - Group: {trading_account.group_name}, Account: {trading_account.account_id}")
                    return
            except Exception as e:
                logger.warning(f"Failed to check demo account status: {e}")
                # Continue with commission creation if check fails
        
        # Check 3: Check if group_name contains 'demo' keyword (case-insensitive)
        if hasattr(trading_account, 'group_name') and trading_account.group_name:
            if 'demo' in trading_account.group_name.lower():
                # logger.info(f"Skipping commission for demo account - Group contains 'demo': {trading_account.group_name}, Account: {trading_account.account_id}")
                return
        
        # Check if trading group is approved
        if hasattr(trading_account, 'group_name') and trading_account.group_name:
            if not commission_profile.is_group_approved(trading_account.group_name):
                return

        # Prepare calculations
        abs_commission = abs(Decimal(str(total_commission)))
        lot_size_decimal = Decimal(str(lot_size))
        
        # Process IB hierarchy
        current_ib = ib_user
        level = 1
        
        # Continue up the hierarchy until no more parent IBs
        while current_ib:
            # Get current IB's commission profile
            current_ib_profile = getattr(current_ib, 'commissioning_profile', None)
            if not current_ib_profile:
                # No profile = no commission, skip to next level
                current_ib = current_ib.parent_ib
                level += 1
                continue
            
            # Check if this IB's profile supports this hierarchy level
            max_levels_for_ib = current_ib_profile.get_max_levels()
            if level > max_levels_for_ib:
                # This IB's profile doesn't support this level, stop here
                break
            
            # Calculate commission using the hierarchy level from IB's own profile
            # Use the actual hierarchy level to get the correct percentage/amount
            commission_to_ib = cls._calculate_commission_amount(
                current_ib_profile, level, abs_commission, lot_size_decimal
            )
            
            if commission_to_ib > 0:
                # Create or get transaction record (keep the hierarchy level for tracking)
                obj, created = cls._create_or_get_transaction(
                    position_id, trading_account, current_ib, level, client,
                    abs_commission, commission_to_ib, position_type, trading_symbol,
                    position_direction, lot_size, profit, deal_ticket, mt5_close_time
                )
                
                # Update details if needed
                if obj and not created:
                    cls._update_transaction_details(obj, lot_size, profit)
                
                # Credit MT5 only for new records
                if created:
                    cls._credit_mt5_account(
                        current_ib, commission_to_ib, level, position_id,
                        current_ib_profile, lot_size_decimal
                    )
            
            # Move to next level
            current_ib = current_ib.parent_ib
            level += 1

class MT5SendDedup(models.Model):
    """Simple table to deduplicate MT5 DealerSend operations across processes.

    Key is a sanitized identifier for the send (operation_type_follower_comment or similar).
    Records are short-lived; broker scripts will ignore keys younger than a TTL and may
    remove stale keys when appropriate.
    """
    key = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['created_at'])]

    def __str__(self):
        return f"MT5SendDedup({self.key}, {self.created_at.isoformat()})"

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get('is_superuser') is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)

class CustomUser(AbstractBaseUser, PermissionsMixin):
    def set_password(self, raw_password):
        # Use Django's secure password hashing only. Do NOT store plaintext passwords.
        super().set_password(raw_password)
        # Field to store which referral code was used at registration (for clients)
    referral_code_used = models.CharField(max_length=100, blank=True, null=True, help_text="Referral code used at registration.")
    user_id = models.PositiveIntegerField(unique=True, editable=False, null=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    # Legacy DB compatibility: some schemas contain an `old_commission` column
    # Ensure it's present in the model with a safe default to avoid NOT NULL errors
    old_commission = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        null=True,
        blank=True,
        help_text="Compatibility field for legacy commission values."
    )
    # Legacy DB compatibility: some schemas contain an `old_commission_withdrawal` column
    # Add it here with safe defaults to avoid NOT NULL constraint failures on signup.
    old_commission_withdrawal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        null=True,
        blank=True,
        help_text="Compatibility field for legacy commission withdrawal values."
    )
    dob = models.DateField(null=True, blank=True)  
    phone_number = models.CharField(max_length=100, blank=True)
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=101, editable=False)
    role = models.CharField(
        max_length=10,
        choices=[
            ('admin', 'Admin'),
            ('manager', 'Manager'), 
            ('client', 'Client')
        ],
        default='client'
    )
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=10, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    def user_profile_image_path(instance, filename):
        import os
        extension = os.path.splitext(filename)[1]
        return f"users/profile_images/{instance.email}{extension}"

    profile_pic = models.ImageField(upload_to=user_profile_image_path, blank=True, null=True)
    verification_status = models.CharField(
        max_length=20,
        choices=[('pending', 'Pending'), ('verified', 'Verified'), ('rejected', 'Rejected')],
        default='pending',
        null=False,
        blank=False,
        help_text="Verification status for the user."
    )
    is_approved_by_admin = models.BooleanField(
        default=False,
        help_text="Whether the user has been approved by admin to access the platform."
    )
    # File upload methods
    def id_file(instance, filename):
        user_id = instance.user_id if instance.user_id else "unsaved"
        extension = os.path.splitext(filename)[1]  
        return f"users/id_proofs/{user_id}_idProof{extension}"

    def address_file(instance, filename):
        user_id = instance.user_id if instance.user_id else "unsaved"
        extension = os.path.splitext(filename)[1]  
        return f"users/address_proofs/{user_id}_idProof{extension}"

    id_proof = models.FileField(upload_to=id_file, blank=True, null=True, help_text="ID Proof file")
    address_proof = models.FileField(upload_to=address_file, blank=True, null=True, help_text="Address Proof file")
    address_proof_verified = models.BooleanField(default=False)
    id_proof_verified = models.BooleanField(default=False)

    @property
    def user_verified(self):
        return self.id_proof_verified and self.address_proof_verified
    
    IB_status = models.BooleanField(default=False)
    referral_code = models.CharField(max_length=20, unique=True, blank=True, null=True, help_text="Unique referral code for IB users.")
    def generate_referral_code(self):
        import string, random
        # Generate a unique 8-character code
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            if not CustomUser.objects.filter(referral_code=code).exists():
                return code

    MAM_manager_status = models.BooleanField(default=False)

    otp = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)
    # Separate fields for login-specific OTPs to avoid collision with password-reset OTPs
    # max_length=256 to store hashed OTP (format: salt$hash)
    login_otp = models.CharField(max_length=256, blank=True, null=True)
    login_otp_created_at = models.DateTimeField(blank=True, null=True)
    # Fast-access last-login info to avoid scanning ActivityLog for login checks
    last_login_ip = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    last_login_at = models.DateTimeField(blank=True, null=True, db_index=True)
    
    created_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_users',
        help_text="The user who created this account. Default is None if self-signup."
    )
    # Plaintext password storage removed for security. Use Django's hashed password field instead.
    
    # Add get_full_name method
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return self.username


    
    manager_admin_status = models.CharField(
        max_length=20,
        choices=[
            ('None', 'None'),
            ('Admin Level 1', 'Admin Level 1'),
            ('Admin Level 2', 'Admin Level 2'),
            ('Manager Level 1', 'Manager Level 1'),
            ('Manager Level 2', 'Manager Level 2'),
            ('Manager Level 3', 'Manager Level 3'),
        ],
        default='None',
    )
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='custom_user_set',
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='custom_user_set',
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
    )
    @property
    def total_earnings(self):
        """Calculate total earnings dynamically as Decimal, excluding demo account commissions."""
        return Decimal(
            CommissionTransaction.objects.filter(
                ib_user=self
            ).exclude(
                client_trading_account__account_type='demo'
            ).aggregate(
                total=Sum('commission_to_ib')
            )['total'] or 0.00
        ).quantize(Decimal('0.01'))

    @property
    def total_commission_withdrawals(self):
        """Calculate total commission withdrawals dynamically as Decimal."""
        return Decimal(
            Transaction.objects.filter(
                user=self, transaction_type="commission_withdrawal", status="approved"
            ).aggregate(total=Sum('amount'))['total'] or 0.00
        ).quantize(Decimal('0.01'))        
        
        
    date_joined = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    
    parent_ib = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='clients')
    commissioning_profile = models.ForeignKey(
        'CommissioningProfile', null=True, blank=True, on_delete=models.SET_NULL, related_name='ib_users'
    )

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    def __str__(self):
        return self.email



    def save(self, *args, **kwargs):
        self.username = f"{self.first_name} {self.last_name}"

        if not self.user_id:
            max_id = CustomUser.objects.aggregate(models.Max('user_id'))['user_id__max']
            self.user_id = max(max_id + 1, 7000000) if max_id else 7000000

        # If user is IB and has no referral code, generate one
        if self.IB_status and not self.referral_code:
            self.referral_code = self.generate_referral_code()

        if self.IB_status and not self.commissioning_profile:
            raise ValidationError("IB users must have an assigned commissioning profile.")

        # --- AUTOMATICALLY ASSIGN CLIENTS' parent_ib WHEN IB STATUS IS ENABLED ---
        # Only run this logic if IB_status is being set to True and the user has a referral_code
        if self.pk is not None:
            # Fetch previous value from DB
            try:
                prev = CustomUser.objects.get(pk=self.pk)
            except CustomUser.DoesNotExist:
                prev = None
        else:
            prev = None

        super().save(*args, **kwargs)

        # If IB_status changed from False to True, assign parent_ib for all clients who used this IB's code
        if self.IB_status and self.referral_code:
            if prev is None or not prev.IB_status:
                # Find all clients who used this IB's referral code and have no parent_ib
                clients = CustomUser.objects.filter(referral_code_used=self.referral_code, parent_ib__isnull=True)
                for client in clients:
                    client.parent_ib = self
                    client.save(update_fields=['parent_ib'])

        # --- AUTOMATICALLY ASSIGN IB CLIENTS TO MANAGER WHEN IB BECOMES MANAGER ---
        # If role changed to 'manager', assign all IB clients to this manager as created_by
        if self.role == 'manager':
            role_changed = prev is None or prev.role != 'manager'
            
            if role_changed:
                # Case 1: IB user becomes manager - assign their IB clients to them
                if self.IB_status and self.referral_code:
                    # Find all clients who used this IB's referral code
                    ib_clients = CustomUser.objects.filter(
                        referral_code_used=self.referral_code,
                        role='client'
                    )
                    
                    # Update created_by to point to this manager for all their IB clients
                    updated_count = 0
                    for client in ib_clients:
                        if client.created_by != self:
                            client.created_by = self
                            client.save(update_fields=['created_by'])
                            updated_count += 1
                    
                    if updated_count > 0:
                        logger.info(f"✅ Assigned {updated_count} IB clients to manager {self.email}")
                
                # Case 2: Also assign any existing clients where this user is parent_ib
                existing_ib_clients = CustomUser.objects.filter(
                    parent_ib=self,
                    role='client'
                ).exclude(created_by=self)
                
                if existing_ib_clients.exists():
                    updated_count = existing_ib_clients.update(created_by=self)
                    logger.info(f"✅ Assigned {updated_count} existing IB clients to manager {self.email}")
                
                logger.info(f"🎯 User {self.email} became manager - auto-assigned their IB clients")

    def mark_documents_verified(self):
        """
        Marks both ID Proof and Address Proof as verified and checks if the user can be fully verified.
        """
        self.id_proof_verified = True
        self.address_proof_verified = True
        
        self.save()

    def generate_otp(self):
        self.otp = f"{random.randint(100000, 999999)}"
        self.otp_created_at = timezone.now()
        self.save()

    def generate_login_otp(self):
        """Generate a one-time code specifically for login verification (new-IP)."""
        self.login_otp = f"{random.randint(100000, 999999)}"
        self.login_otp_created_at = timezone.now()
        self.save(update_fields=['login_otp', 'login_otp_created_at'])

    def is_otp_valid(self, otp):
        """Validate OTP (check value and expiration within 10 minutes)."""
        if self.otp != otp:
            return False
        expiration_time = timezone.now() - timezone.timedelta(minutes=10)
        return self.otp_created_at and self.otp_created_at > expiration_time

    def is_login_otp_valid(self, otp=None):
        """Validate login OTP (check value and expiration).

        Uses the `LOGIN_OTP_TTL_SECONDS` Django setting (defaults to 60 seconds).
        
        If otp is provided, verifies the hashed OTP matches the provided plain text.
        If otp is None, just checks if a valid (non-expired) OTP exists.
        """
        # Check if OTP exists and hasn't expired
        ttl = getattr(settings, 'LOGIN_OTP_TTL_SECONDS', 60)
        expiration_time = timezone.now() - timezone.timedelta(seconds=ttl)
        
        if not self.login_otp or not self.login_otp_created_at:
            return False
            
        if self.login_otp_created_at <= expiration_time:
            return False
        
        # If otp is provided, verify it against the hash
        if otp is not None:
            try:
                from adminPanel.views.auth_views import verify_otp
                return verify_otp(self.login_otp, otp)
            except Exception:
                return False
        
        # If no otp provided, just check expiration
        return True

    def get_level(self):
        """Calculate the level of this user relative to their 'top-level' IB."""
        level = 1
        current_ib = self.parent_ib
        while current_ib:
            level += 1
            current_ib = current_ib.parent_ib
        return level

    def get_all_clients(self, max_level=None):
        """Recursively fetch all clients under this IB up to an optional max level."""
        def fetch_clients(ib_user, level=1):
            if max_level and level > max_level:
                return []
            direct_clients = ib_user.clients.all()
            all_clients = list(direct_clients)
            for client in direct_clients:
                if client.IB_status:  
                    all_clients.extend(fetch_clients(client, level + 1))
            return all_clients
        return fetch_clients(self)

    def get_clients_by_level(self, target_level):
        
        def fetch_clients_by_level(ib_user, current_level):
            if current_level == target_level:
                return ib_user.clients.all()
            elif current_level < target_level:
                all_clients = []
                for client in ib_user.clients.filter(IB_status=True):  
                    all_clients.extend(fetch_clients_by_level(client, current_level + 1))
                return all_clients
            else:
                return []
        return fetch_clients_by_level(self, current_level=1)

    @property
    def direct_client_count(self):
        return self.clients.count()

class TradingAccount(models.Model):
    ACCOUNT_TYPE_CHOICES = [
        ('standard', 'Standard Trading Account'),
        ('mam', 'MAM Master Account'),
        ('mam_investment', 'MAM Investment Account'),
        ('prop', 'Proprietary Trading Account'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='trading_accounts',
        help_text="The user who owns this trading account."
    )
    account_id = models.CharField(
        max_length=100,
        unique=True,
        help_text="Unique identifier for the trading account."
    )
    account_type = models.CharField(
        max_length=20,
        choices=ACCOUNT_TYPE_CHOICES,
        default='standard',
        help_text="Type of the trading account."
    )
    account_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Name of the trading account."
    )
    leverage = models.PositiveIntegerField(
        default=100,
        help_text="Leverage value (integer only)."
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Current balance of the trading account."
    )
    
    equity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Current equity of the trading account."
    )
    
    margin = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Current margin of the trading account."
    )
    
    margin_free = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Free margin available in the trading account."
    )
    
    margin_level = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Current margin level of the trading account."
    )
    
    status = models.CharField(
        max_length=20,
        default='pending_activation',
        choices=[
            ('pending_activation', 'Pending Activation'),
            ('active', 'Active'),
            ('disabled', 'Disabled'),
            ('suspended', 'Suspended'),
        ],
        help_text="Current status of the trading account."
    )
    
    algo_enabled = models.BooleanField(
        default=False,
        help_text="Whether algorithmic trading is enabled for this account."
    )
   
    is_enabled = models.BooleanField(
        default=True,
        help_text="Whether the account is enabled."
    )
    is_trading_enabled = models.BooleanField(
        default=True,
        help_text="Whether trading is enabled for this account."
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the account was created."
    )
    group_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Trading group name, if applicable."
    )
    manager_allow_copy = models.BooleanField(
        default=True,
        help_text="Indicates if the manager allows copying."
    )
    investor_allow_copy = models.BooleanField(
        default=True,
        help_text="Indicates if the investor allows copying."
    )

    
    is_pending = models.BooleanField(
        default=True,
        help_text="Indicates if the trading account is pending activation."
    )
    mam_master_account = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='investments',
        help_text="Link to the MAM master account (for investment accounts)."
    )
    
    # Fields for MAM investment copy settings
    COPY_MODE_CHOICES = [
        ('balance_ratio', 'By Balance Ratio'),
        ('fixed_multiple', 'By Fixed Multiple'),
    ]
    copy_mode = models.CharField(
        max_length=20,
        choices=COPY_MODE_CHOICES,
        default='balance_ratio',
        blank=True,
        null=True,
        help_text="The copy mode for MAM investment accounts (Balance Ratio or Fixed Multiple)."
    )
    # Legacy/DB compatibility field: some database schemas use copy_multiplier_mode column name
    # Keep a non-null default so inserts from parts of the code that don't set this field succeed.
    copy_multiplier_mode = models.CharField(
        max_length=50,
        default='balance_ratio',
        help_text="Compatibility field for older DB schemas (stores copy mode as text)."
    )
    # Compatibility numeric multiplier for fixed multiple copy mode
    fixed_copy_multiplier = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Compatibility numeric multiplier used when copy mode is fixed multiple."
    )
    # Max copy multiplier exists in DB schema per error message
    max_copy_multiplier = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Compatibility max multiplier for copy settings."
    )
    # Copy trading enabled flag - DB column exists and requires non-null value
    copy_trade_enabled = models.BooleanField(
        default=False,
        help_text="Whether copy trading is enabled for this account."
    )
    copy_factor = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        default=Decimal('1.00'),
        blank=True,
        null=True,
        help_text="The coefficient factor used for trade copying in MAM investment accounts."
    )
    dual_trade_enabled = models.BooleanField(
        default=False,
        help_text="Whether to enable multiple trade copying (legacy field, use multi_trade_count instead)."
    )
    multi_trade_count = models.PositiveIntegerField(
        default=1,
        help_text="Number of times to copy each master trade to the investor account (1-10)."
    )
    profit_sharing_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Profit sharing percentage (for MAM master accounts)."
    )
    risk_level = models.CharField(
        max_length=10,
        choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
        blank=True,
        null=True,
        help_text="Risk level (for MAM master accounts)."
    )
    is_algo_enabled = models.BooleanField(
        default=False,
        help_text="Indicates whether algorithmic trading is enabled (for MAM)."
    )
    payout_frequency = models.CharField(
        max_length=20,
        choices=[
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
            ('quarterly', 'Quarterly'),
            ('half-yearly', 'Half-Yearly')
        ],
        blank=True,
        null=True,
        help_text="Frequency of profit payouts (for MAM master accounts)."
    )

    
    package = models.ForeignKey(
        'Package',
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='prop_trading_accounts',
        help_text="The package associated with this proprietary trading account."
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('running', 'Running'),
            ('success', 'Success'),
            ('failed', 'Failed')
        ],
        blank=True,
        null=True,
        default='running',
        help_text="Current status of the proprietary trading account."
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_prop_accounts',
        help_text="Admin or manager who approved this account."
    )
    approved_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp when the account was approved."
    )
    start_date = models.DateTimeField(
        blank=True,
        null=True,
        help_text="The start date of trading for this proprietary account."
    )
    end_date = models.DateTimeField(
        blank=True,
        null=True,
        help_text="The end date of trading for this proprietary account."
    )

    def save(self, *args, **kwargs):
        
        if self.account_type == 'mam' and not self.profit_sharing_percentage:
            raise ValueError("Profit sharing percentage is required for MAM accounts.")
        
        if self.account_type == 'mam_investment' and not self.mam_master_account:
            raise ValueError("MAM Investment accounts must be linked to a MAM Master account.")

        if not self.account_name:
            if self.account_type == 'mam':
                self.account_name = f"({self.account_id})-MAM"
            if self.account_type == 'mam_investment':
                self.account_name = f"({self.account_id})-INV"
            if self.account_type == 'prop':
                self.account_name = f"({self.account_id})-PROP"
            if self.account_type == 'standard':
                self.account_name = f"({self.account_id})"

        if self.account_type == 'prop' and self.approved_at and not self.start_date:
            self.start_date = self.approved_at
            if self.package:
                self.end_date = self.approved_at + timezone.timedelta(days=self.package.target_time_in_days)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.account_type} - {self.account_id} - User: {self.user.email}"

    def is_mam_master(self):
        return self.account_type == 'mam'

    def is_mam_investment(self):
        return self.account_type == 'mam_investment'

    def is_standard_account(self):
        return self.account_type == 'standard'

    def is_prop_account(self):
        return self.account_type == 'prop'

    def get_investments(self):
        if self.is_mam_master():
            return self.investments.all()
        return None

class Transaction(models.Model):
    admin_comment = models.TextField(
        blank=True,
        null=True,
        help_text="Admin approval/rejection comment for this transaction."
    )
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='transactions',
        help_text="User associated with the transaction."
    )
    source = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="The origin or source of the transaction (e.g., 'Bank', 'Crypto', 'Internal')."
    )

    
    trading_account = models.ForeignKey(
        'TradingAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions',
        help_text="Trading account involved in the transaction, if applicable."
    )

    TRANSACTION_TYPE_CHOICES = [
        ('deposit_trading', 'Deposit into Trading Account'),
        ('withdraw_trading', 'Withdrawal from Trading Account'),
        ('credit_in', 'Credit In into Trading Account'),
        ('credit_out', 'Credit Out from Trading Account'),
        ('commission_withdrawal', 'Commission Withdrawal'),
        ('internal_transfer', 'Internal Transfer Between Trading Accounts'),
    ]
    transaction_type = models.CharField(
        max_length=30,
        choices=TRANSACTION_TYPE_CHOICES,
        help_text="Type of transaction."
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Amount involved in the transaction."
    )
    description = models.TextField(
        blank=True,
        null=True,
        help_text="Description or notes for the transaction."
    )
    created_at = models.DateTimeField(auto_now_add=True, help_text="When the transaction was created.")

    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="Transaction status."
    )

    
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_transactions',
        help_text="Admin who approved/rejected this transaction."
    )
    approved_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp when the transaction was approved/rejected."
    )

    
    payout_to = models.CharField(
        max_length=50,
        choices=[('bank', 'Bank'), ('crypto', 'Crypto')],
        blank=True,
        null=True,
        help_text="Payout destination type (external payouts only)."
    )
    external_account = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Bank or crypto account details for the external payout."
    )

    
    from_account = models.ForeignKey(
        'TradingAccount',
        on_delete=models.CASCADE,
        related_name='outgoing_transfers',
        blank=True,
        null=True,
        help_text="Source trading account for internal transfers."
    )
    to_account = models.ForeignKey(
        'TradingAccount',
        on_delete=models.CASCADE,
        related_name='incoming_transfers',
        blank=True,
        null=True,
        help_text="Destination trading account for internal transfers."
    )
    migrated_to_old_withdrawal = models.BooleanField(
        default=False,
        help_text="Whether this transaction has been migrated to the old withdrawal system."
    )

    def document_file(instance, filename):
        tran_id = instance.id if instance.id else "unsaved"
        extension = os.path.splitext(filename)[1]  
        return f"transaction_documents/{tran_id}_{extension}"

    document = models.FileField(
        upload_to=document_file,
        blank=True,
        null=True,  
        help_text="Optional document (image or PDF) related to the transaction."
    )

    def __str__(self):
        return f"Transaction {self.id} ({self.get_transaction_type_display()}) - ${self.amount} - {self.get_status_display()}"

    def clean(self):
        """
        Validation to ensure proper usage of fields based on transaction type.
        """
        if self.transaction_type == 'internal_transfer':
            if not self.from_account or not self.to_account:
                raise ValidationError("Internal transfers must specify both from_account and to_account.")
            if self.from_account == self.to_account:
                raise ValidationError("from_account and to_account must be different for internal transfers.")
        else:
            if self.from_account or self.to_account:
                raise ValidationError("from_account and to_account should only be set for internal transfers.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']

class DemoAccount(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='demo_accounts')
    account_name = models.CharField(max_length=255, blank=True, default="")
    account_id = models.CharField(max_length=100, unique=True, default=uuid.uuid4)
    leverage = models.CharField(max_length=20, default="100")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('10000.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    is_enabled = models.BooleanField(default=True)  
    is_algo_enabled = models.BooleanField(default=True)  
    is_active = models.BooleanField(default=True)  # Added for enable/disable logic

    def save(self, *args, **kwargs):
        if not self.account_name:
            self.account_name = f"{self.user.username} - Demo"
        super().save(*args, **kwargs)
        # --- Auto-create/update TradingAccount for dashboard stats ---
        from adminPanel.models import TradingAccount
        TradingAccount.objects.update_or_create(
            account_id=self.account_id,
            defaults={
                'user': self.user,
                'account_name': self.account_name or f"Demo Account {self.account_id}",
                'leverage': int(self.leverage) if self.leverage else 100,
                'balance': self.balance if self.balance else Decimal('10000.00'),
                'is_enabled': self.is_enabled,
                'is_algo_enabled': getattr(self, 'is_algo_enabled', True),
                'account_type': 'demo',
            }
        )

    def __str__(self):
        return f"Demo - {self.account_name} - {self.user.email}"
    
class EmailSetting(models.Model):
    
    
    user_registration_from = models.EmailField(blank=True, null=True, verbose_name="User Registration (From)")
    user_registration_to = models.EmailField(blank=True, null=True, verbose_name="User Registration (To)")
    account_approval_from = models.EmailField(blank=True, null=True, verbose_name="Account Approval (From)")
    account_rejection_from = models.EmailField(blank=True, null=True, verbose_name="Account Rejection (From)")

    
    trading_account_opening_from = models.EmailField(blank=True, null=True, verbose_name="Trading Account Opening (From)")
    trading_account_opening_to = models.EmailField(blank=True, null=True, verbose_name="Trading Account Opening (To)")
    demo_account_welcome_from = models.EmailField(blank=True, null=True, verbose_name="Demo Account Welcome (From)")
    demo_account_welcome_to = models.EmailField(blank=True, null=True, verbose_name="Demo Account Notification (To)")

    
    mam_manager_notification_from = models.EmailField(blank=True, null=True, verbose_name="MAM Manager Notification (From)")
    mam_investor_notification_from = models.EmailField(blank=True, null=True, verbose_name="MAM Investor Notification (From)")
    prop_trading_notification_from = models.EmailField(blank=True, null=True, verbose_name="Proprietary Trading Notification (From)")
    prop_trading_notification_to = models.EmailField(blank=True, null=True, verbose_name="Proprietary Trading Notification (To)")

    
    deposit_notification_from = models.EmailField(blank=True, null=True, verbose_name="Deposit Notification (From)")
    deposit_notification_to = models.EmailField(blank=True, null=True, verbose_name="Deposit Notification (To)")
    withdrawal_notification_from = models.EmailField(blank=True, null=True, verbose_name="Withdrawal Notification (From)")
    withdrawal_notification_to = models.EmailField(blank=True, null=True, verbose_name="Withdrawal Notification (To)")
    internal_transfer_notification_from = models.EmailField(blank=True, null=True, verbose_name="Internal Transfer Notification (From)")
    internal_transfer_notification_to = models.EmailField(blank=True, null=True, verbose_name="Internal Transfer Notification (To)")

    
    promotional_email_from = models.EmailField(blank=True, null=True, verbose_name="Promotional Email (From)")
    sales_inquiry_from = models.EmailField(blank=True, null=True, verbose_name="Sales Inquiry (From)")
    sales_inquiry_to = models.EmailField(blank=True, null=True, verbose_name="Sales Inquiry (To)")

    
    daily_report_from = models.EmailField(blank=True, null=True, verbose_name="Daily Report (From)")
    daily_report_to = models.EmailField(blank=True, null=True, verbose_name="Daily Report (To)")
    trading_performance_report_from = models.EmailField(blank=True, null=True, verbose_name="Trading Performance Report (From)")

    
    support_ticket_from = models.EmailField(blank=True, null=True, verbose_name="Support Ticket (From)")
    support_ticket_to = models.EmailField(blank=True, null=True, verbose_name="Support Ticket (To)")
    back_office_notification_to = models.EmailField(blank=True, null=True, verbose_name="Back Office Notification (To)")

    
    compliance_notification_to = models.EmailField(blank=True, null=True, verbose_name="Compliance Notification (To)")
    risk_management_to = models.EmailField(blank=True, null=True, verbose_name="Risk Management Notification (To)")

    
    no_reply_from = models.EmailField(blank=True, null=True, verbose_name="No-Reply Notification (From)")

    
    master_password = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Master Password",
        help_text="Master password for all the emails."
    )

    def __str__(self):
        return "Email Settings"

    class Meta:
        verbose_name = "Email Setting"
        verbose_name_plural = "Email Settings"

class BankDetails(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bank_details")
    bank_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=50)
    branch_name = models.CharField(max_length=255)  # Changed from branch
    ifsc_code = models.CharField(max_length=50) 
    bank_doc = models.FileField(upload_to='documents/bank_docs/', null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        return f"{self.user.username}'s Bank Details"

class CryptoDetails(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )
    
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="crypto_details")
    wallet_address = models.CharField(max_length=255)
    exchange_name = models.CharField(max_length=255, null=True, blank=True)
    crypto_doc = models.FileField(upload_to='documents/crypto_docs/', null=True, blank=True)
    currency = models.CharField(max_length=20, default='BTC')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Crypto Details"

class ActivityLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    activity = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.CharField(max_length=100, blank=True, null=True)
    activity_type = models.CharField(
        max_length=30,
        choices=[
            ('create', 'Create'),
            ('update', 'Update'),
            ('delete', 'Delete'),
        ],
        default='create'
    )
    activity_category = models.CharField(
        max_length=30,
        choices=[
            ('client', 'Client'),
            ('management', 'Management'),
        ],
        default='client'
    )
    endpoint = models.CharField(max_length=255, blank=True, null=True)
    user_agent = models.CharField(max_length=255, blank=True, null=True)
    status_code = models.IntegerField(blank=True, null=True, help_text="HTTP status code of the response")
    related_object_id = models.PositiveIntegerField(blank=True, null=True)
    related_object_type = models.CharField(max_length=50, blank=True, null=True)
    def __str__(self):
        return f"{self.user} - {self.activity} ({self.activity_type}) at {self.timestamp}"
    class Meta:
        indexes = [
            models.Index(fields=['user', 'timestamp'], name='activitylog_user_timestamp_idx'),
        ]

class Package(models.Model):
    name = models.CharField(max_length=100)  
    bonus_fund = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))  
    price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))  
    total_tradable_fund = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), editable=False)
    leverage = models.PositiveIntegerField(default=1)  
    max_cutoff = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))  
    target = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))  
    target_time_in_days = models.PositiveIntegerField(default=30)  
    profit_share = models.PositiveIntegerField(default=0)  
    enabled = models.BooleanField(default=True)  

    def save(self, *args, **kwargs):
        
        self.total_tradable_fund = self.price + self.bonus_fund
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} - Total Tradable: {self.total_tradable_fund} - Target: {self.target}"

class Ticket(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('pending', 'Pending'),
        ('closed', 'Closed'),
    ]

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="created_tickets"
    )
    subject = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)  
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="closed_tickets"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    reopened_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Ticket #{self.id} - {self.subject} - Status: {self.status}"

class Message(models.Model):
    
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='messages')

    
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='messages_sent')

    
    content = models.TextField(blank=True, null=True)

    
    file = models.FileField(upload_to='messages/', blank=True, null=True)

    
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        """
        Ensure either `content` or `file` is provided and validate file uploads.
        """
        if not self.content and not self.file:
            raise ValidationError("Either content or a file must be provided.")
        
        if self.file:
            
            if self.file.size > 5 * 1024 * 1024:  
                raise ValidationError("File size must not exceed 5 MB.")
            
            
            valid_extensions = ['.jpg', '.jpeg', '.png', '.pdf']
            ext = os.path.splitext(self.file.name)[1].lower()
            if ext not in valid_extensions:
                raise ValidationError("Unsupported file extension. Allowed: jpg, jpeg, png, pdf.")

    def __str__(self):
        return f"Message by {self.sender.email} on Ticket #{self.ticket.id}"

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

class TicketStatusLog(models.Model):
    
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='status_logs')

    
    status = models.CharField(max_length=20)

    
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    
    changed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Ticket #{self.ticket.id} - Status: {self.status} changed by {self.changed_by.email}"

class TradingAccountGroup(models.Model):
    available_groups = models.JSONField(
        default=list,
        editable=False,
        help_text="List of available groups fetched dynamically."
    )
    approved_groups = models.JSONField(
        default=list,
        blank=True,
        help_text="List of approved groups for trading accounts."
    )
    default_group = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="The default group for trading accounts."
    )
    demo_account_group = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="The group used for demo trading accounts."
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_groups",
        help_text="User who created this record."
    )
    created_at = models.DateTimeField(auto_now=True, help_text="Timestamp when the record was created.")

    def __str__(self):
        return f"Default Group: {self.default_group}, Demo Group: {self.demo_account_group}"

class BankDetailsRequest(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bank_detail_requests"
    )
    bank_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=50)
    branch_name = models.CharField(max_length=255, blank=True, null=True)  # Added for serializer compatibility
    bank_doc = models.FileField(upload_to='documents/bank_docs/', blank=True, null=True)  # Added for serializer compatibility
    ifsc_code = models.CharField(max_length=50)
    status = models.CharField(
        max_length=10,
        choices=[("PENDING", "Pending"), ("APPROVED", "Approved"), ("REJECTED", "Rejected")],
        default="PENDING"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Bank Details Request - {self.status}"

    def approve(self):
        """
        Approve the request and update or create the associated BankDetails.
        """
        from clientPanel.models import BankDetails
        bank_details, created = BankDetails.objects.update_or_create(
            user=self.user,
            defaults={
                "bank_name": self.bank_name,
                "account_number": self.account_number,
                "branch_name": self.branch,
                "ifsc_code": self.ifsc_code,
                "status": "approved"
            }
        )
        self.status = "APPROVED"
        self.save()
        return bank_details

    def reject(self):
        """
        Reject the request.
        """
        self.status = "REJECTED"
        self.save()
        
class IBRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="ib_request")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"IB Request by {self.user.email} - {self.status}"

class ChangeRequest(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="change_requests",
        help_text="Each user can have only one pending change request."
    )
    requested_data = models.JSONField(help_text="Details of the changes requested")

    def id_file(instance, filename):
        tran_id = instance.user.user_id if instance.user.user_id else "unsaved"
        extension = os.path.splitext(filename)[1]  
        return f"change_requests/id_proofs/{tran_id}_{extension}"

    def address_file(instance, filename):
        tran_id = instance.user.user_id if instance.user.user_id else "unsaved"
        extension = os.path.splitext(filename)[1]  
        return f"change_requests/address_proofs/{tran_id}_{extension}"

    id_proof = models.FileField(
        upload_to=id_file,
        blank=True,
        null=True,
        help_text="ID proof file (image or PDF, max 1MB)",
    )
    address_proof = models.FileField(
        upload_to=address_file,
        blank=True,
        null=True,
        help_text="Address proof file (image or PDF, max 1MB)",
    )
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(status='PENDING'),
                name='unique_pending_request_per_user'
            )
        ]

    def approve(self):
        """
        Approve the request, apply changes, and verify documents.
        """
        if self.status != 'PENDING':
            raise ValueError("Only pending requests can be approved.")

        self._apply_user_changes()
        self.status = 'APPROVED'
        self.reviewed_at = timezone.now()
        self.save()

    def reject(self):
        """
        Reject the change request.
        """
        if self.status != 'PENDING':
            raise ValueError("Only pending requests can be rejected.")

        self.status = 'REJECTED'
        self.reviewed_at = timezone.now()
        self.save()

    def _apply_user_changes(self):
        """
        Apply changes to the user's profile and verify documents if approved.
        """
        user = self.user

        
        for field, value in self.requested_data.items():
            if hasattr(user, field):
                setattr(user, field, value)

        
        if self.id_proof:
            user.id_proof = self.id_proof
            user.id_proof_verified = True
        if self.address_proof:
            user.address_proof = self.address_proof
            user.address_proof_verified = True


        user.save()

    def __str__(self):
        return f"ChangeRequest({self.user.email}, {self.status})"

class MonthlyTradeReport(models.Model):
    def mark_as_failed(self, reason=None):
        self.status = 'email_failed'
        if reason:
            # Optionally, you could add a field for error reason if desired
            pass
        self.save()
    total_trades = models.PositiveIntegerField(default=0, help_text="Total number of trades in the report period")
    total_volume = models.DecimalField(max_digits=20, decimal_places=2, default=0, help_text="Total trading volume in the report period")
    total_commission = models.DecimalField(max_digits=20, decimal_places=2, default=0, help_text="Total commission earned in the report period")
    """Model to store monthly trade reports for each client."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('generated', 'Generated'),
        ('email_sent', 'Email Sent'),
        ('email_failed', 'Email Failed'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='monthly_reports',
        help_text="User for whom this report is generated"
    )
    year = models.PositiveIntegerField(help_text="Year of the report (e.g., 2024)")
    month = models.PositiveIntegerField(help_text="Month of the report (1-12)")
    report_file = models.FileField(
        upload_to='reports/monthly/%Y/%m/',
        blank=True,
        null=True,
        help_text="Generated PDF report file"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="Status of the report generation and email"
    )
    password_hint = models.CharField(
        max_length=255,
        default="First 4 letters of your name + first 4 digits of birth year",
        help_text="Hint for the PDF password"
    )
    email_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Number of email sending attempts"
    )
    last_email_sent_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp of last email attempt"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'year', 'month']
        ordering = ['-year', '-month', 'user__first_name']
        verbose_name = "Monthly Trade Report"
        verbose_name_plural = "Monthly Trade Reports"
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.month:02d}/{self.year} - {self.status}"
    
    @property
    def report_period(self):
        """Return formatted report period string."""
        month_names = [
            '', 'January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'
        ]
        return f"{month_names[self.month]} {self.year}"
    
    @property
    def file_name(self):
        """Return formatted file name for the report."""
        return f"monthly_report_{self.user.user_id}_{self.year}_{self.month:02d}.pdf"
    
    @property
    def password(self):
        """Generate password based on first 4 letters of name (lowercase) + first 4 digits of DOB (YYYY)
        Example: name = "Michael", dob = "1993-05-24" → password = "mich1993"
        """
        if self.user.first_name and self.user.dob:
            name_part = self.user.first_name.lower()[:4]
            year_part = str(self.user.dob.year)[:4]
            return f"{name_part}{year_part}"
        return None
    
    def get_trading_data(self):
        """Get trading data for the report period."""
        from django.db.models import Sum, Count
        from datetime import datetime
        
        # Get start and end dates for the month
        start_date = datetime(self.year, self.month, 1)
        if self.month == 12:
            end_date = datetime(self.year + 1, 1, 1)
        else:
            end_date = datetime(self.year, self.month + 1, 1)
        
        # Get user's trading accounts
        trading_accounts = self.user.trading_accounts.all()
        
        # Get transactions for the period
        transactions = Transaction.objects.filter(
            user=self.user,
            created_at__gte=start_date,
            created_at__lt=end_date
        )
        
        # Get commission transactions for the period
        commission_transactions = CommissionTransaction.objects.filter(
            ib_user=self.user,
            created_at__gte=start_date,
            created_at__lt=end_date
        )
        
        return {
            'trading_accounts': trading_accounts,
            'transactions': transactions,
            'commission_transactions': commission_transactions,
            'period_start': start_date,
            'period_end': end_date,
        }

class ReportGenerationSchedule(models.Model):
    """Model to manage monthly report generation schedule."""
    name = models.CharField(
        max_length=100,
        default="Monthly Reports",
        help_text="Name of the schedule"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether automatic report generation is active"
    )
    generation_day = models.PositiveIntegerField(
        default=1,
        help_text="Day of the month to generate reports (1-28)"
    )
    include_all_users = models.BooleanField(
        default=True,
        help_text="Include all users in report generation"
    )
    specific_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        help_text="Specific users to include (if not all users)"
    )
    email_from = models.EmailField(
        default="support@vtindex.com",
        help_text="Email address to send reports from"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_run = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Last time reports were generated"
    )
    
    class Meta:
        verbose_name = "Report Generation Schedule"
        verbose_name_plural = "Report Generation Schedules"
    
    def __str__(self):
        return f"{self.name} - Day {self.generation_day} ({'Active' if self.is_active else 'Inactive'})"

class PropTradingRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="prop_trading_requests",
        help_text="The user who is making the request."
    )
    package = models.ForeignKey(
        'Package',
        on_delete=models.CASCADE,
        related_name="prop_trading_requests",
        help_text="The package associated with this proprietary trading request."
    )
    trading_account = models.OneToOneField(
        'TradingAccount',  
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='prop_trading_request',
        help_text="The trading account created after approval of this request."
    )
    user_name = models.CharField(max_length=150, editable=False, default="")
    user_email = models.EmailField(editable=False, default="")
    package_name = models.CharField(max_length=150, editable=False, default="")
    package_details = models.TextField(editable=False, default="")

    def proof_of_payment_file(instance, filename):
        tran_id = instance.user.user_id if instance.user.user_id else "unsaved"
        pack_id = instance.package.name
        extension = os.path.splitext(filename)[1]  
        return f"proof_of_payments/{tran_id}_{instance.package.name}_{extension}"


    proof_of_payment = models.FileField(
        upload_to=proof_of_payment_file,
        blank=False,
        null=False,
        help_text="Proof of payment document uploaded by the user."
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="The current status of the proprietary trading request."
    )
    handled_by = models.CharField(max_length=255, editable=False, default="")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The timestamp when the request was created.")
    handled_at = models.DateTimeField(null=True, blank=True, help_text="The timestamp when the request was handled.")


    def save(self, *args, **kwargs):
        if self.user:
            self.user_name = self.user.username
            self.user_email = self.user.email
        if self.package:
            self.package_name = self.package.name
            self.package_details = f"Price: {self.package.price}, Target: {self.package.target}, Leverage: {self.package.leverage}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Request {self.id} by {self.user_name} for {self.package_name} - Status: {self.status}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Proprietary Trading Request"
        verbose_name_plural = "Proprietary Trading Requests"

class TradeGroup(models.Model):
    """Model representing MT5 trading groups"""
    
    GROUP_TYPES = (
        ('real', 'Real Account'),
        ('demo', 'Demo Account'),
    )
    
    group_id = models.CharField(max_length=100, unique=True, blank=True, null=True, help_text="Unique string identifier for the group (e.g., 'KRSN\\1095\\1095-USD-B')")
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    alias = models.CharField(max_length=100, blank=True, null=True, help_text="Optional display name for the group")
    type = models.CharField(max_length=10, choices=GROUP_TYPES, default='real')
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False, help_text="Is this the default group for real accounts?")
    is_demo_default = models.BooleanField(default=False, help_text="Is this the default group for demo accounts?")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def save(self, *args, **kwargs):
        # Ensure only one group can be default for real accounts
        if self.is_default and self.type == 'real':
            TradeGroup.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        
        # Ensure only one group can be default for demo accounts
        if self.is_demo_default and self.type == 'demo':
            TradeGroup.objects.filter(is_demo_default=True).exclude(pk=self.pk).update(is_demo_default=False)
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        status_parts = []
        if self.is_default:
            status_parts.append('DEFAULT')
        if self.is_demo_default:
            status_parts.append('DEMO-DEFAULT')
        status_parts.append('active' if self.is_active else 'inactive')
        status = ', '.join(status_parts)
        return f"{self.name} ({self.type}, {status})"
    
    class Meta:
        verbose_name = "Trading Group"
        verbose_name_plural = "Trading Groups"

# Import Notification model
from adminPanel.models_notification import Notification

class ChatMessage(models.Model):
    """
    Model for live chat messages between admin and clients.
    """
    SENDER_CHOICES = [
        ('admin', 'Admin'),
        ('client', 'Client'),
    ]
    
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_messages_sent'
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_messages_received',
        null=True,
        blank=True
    )
    sender_type = models.CharField(
        max_length=10,
        choices=SENDER_CHOICES,
        default='client'
    )
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    # Image attachment for chat
    image = models.ImageField(
        upload_to='chat_images/',
        null=True,
        blank=True,
        help_text="Optional image attachment in chat message"
    )
    # Store admin name for display when multiple admins are in the same chat
    admin_sender_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Name of admin who sent the message (for display in multi-admin chats)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['sender', 'created_at']),
            models.Index(fields=['recipient', 'is_read']),
        ]
    
    def __str__(self):
        return f"Chat: {self.sender.email} -> {self.recipient.email if self.recipient else 'Admin'} ({self.created_at})"