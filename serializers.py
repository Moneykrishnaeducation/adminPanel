from rest_framework import serializers
from adminPanel.mt5.services import MT5ManagerActions
from .models import *
from adminPanel.mt5.models import ServerSetting
from decimal import Decimal
import decimal

class CommissionTransactionSerializer(serializers.ModelSerializer):
    ib_user = serializers.SerializerMethodField()
    client_user_first_name = serializers.CharField(source='client_user.first_name', read_only=True)
    client_user_last_name = serializers.CharField(source='client_user.last_name', read_only=True)
    client_user_email = serializers.EmailField(source='client_user.email', read_only=True)
    client_trading_account = serializers.CharField(source='client_trading_account.account_id', read_only=True)
    ib_user_email = serializers.EmailField(source='ib_user.user.email', read_only=True)  
    commissioning_profile_name = serializers.CharField(source='ib_user.commissioning_profile.name', read_only=True)  
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, source='commission_to_ib', read_only=True)
    commission_percentage = serializers.SerializerMethodField(read_only=True)
    
    def get_ib_user(self, obj):
        """Return IB user's full name with email"""
        return f"{obj.ib_user.first_name} {obj.ib_user.last_name} ({obj.ib_user.email})"

    def get_commission_percentage(self, obj):
        if obj.ib_level == 1:
            return obj.ib_user.commissioning_profile.level_1_percentage
        elif obj.ib_level == 2:
            return obj.ib_user.commissioning_profile.level_2_percentage
        elif obj.ib_level == 3:
            return obj.ib_user.commissioning_profile.level_3_percentage
        return None

    class Meta:
        model = CommissionTransaction
        fields = [
            'id', 'ib_user', 'ib_user_email', 'client_user_first_name', 'client_user_last_name', 'client_user_email', 'client_trading_account',
            'position_id', 'deal_ticket', 'amount', 'commission_percentage', 'ib_level', 'total_commission',
            'commissioning_profile_name', 'position_type', 'position_symbol', 'position_direction', 
            'lot_size', 'profit', 'mt5_close_time', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'ib_user_email', 'commissioning_profile_name', 'amount', 'commission_percentage', 'client_user_email']

class UserSerializer(serializers.ModelSerializer):

    user_verified = serializers.ReadOnlyField()
    commission_profile_name = serializers.SerializerMethodField()
    total_clients = serializers.SerializerMethodField()
    profile_image_url = serializers.SerializerMethodField()
    created_by_email = serializers.SerializerMethodField()
    parent_ib_email = serializers.SerializerMethodField()
    available_commission = serializers.SerializerMethodField()

    def get_created_by_email(self, obj):
        return obj.created_by.email if obj.created_by else None

    def get_parent_ib_email(self, obj):
        return obj.parent_ib.email if obj.parent_ib else None

    def get_commission_profile_name(self, obj):
        if obj.commissioning_profile:
            return obj.commissioning_profile.name
        return None

    def get_total_clients(self, obj):
        # Count users where this IB is parent_ib
        return obj.clients.count() if hasattr(obj, 'clients') else 0
    
    def get_available_commission(self, obj):
        """Get the withdrawable commission balance for IB users"""
        if not obj.IB_status:
            return 0
        
        # Calculate withdrawable balance using the same logic as statistics endpoint
        try:
            total_earnings = float(getattr(obj, 'total_earnings', 0) or 0)
        except Exception:
            try:
                total_earnings = float(getattr(obj, 'earnings', 0) or 0)
            except Exception:
                total_earnings = 0.0

        try:
            total_withdrawals = float(getattr(obj, 'total_commission_withdrawals', 0) or 0)
        except Exception:
            total_withdrawals = 0.0

        # Withdrawable balance = total earnings - total withdrawals
        withdrawable_balance = total_earnings - total_withdrawals
        return withdrawable_balance

    def get_profile_image_url(self, obj):
        request = self.context.get('request')
        if obj.profile_pic and hasattr(obj.profile_pic, 'url'):
            url = obj.profile_pic.url
            if request is not None:
                return request.build_absolute_uri(url)
            return url
        return None

    class Meta:
        model = CustomUser
        fields = '__all__'
        extra_kwargs = {
            'password': {'write_only': True},
            'last_name': {'required': False, 'allow_blank': True},
            'dob': {'required': False, 'allow_null': True},
            'address': {'required': False, 'allow_blank': True},
            'phone_number': {'required': False, 'allow_blank': True},  
            'id_proof': {'required': False},  
            'address_proof': {'required': False}  
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Always include user_id in the output
        if hasattr(instance, 'user_id'):
            data['user_id'] = instance.user_id
        return data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['created_by_email'] = self.get_created_by_email(instance)
        data['parent_ib_email'] = self.get_parent_ib_email(instance)
        return data

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = self.Meta.model(**validated_data)
        if password:
            user.set_password(password) 
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance

class UserInfoSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    
    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'profile_pic', 'name']
    
    def get_name(self, obj):
        if obj.first_name and obj.last_name:
            return f"{obj.first_name} {obj.last_name}"
        elif obj.first_name:
            return obj.first_name
        elif obj.last_name:
            return obj.last_name
        else:
            return obj.username

class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            'user_id',  
            'username',  
            'email', 
            'date_joined',  
            'country', 
            'IB_status', 
            'manager_admin_status', 
            'is_active',  
            'user_verified',  
            'address_proof_verified',  
            'id_proof_verified',  
            'profile_pic',
            'Access_Key'  # Add Access_Key to be returned in user list
        ]

class TransactionSerializer(serializers.ModelSerializer):
    # Allow admin_comment to be written to as well
    admin_comment = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    
    user_id = serializers.IntegerField(source='user.user_id', read_only=True)
    username = serializers.CharField(source='trading_account.user.username', read_only=True)
    it_username=serializers.CharField(source='from_account.user.username', read_only=True)
    it_useremail=serializers.CharField(source='from_account.user.email', read_only=True)
    email = serializers.EmailField(source='trading_account.user.email', read_only=True)
    trading_account_id = serializers.CharField(source='trading_account.account_id', read_only=True)
    trading_account_name = serializers.CharField(source='trading_account.account_name', read_only=True)
    trading_account_balance = serializers.DecimalField(
        source='trading_account.balance', max_digits=12, decimal_places=2, read_only=True
    )
    trading_account_leverage = serializers.IntegerField(source='trading_account.leverage', read_only=True)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True, default=None)
    approved_by_email = serializers.EmailField(source='approved_by.email', read_only=True, default=None)
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    document_url = serializers.SerializerMethodField()
    source = serializers.CharField(read_only=True)
    from_account = serializers.CharField(source='from_account.account_id', read_only=True)
    to_account = serializers.CharField(source='to_account.account_id', read_only=True)
    from_account_name = serializers.CharField(source='from_account.account_name', read_only=True, default=None)
    to_account_name = serializers.CharField(source='to_account.account_name', read_only=True, default=None)
    
    class Meta:
        model = Transaction
        fields = [
            'id',
            'user_id',
            'username',
            'email',
            'trading_account_id',
            'trading_account_name',
            'trading_account_balance',
            'trading_account_leverage',
            'transaction_type',
            'transaction_type_display',
            'amount',
            'description',
            'source',
            'status',
            'created_at',
            'approved_by_username',
            'approved_by_email',
            'approved_at',
            'payout_to',
            'external_account',
            'from_account',
            'to_account',
            'from_account_name',
            'to_account_name',
            'document',
            'document_url',
            'it_username',
            'it_useremail',
            'admin_comment',
        ]
        read_only_fields = [
            'id', 
            'user_id', 
            'username', 
            'email', 
            'trading_account_id', 
            'trading_account_name', 
            'trading_account_balance',
            'trading_account_leverage',
            'approved_by_username', 
            'approved_by_email', 
            'created_at',            
            'from_account',
            'to_account',  
            'from_account_name',
            'to_account_name',
            'it_username',
            'it_useremail',
            
        ]
    def get_attachments(self, obj):
        request = self.context.get('request')
        # If you have a related field for multiple documents, use it here. Example: obj.documents.all()
        if hasattr(obj, 'documents') and hasattr(obj.documents, 'all'):
            return [
                {
                    'url': request.build_absolute_uri(doc.file.url) if request else doc.file.url,
                    'name': getattr(doc, 'name', getattr(doc, 'filename', 'Document'))
                }
                for doc in obj.documents.all() if hasattr(doc, 'file') and doc.file
            ]
        # Fallback: single document
        if hasattr(obj, 'document') and obj.document:
            url = request.build_absolute_uri(obj.document.url) if request else obj.document.url
            return [{
                'url': url,
                'name': getattr(obj.document, 'name', getattr(obj.document, 'filename', 'Document'))
            }]
        return []

    def get_document_url(self, obj):
        """
        Returns the absolute URL for the attached document if it exists.
        """
        request = self.context.get('request')
        if obj.document and request:
            return request.build_absolute_uri(obj.document.url)
        return None
   
class IBUserSerializer(serializers.ModelSerializer):
    userName = serializers.SerializerMethodField()
    commissioningProfile = serializers.CharField(source='commissioning_profile.name')
    totalClients = serializers.IntegerField(source='direct_client_count')  

    class Meta:
        model = CustomUser
        fields = [
            'user_id',               
            'userName',              
            'commissioningProfile',  
            'totalClients',          
        ]

    def get_userName(self, obj):
        return f"{obj.first_name} {obj.last_name}"
    
class CommissioningProfileSerializer(serializers.ModelSerializer):
    # Accept legacy 'commission' field from frontend for backward compatibility
    commission = serializers.DecimalField(max_digits=5, decimal_places=2, write_only=True, required=False)
    # Accept 'level_percentages' field for dynamic percentage levels (write-only since model field was removed)
    level_percentages = serializers.CharField(write_only=True, required=False)
    # Accept 'level_amounts_usd_per_lot' field for dynamic USD per lot levels
    level_amounts_usd_per_lot = serializers.CharField(write_only=True, required=False)
    # Accept 'level_amounts' for frontend compatibility
    level_amounts = serializers.CharField(write_only=True, required=False)
    # Accept group-specific commissions: list of {group_name, amounts} where amounts is comma-separated or array
    group_commissions = serializers.ListField(write_only=True, required=False)
    # NEW: Accept dynamic levels configuration
    levels = serializers.ListField(write_only=True, required=False, help_text="List of level objects with level, percentage, and/or usd_per_lot")
    
    class Meta:
        model = CommissioningProfile
        fields = ['id', 'name', 'level_1_percentage', 'level_2_percentage', 'level_3_percentage', 
                 'commission_percentage', 'commission', 'level_percentages',
                 'level_1_usd_per_lot', 'level_2_usd_per_lot', 'level_3_usd_per_lot',
                 'level_amounts_usd_per_lot', 'level_amounts', 'use_percentage_based', 
                 'approved_groups', 'group_commissions', 'dynamic_levels', 'levels']

    def create(self, validated_data):
        """Custom create method to handle special fields that don't exist in the model."""
        # Remove write-only fields that don't exist in the model
        level_percentages = validated_data.pop('level_percentages', None)
        level_amounts = validated_data.pop('level_amounts', None)
        commission = validated_data.pop('commission', None)
        levels = validated_data.pop('levels', None)
        
        # Process levels into dynamic_levels
        if levels:
            dynamic_levels = []
            for level_data in levels:
                if isinstance(level_data, dict):
                    level_obj = {}
                    if 'level' in level_data:
                        level_obj['level'] = int(level_data['level'])
                    if 'percentage' in level_data:
                        level_obj['percentage'] = float(level_data['percentage'])
                    if 'usd_per_lot' in level_data:
                        level_obj['usd_per_lot'] = float(level_data['usd_per_lot'])
                    if level_obj:
                        dynamic_levels.append(level_obj)
            validated_data['dynamic_levels'] = dynamic_levels
        
        # Extract group_commissions if present and create model after main instance
        group_commissions = validated_data.pop('group_commissions', None)
        instance = super().create(validated_data)

        # Persist group-specific commissions
        if group_commissions:
            for item in group_commissions:
                # item may be dict or string; expect dict with group_name and amounts
                if isinstance(item, dict):
                    group_name = item.get('group_name')
                    amounts_raw = item.get('amounts')
                else:
                    # If frontend sends a CSV like "group_name:50,20,10" ignore for now
                    continue

                if not group_name or not amounts_raw:
                    continue

                # Normalize amounts to list
                if isinstance(amounts_raw, str):
                    amounts = [a.strip() for a in amounts_raw.split(',') if a.strip()]
                elif isinstance(amounts_raw, list):
                    amounts = [str(a) for a in amounts_raw]
                else:
                    amounts = []

                # Convert to numeric values
                try:
                    amounts_num = [float(a) for a in amounts]
                except Exception:
                    amounts_num = []

                if amounts_num:
                    CommissioningProfileGroup.objects.update_or_create(
                        profile=instance,
                        group_name=group_name,
                        defaults={'amounts': amounts_num}
                    )

        return instance

    def update(self, instance, validated_data):
        """Custom update method to handle special fields that don't exist in the model."""
        # Remove write-only fields that don't exist in the model
        level_percentages = validated_data.pop('level_percentages', None)
        level_amounts = validated_data.pop('level_amounts', None)
        commission = validated_data.pop('commission', None)
        levels = validated_data.pop('levels', None)
        
        # Process levels into dynamic_levels
        if levels is not None:
            dynamic_levels = []
            for level_data in levels:
                if isinstance(level_data, dict):
                    level_obj = {}
                    if 'level' in level_data:
                        level_obj['level'] = int(level_data['level'])
                    if 'percentage' in level_data:
                        level_obj['percentage'] = float(level_data['percentage'])
                    if 'usd_per_lot' in level_data:
                        level_obj['usd_per_lot'] = float(level_data['usd_per_lot'])
                    if level_obj:
                        dynamic_levels.append(level_obj)
            validated_data['dynamic_levels'] = dynamic_levels
        
        group_commissions = validated_data.pop('group_commissions', None)
        instance = super().update(instance, validated_data)

        # Persist group-specific commissions
        if group_commissions is not None:
            # Replace existing entries for this profile
            CommissioningProfileGroup.objects.filter(profile=instance).delete()
            for item in group_commissions:
                if isinstance(item, dict):
                    group_name = item.get('group_name')
                    amounts_raw = item.get('amounts')
                else:
                    continue

                if not group_name or not amounts_raw:
                    continue

                if isinstance(amounts_raw, str):
                    amounts = [a.strip() for a in amounts_raw.split(',') if a.strip()]
                elif isinstance(amounts_raw, list):
                    amounts = [str(a) for a in amounts_raw]
                else:
                    amounts = []

                try:
                    amounts_num = [float(a) for a in amounts]
                except Exception:
                    amounts_num = []

                if amounts_num:
                    CommissioningProfileGroup.objects.create(
                        profile=instance,
                        group_name=group_name,
                        amounts=amounts_num
                    )

        return instance

    def validate(self, data):
        use_percentage_based = data.get('use_percentage_based', False)
        
        # NEW: Handle dynamic levels field
        if 'levels' in data:
            levels = data.get('levels', [])
            
            # Validate each level configuration
            for level_data in levels:
                if not isinstance(level_data, dict):
                    raise serializers.ValidationError("Each level must be a dictionary with 'level' and 'percentage' or 'usd_per_lot'.")
                
                if 'level' not in level_data:
                    raise serializers.ValidationError("Each level must have a 'level' number.")
                
                try:
                    level_num = int(level_data['level'])
                    if level_num < 1:
                        raise serializers.ValidationError(f"Level number must be positive (got {level_num}).")
                except (ValueError, TypeError):
                    raise serializers.ValidationError("Level number must be a valid integer.")
                
                # Check that at least percentage or usd_per_lot is specified
                has_percentage = 'percentage' in level_data
                has_usd = 'usd_per_lot' in level_data
                
                if not has_percentage and not has_usd:
                    raise serializers.ValidationError(f"Level {level_num} must have either 'percentage' or 'usd_per_lot'.")
                
                # Validate percentage if present
                if has_percentage:
                    try:
                        percentage = Decimal(str(level_data['percentage']))
                        if percentage < 0 or percentage > 100:
                            raise serializers.ValidationError(f"Level {level_num} percentage must be between 0 and 100.")
                    except (ValueError, decimal.InvalidOperation):
                        raise serializers.ValidationError(f"Level {level_num} has invalid percentage value.")
                
                # Validate usd_per_lot if present
                if has_usd:
                    try:
                        usd_amount = Decimal(str(level_data['usd_per_lot']))
                        if usd_amount < 0:
                            raise serializers.ValidationError(f"Level {level_num} USD per lot cannot be negative.")
                        if usd_amount > Decimal('1000'):
                            raise serializers.ValidationError(f"Level {level_num} USD per lot exceeds maximum of $1000.")
                    except (ValueError, decimal.InvalidOperation):
                        raise serializers.ValidationError(f"Level {level_num} has invalid usd_per_lot value.")
            
            # Check total percentage if percentage-based
            if use_percentage_based or any('percentage' in lc for lc in levels):
                total_percentage = Decimal('0')
                for level_data in levels:
                    if 'percentage' in level_data:
                        try:
                            total_percentage += Decimal(str(level_data['percentage']))
                        except (ValueError, decimal.InvalidOperation):
                            pass
                
                if total_percentage > Decimal('100'):
                    raise serializers.ValidationError(f"Total commission percentage ({total_percentage}%) cannot exceed 100%.")
            
            # Skip legacy validation if using dynamic levels
            return data
        
        # LEGACY VALIDATION BELOW
        if use_percentage_based:
            # Validate percentage-based commission
            # Priority: level_percentages > commission > individual level fields
            if 'level_percentages' in data:
                # New dynamic percentage levels format
                level_percentages_str = data.pop('level_percentages')
                try:
                    percentages = [Decimal(p.strip()) for p in level_percentages_str.split(',') if p.strip()]
                    total = sum(percentages)
                    
                    if total > Decimal('100'):
                        raise serializers.ValidationError(f"Total commission percentage ({total}%) cannot exceed 100%.")
                    
                    # Set the old fields for backward compatibility
                    data['level_1_percentage'] = percentages[0] if len(percentages) > 0 else Decimal('0')
                    data['level_2_percentage'] = percentages[1] if len(percentages) > 1 else Decimal('0')
                    data['level_3_percentage'] = percentages[2] if len(percentages) > 2 else Decimal('0')
                    data['commission_percentage'] = data['level_1_percentage']
                    
                except (ValueError, decimal.InvalidOperation):
                    raise serializers.ValidationError("Invalid format for level percentages. Use comma-separated numbers (e.g., '50,20,20,10').")
                    
            elif 'commission' in data:
                # Legacy single commission field
                commission_value = data.pop('commission')
                data['level_1_percentage'] = commission_value
                data['commission_percentage'] = commission_value
                if 'level_2_percentage' not in data:
                    data['level_2_percentage'] = 0
                if 'level_3_percentage' not in data:
                    data['level_3_percentage'] = 0
            else:
                # Validate individual level fields
                level_1 = data.get('level_1_percentage', 0)
                level_2 = data.get('level_2_percentage', 0)
                level_3 = data.get('level_3_percentage', 0)
                total_percentage = level_1 + level_2 + level_3
                
                if total_percentage > 100:
                    raise serializers.ValidationError("Total percentage of all levels cannot exceed 100%.")
        else:
            # Validate USD per lot commission
            # Priority: level_amounts_usd_per_lot > level_amounts > individual level fields
            if 'level_amounts_usd_per_lot' in data or 'level_amounts' in data:
                # New dynamic USD per lot levels format
                level_amounts_str = data.pop('level_amounts_usd_per_lot', None) or data.pop('level_amounts', None)
                try:
                    amounts = [Decimal(a.strip()) for a in level_amounts_str.split(',') if a.strip()]
                    
                    # Validate amounts
                    for i, amount in enumerate(amounts, 1):
                        if amount < 0:
                            raise serializers.ValidationError(f"Level {i} amount cannot be negative.")
                        if amount > Decimal('1000'):
                            raise serializers.ValidationError(f"Level {i} amount ({amount}) exceeds maximum of $1000 per lot.")
                    
                    # Set the level_amounts_usd_per_lot field
                    data['level_amounts_usd_per_lot'] = level_amounts_str
                    
                    # Also set the old fields for backward compatibility
                    data['level_1_usd_per_lot'] = amounts[0] if len(amounts) > 0 else Decimal('0')
                    data['level_2_usd_per_lot'] = amounts[1] if len(amounts) > 1 else Decimal('0')
                    data['level_3_usd_per_lot'] = amounts[2] if len(amounts) > 2 else Decimal('0')
                    
                except (ValueError, decimal.InvalidOperation):
                    raise serializers.ValidationError("Invalid format for level amounts. Use comma-separated numbers (e.g., '50,20,15,10').")
            else:
                # Validate individual USD per lot level fields
                level_1 = data.get('level_1_usd_per_lot', 0)
                level_2 = data.get('level_2_usd_per_lot', 0)
                level_3 = data.get('level_3_usd_per_lot', 0)
                
                for i, amount in enumerate([level_1, level_2, level_3], 1):
                    if amount < 0:
                        raise serializers.ValidationError(f"Level {i} amount cannot be negative.")
                    if amount > Decimal('1000'):
                        raise serializers.ValidationError(f"Level {i} amount ({amount}) exceeds maximum of $1000 per lot.")
        
        return data

class CommissioningProfileSerializerFor(serializers.ModelSerializer):
    profileName = serializers.CharField(source='name')
    profileId = serializers.CharField(source='id')
    
    # Percentage fields
    level1Percentage = serializers.DecimalField(source='level_1_percentage', max_digits=5, decimal_places=2)
    level2Percentage = serializers.DecimalField(source='level_2_percentage', max_digits=5, decimal_places=2)
    level3Percentage = serializers.DecimalField(source='level_3_percentage', max_digits=5, decimal_places=2)
    level_percentages = serializers.SerializerMethodField()
    
    # USD per lot fields
    level1UsdPerLot = serializers.DecimalField(source='level_1_usd_per_lot', max_digits=10, decimal_places=2)
    level2UsdPerLot = serializers.DecimalField(source='level_2_usd_per_lot', max_digits=10, decimal_places=2)
    level3UsdPerLot = serializers.DecimalField(source='level_3_usd_per_lot', max_digits=10, decimal_places=2)
    level_amounts_usd_per_lot = serializers.CharField(read_only=True)
    
    # Commission type and groups
    usePercentageBased = serializers.BooleanField(source='use_percentage_based')
    approvedGroups = serializers.JSONField(source='approved_groups')
    group_commissions = serializers.SerializerMethodField()
    
    # Dynamic fields based on commission type
    commissionType = serializers.SerializerMethodField()
    displayText = serializers.SerializerMethodField()

    def get_level_percentages(self, obj):
        """Return level percentages as comma-separated string for backward compatibility."""
        percentages = obj.get_level_percentages_list()
        return ','.join([str(p) for p in percentages]) if percentages else ""

    def get_commissionType(self, obj):
        return 'percentage' if obj.use_percentage_based else 'usd_per_lot'
    
    def get_displayText(self, obj):
        if obj.use_percentage_based:
            percentages = obj.get_level_percentages_list()
            if percentages:
                levels_str = ', '.join([f"L{i+1}: {p}%" for i, p in enumerate(percentages)])
                total = sum(percentages)
                return f"{levels_str} (Total: {total}%)"
            else:
                total = obj.level_1_percentage + obj.level_2_percentage + obj.level_3_percentage
                return f"L1: {obj.level_1_percentage}%, L2: {obj.level_2_percentage}%, L3: {obj.level_3_percentage}% (Total: {total}%)"
        else:
            if obj.level_amounts_usd_per_lot:
                amounts = obj.get_level_amounts_list()
                levels_str = ', '.join([f"L{i+1}: ${a}" for i, a in enumerate(amounts)])
                total = sum(amounts)
                return f"{levels_str} per lot (Max: ${total})"
            else:
                total = obj.level_1_usd_per_lot + obj.level_2_usd_per_lot + obj.level_3_usd_per_lot
                return f"L1: ${obj.level_1_usd_per_lot}, L2: ${obj.level_2_usd_per_lot}, L3: ${obj.level_3_usd_per_lot} per lot (Max: ${total})"

    class Meta:
        model = CommissioningProfile
        fields = ['profileName', 'profileId', 'level1Percentage', 'level2Percentage', 'level3Percentage', 
                 'level_percentages', 'level1UsdPerLot', 'level2UsdPerLot', 'level3UsdPerLot', 
                 'level_amounts_usd_per_lot', 'usePercentageBased', 'approvedGroups', 'group_commissions',
                 'commissionType', 'displayText']

    def get_group_commissions(self, obj):
        result = []
        for gc in getattr(obj, 'group_commissions', []).all():
            amounts = gc.get_amounts_list()
            result.append({
                'group_name': gc.group_name,
                'amounts_csv': ','.join([str(a) for a in amounts]),
                'amounts': [float(a) for a in amounts]
            })
        return result

class UserVerificationStatusSerializer(serializers.ModelSerializer):
    id_proof_status = serializers.SerializerMethodField()
    address_proof_status = serializers.SerializerMethodField()
    
    class Meta:
        model = CustomUser
        fields = ['user_verified', 'id_proof_status', 'address_proof_status']
    
    def get_id_proof_status(self, obj):
        if obj.id_proof_verified:
            return 'verified'
        elif obj.id_proof:
            return 'uploaded'
        else:
            return 'not_uploaded'
    
    def get_address_proof_status(self, obj):
        if obj.address_proof_verified:
            return 'verified'
        elif obj.address_proof:
            return 'uploaded'
        else:
            return 'not_uploaded'

class TradingAccountSerializer(serializers.ModelSerializer):
    
    user_id = serializers.CharField(source='user.user_id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    reg_date = serializers.DateTimeField(source='user.date_joined', read_only=True)
    country = serializers.CharField(source='user.country', default="", read_only=True)
    mam_master_account_id = serializers.SerializerMethodField()
    mam_master_account_name = serializers.SerializerMethodField()
    mam_master_account_email = serializers.SerializerMethodField()

    package_name = serializers.SerializerMethodField()
    package_price = serializers.SerializerMethodField()
    package_target = serializers.SerializerMethodField()
    package_leverage = serializers.SerializerMethodField()

    approved_by = serializers.CharField(source='approved_by.username', default=None, read_only=True)
    approved_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', default=None, read_only=True)
    start_date = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', default=None, read_only=True)
    end_date = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', default=None, read_only=True)
    profit = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    
    class Meta:
        model = TradingAccount
        fields = '__all__'
        
    def get_balance(self, obj):
        # Temporarily disable MT5 calls for debugging
        # try:               
        #     balance = MT5ManagerActions().get_balance(int(obj.account_id))
        #     if balance is not None:
        #         obj.balance = balance
        #         obj.save()
        #         return balance
        # except Exception as e:
        #     print(f"MT5 balance fetch failed for account {obj.account_id}: {e}")
        
        # Return the stored balance if MT5 fetch fails
        return float(obj.balance) if obj.balance else 0.0

    def get_mam_master_account_name(self, obj):
        """Retrieve the name of the associated MAM master account."""
        if obj.mam_master_account and obj.mam_master_account.user:
            return obj.mam_master_account.user.username
        return None

    def get_mam_master_account_email(self, obj):
        """Retrieve the email of the associated MAM master account."""
        if obj.mam_master_account and obj.mam_master_account.user:
            return obj.mam_master_account.user.email
        return None

    def get_mam_master_account_id(self, obj):
        """Retrieve the ID of the associated MAM master account."""
        if obj.mam_master_account:
            return obj.mam_master_account.account_id
        return None

    def get_profit(self, obj):
        # Temporarily disable MT5 calls for debugging  
        # try:
        #     profit = MT5ManagerActions().total_account_profit(int(obj.account_id))
        #     return profit if profit is not None else 0.0
        # except Exception as e:
        #     print(f"MT5 profit fetch failed for account {obj.account_id}: {e}")
        return 0.0

    def get_package_name(self, obj):
        """Retrieve the package name for proprietary accounts."""
        if obj.account_type == 'prop' and obj.package:
            return obj.package.name
        return None

    def get_package_price(self, obj):
        """Retrieve the package price for proprietary accounts."""
        if obj.account_type == 'prop' and obj.package:
            return obj.package.price
        return None

    def get_package_target(self, obj):
        """Retrieve the package target for proprietary accounts."""
        if obj.account_type == 'prop' and obj.package:
            return obj.package.target
        return None

    def get_package_leverage(self, obj):
        """Retrieve the package leverage for proprietary accounts."""
        if obj.account_type == 'prop' and obj.package:
            return obj.package.leverage
        return None
    
class DemoAccountSerializer(serializers.ModelSerializer):
    user_id = serializers.CharField(source='user.user_id')
    username = serializers.CharField(source='user.username')
    email = serializers.EmailField(source='user.email')
    reg_date = serializers.DateTimeField(source='user.date_joined')
    country = serializers.CharField(source='user.country')
    account_id = serializers.CharField()
    account_name = serializers.CharField()
    leverage = serializers.CharField()
    balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    is_enabled = serializers.BooleanField()  
    is_algo_enabled = serializers.BooleanField()  

    class Meta:
        model = DemoAccount
        fields = [
            'user_id', 'username', 'email', 'reg_date', 'country',
            'account_id', 'account_name', 'leverage', 'balance', 
            'is_enabled', 'is_algo_enabled', 'created_at'
        ]

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'address', 'dob']
        
# Bank and Crypto serializers moved to clientPanel.serializers
        
class PromoteDemoteUserSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=True)

    def validate_user_id(self, value):
        
        try:
            user = CustomUser.objects.get(user_id=value)
        except CustomUser.DoesNotExist:
            raise serializers.ValidationError("User not found.")
        return value
    
class UserStatusSerializer(serializers.ModelSerializer):
    status = serializers.CharField(source='manager_admin_status')  
    available_levels = serializers.SerializerMethodField()  

    class Meta:
        model = CustomUser
        fields = ['status', 'available_levels']

    def get_available_levels(self, obj):
        
        all_levels = [
            'None',
            'Admin Level 1', 'Admin Level 2',
            'Manager Level 1', 'Manager Level 2', 'Manager Level 3'
        ]

        
        available_levels = [level for level in all_levels if level != obj.manager_admin_status]

        return available_levels

class CreateTradingAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradingAccount
        fields = ['id', 'user', 'account_id', 'account_name', 'leverage', 'balance', 'created_at']

class CreateDemoAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = DemoAccount
        fields = ['id', 'user', 'account_id', 'account_name', 'leverage', 'balance', 'created_at']
          
class InternalTransferSerializer(serializers.ModelSerializer):
    from_account_id = serializers.CharField(write_only=True)
    to_account_id = serializers.CharField(write_only=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        model = Transaction
        fields = ['from_account_id', 'to_account_id', 'amount']

    def validate(self, data):
        from_account_id = data['from_account_id']
        to_account_id = data['to_account_id']

        
        if from_account_id == to_account_id:
            raise serializers.ValidationError("From and to accounts must be different for an internal transfer.")

        
        from_account = TradingAccount.objects.get(account_id=from_account_id)
        to_account = TradingAccount.objects.get(account_id=to_account_id)
        
        if from_account.balance < data['amount']:
            raise serializers.ValidationError("Insufficient balance in the from account.")
        
        data['from_account'] = from_account
        data['to_account'] = to_account

        return data
    
class PackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Package
        fields = '__all__'
        
class PropTradingRequestSerializer(serializers.ModelSerializer):
    proof_of_payment = serializers.SerializerMethodField()

    def get_proof_of_payment(self, obj):
        if obj.proof_of_payment:
            return obj.proof_of_payment.url  
        return None

    class Meta:
        model = PropTradingRequest
        fields = '__all__'
        
class TicketSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="created_by.username", read_only=True)

    user_id = serializers.SerializerMethodField()

    def get_user_id(self, obj):
        # Always return as string, and ensure it's the 7-digit client id
        if obj.created_by and obj.created_by.user_id:
            return str(obj.created_by.user_id)
        return "-"

    class Meta:
        model = Ticket
        fields = '__all__'
        read_only_fields = ['created_by', 'created_at', 'updated_at', 'closed_by', 'closed_at', 'reopened_at']
        # Add user_id to the output fields if not already present
        extra_fields = ['user_id']
    
    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['user_id'] = self.get_user_id(instance)
        return rep

class TicketStatusLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketStatusLog
        fields = '__all__'


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source='sender.username', read_only=True)

    # Accept uploaded file on write, but return relative file path on read
    file = serializers.FileField(required=False, allow_null=True)

    class Meta:
        model = Message
        fields = ['id', 'ticket', 'sender', 'sender_name', 'content', 'file', 'created_at']
        read_only_fields = ['created_at']

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        request = self.context.get('request')
        if getattr(instance, 'file', None):
            try:
                url = instance.file.url
                if request is not None:
                    rep['file'] = request.build_absolute_uri(url)
                else:
                    rep['file'] = url
            except Exception:
                rep['file'] = None
        else:
            rep['file'] = None
        return rep

    def validate(self, data):
        # During create/update `file` may be an UploadedFile in data or `content` may be present
        if not data.get('content') and not data.get('file'):
            raise serializers.ValidationError("Either content or a file must be provided.")
        return data


class TicketWithMessagesSerializer(TicketSerializer):
    """Extend ticket representation with related messages.

    We avoid modifying `Meta.fields` because the base serializer may use
    `'__all__'` (a string). Instead we append `messages` in
    `to_representation` so file URLs are exposed safely.
    """

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['messages'] = MessageSerializer(instance.messages.all(), many=True, context=self.context).data
        return rep
            
class CreateTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ['subject', 'description']

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)
    
class ActivityLogSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source='user.username')  

    class Meta:
        model = ActivityLog
        fields = [
            'id', 'user', 'activity', 'timestamp', 'ip_address', 
            'activity_type', 'activity_category', 'endpoint', 
            'status_code','user_agent', 'related_object_id', 'related_object_type'
        ]

class TradingAccountGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradingAccountGroup
        fields = [
            'available_groups',    
            'approved_groups',     
            'default_group',       
            'demo_account_group',  
            'created_by',          
            'created_at',          
        ]
        read_only_fields = ['created_by', 'available_groups', 'created_at']

class EmailSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailSetting
        fields = '__all__'

    def validate(self, data):
        
        master_password = data.get('master_password', None)
        confirm_master_password = data.get('confirm_master_password', None)
        if master_password and confirm_master_password and master_password != confirm_master_password:
            raise serializers.ValidationError({
                'confirm_master_password': "Master password and confirmation password do not match."
            })

        
        email_fields = [field for field in data if field.endswith('_from') or field.endswith('_to')]
        for field in email_fields:
            email = data.get(field)
            if email and '@' not in email:
                raise serializers.ValidationError({field: f"{field} must be a valid email address."})

        return data
    
class ServerSettingSerializer(serializers.ModelSerializer):
    real_account_password = serializers.CharField(write_only=True)
    class Meta:
        model = ServerSetting
        fields = '__all__'

    def is_valid(self, raise_exception=False):
        result = super().is_valid(raise_exception=raise_exception)
        if not result:
            print(f"Validation Errors: {self.errors}")
        return result

class BankDetailsRequestSerializer(serializers.ModelSerializer):
    branch = serializers.CharField(source='branch_name', read_only=True)
    user = serializers.CharField(source='user.username', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    
    class Meta:
        model = BankDetailsRequest
        fields = [
            "id", 
            "user_id", 
            "user_name", 
            "user",        # <-- Added to fix API error
            "email", 
            "user_email",  
            "bank_name", 
            "account_number", 
            "branch_name",   # <-- Added branch_name
            "branch",        # <-- Added for frontend compatibility
            "ifsc_code", 
            "bank_doc",      # <-- Added bank_doc
            "status", 
            "created_at", 
            "updated_at",
        ]
        read_only_fields = ["id", "user", "user_email", "status", "created_at", "updated_at"]
    user_id = serializers.IntegerField(source='user.user_id', read_only=True)
    user_name = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    branch_name = serializers.CharField(read_only=True)
    bank_doc = serializers.FileField(read_only=True)
        
class IBRequestSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    useremail = serializers.EmailField(source='user.email', read_only=True)
    user_id = serializers.IntegerField(source='user.user_id', read_only=True)
    class Meta:
        model = IBRequest
        fields = ['id', 'user_id', 'username', 'useremail', 'status', 'created_at', 'updated_at']
        
    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Rename id to request_id to avoid confusion
        data['request_id'] = data.pop('id')
        return data

class ChangeRequestSerializer(serializers.ModelSerializer):
    # user = serializers.CharField(source='user.username', read_only=True)
    user_id = serializers.IntegerField(source='user.user_id', read_only=True)
    user_name = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    requested_changes = serializers.JSONField(source='requested_data', read_only=True)
    
    class Meta:
        model = ChangeRequest
        fields = [
            'id', 'user_id', 'user_name', 'email', 'requested_changes', 'id_proof', 'address_proof', 
            'status', 'created_at', 'reviewed_at'
        ]
        read_only_fields = ['user', 'user_email', 'status', 'created_at', 'reviewed_at']

class UserDocumentSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.user_id', read_only=True)
    user_name = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    id_proof = serializers.SerializerMethodField()
    address_proof = serializers.SerializerMethodField()
    
    class Meta:
        from clientPanel.models import UserDocument
        model = UserDocument
        fields = [
            'id', 'user_id', 'user_name', 'email', 'document_type', 
            'id_proof', 'address_proof', 'status', 'uploaded_at', 'verified_at'
        ]
        read_only_fields = ['user', 'status', 'uploaded_at', 'verified_at']
    
    def get_id_proof(self, obj):
        """Return the document URL if it's an identity document"""
        if obj.document_type == 'identity' and obj.document:
            return obj.document.url
        return None
    
    def get_address_proof(self, obj):
        """Return the document URL if it's a residence document"""
        if obj.document_type == 'residence' and obj.document:
            return obj.document.url
        return None


class MAMAccountSerializer(serializers.ModelSerializer):
    managername = serializers.CharField(source='user.username', read_only=True)
    manager = serializers.CharField(source='user.email', read_only=True)
    class Meta:
        model = TradingAccount
        fields = [
            'id',
            'account_id',
            'balance',
            'account_name',
            'managername', 
            'leverage',
            'profit_sharing_percentage',
            'risk_level',
            'payout_frequency',
            'group_name',
            'is_algo_enabled',
            'is_enabled',
            'status',
            'manager',
            'is_trading_enabled',
            
        ]
        read_only_fields = ['id', 'account_id', 'group_name']

class NewUserSignupSerializer(serializers.ModelSerializer):

    class Meta:
        model = CustomUser
        fields = [
            "first_name",
            "last_name",
            "email",
            "password",
            "phone_number",
            "dob",
        ]
        extra_kwargs = {
            "password": {"write_only": True},  # Ensure password is write-only
        }

    def to_internal_value(self, data):
        data = {
            "first_name": data.get("firstName"),
            "last_name": data.get("lastName"),
            "email": data.get("email"),
            "password": data.get("password"),
            "phone_number": data.get("phone"),
            "dob": data.get("dob"),
        }
        return super().to_internal_value(data)

    def create(self, validated_data):
        # Validate signup email against disposable provider list
        try:
            from adminPanel.utils.email_validation import validate_signup_email
            validate_signup_email(validated_data["email"])
        except ValueError:
            raise serializers.ValidationError({
                "email": "Disposable or temporary email addresses are not allowed"
            })
        except Exception:
            # Non-fatal: if validator fails unexpectedly, proceed with caution
            pass

        # Use manager's create_user so password hashing is handled consistently
        user = CustomUser.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data["first_name"],
            last_name=validated_data["last_name"],
            phone_number=validated_data["phone_number"],
            dob=validated_data.get("dob"),
        )
        user.manager_admin_status = "None"
        user.created_by = None
        user.save()
        return user

class ChatMessageSerializer(serializers.ModelSerializer):
    """
    Serializer for live chat messages between admin and clients.
    Includes sender profile pictures and image attachments.
    """
    sender_email = serializers.EmailField(source='sender.email', read_only=True)
    sender_name = serializers.SerializerMethodField()
    sender_profile_pic = serializers.SerializerMethodField()
    recipient_email = serializers.EmailField(source='recipient.email', read_only=True, allow_null=True)
    recipient_name = serializers.SerializerMethodField()
    recipient_profile_pic = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source='created_at', read_only=True)
    image_url = serializers.SerializerMethodField()
    
    def get_sender_name(self, obj):
        return f"{obj.sender.first_name} {obj.sender.last_name}".strip() or obj.sender.email
    
    def get_sender_profile_pic(self, obj):
        """Get the profile picture of the sender"""
        if obj.sender and obj.sender.profile_pic:
            return str(obj.sender.profile_pic)
        return None
    
    def get_recipient_name(self, obj):
        if obj.recipient:
            return f"{obj.recipient.first_name} {obj.recipient.last_name}".strip() or obj.recipient.email
        return None
    
    def get_recipient_profile_pic(self, obj):
        """Get the profile picture of the recipient"""
        if obj.recipient and obj.recipient.profile_pic:
            return str(obj.recipient.profile_pic)
        return None
    
    def get_image_url(self, obj):
        """Get the full URL of the chat image if it exists"""
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None
    
    class Meta:
        model = ChatMessage
        fields = [
            'id', 'sender', 'sender_email', 'sender_name', 'sender_profile_pic', 'sender_type',
            'recipient', 'recipient_email', 'recipient_name', 'recipient_profile_pic', 'message',
            'image', 'image_url', 'is_read', 'admin_sender_name', 'timestamp', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'timestamp', 'created_at', 'updated_at', 'sender', 'sender_email', 'sender_name', 'sender_profile_pic', 'recipient_email', 'recipient_name', 'recipient_profile_pic', 'image_url']