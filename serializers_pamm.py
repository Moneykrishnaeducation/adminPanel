"""
PAMM Serializers
Handles serialization for PAMM accounts, participants, and transactions
"""

from rest_framework import serializers
from decimal import Decimal
from adminPanel.models_pamm import PAMMAccount, PAMMParticipant, PAMMTransaction, PAMMEquitySnapshot
from django.contrib.auth import get_user_model

User = get_user_model()


class PAMMAccountSerializer(serializers.ModelSerializer):
    """Serializer for PAMM Account"""
    manager_email = serializers.EmailField(source='manager.email', read_only=True)
    manager_name = serializers.SerializerMethodField()
    unit_price = serializers.SerializerMethodField()
    investor_count = serializers.SerializerMethodField()
    total_investor_units = serializers.SerializerMethodField()
    
    class Meta:
        model = PAMMAccount
        fields = [
            'id', 'name', 'manager', 'manager_email', 'manager_name',
            'profit_share', 'total_equity', 'total_units', 'unit_price',
            'high_water_mark', 'mt5_account_id', 'leverage', 'status',
            'is_accepting_investors', 'investor_count', 'total_investor_units',
            'created_at', 'updated_at', 'last_equity_update'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_equity_update']
    
    def get_manager_name(self, obj):
        return f"{obj.manager.first_name} {obj.manager.last_name}".strip() or obj.manager.email
    
    def get_unit_price(self, obj):
        """Get current unit price"""
        return str(obj.unit_price())
    
    def get_investor_count(self, obj):
        """Get number of active investors"""
        return obj.participants.filter(role='INVESTOR', units__gt=0).count()
    
    def get_total_investor_units(self, obj):
        """Get total units held by investors"""
        total = obj.participants.filter(role='INVESTOR').aggregate(
            total=serializers.models.Sum('units')
        )['total'] or Decimal('0.00000000')
        return str(total)


class PAMMAccountCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new PAMM account"""
    master_password = serializers.CharField(write_only=True, required=True)
    invest_password = serializers.CharField(write_only=True, required=True)
    
    def __init__(self, *args, **kwargs):
        # Accept both `invest_password` and `investor_password` from clients.
        data = kwargs.get('data')
        if data is not None:
            try:
                # Handle QueryDict and dict-like objects
                mutable = getattr(data, 'copy', None)
                if callable(mutable):
                    d = data.copy()
                else:
                    d = dict(data)

                if 'invest_password' not in d and 'investor_password' in d:
                    d['invest_password'] = d.get('investor_password')
                    kwargs['data'] = d
            except Exception:
                pass

        super().__init__(*args, **kwargs)
    
    class Meta:
        model = PAMMAccount
        fields = [
            'name', 'profit_share', 'leverage',
            'master_password', 'invest_password'
        ]
    
    def validate_profit_share(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError("Profit share must be between 0 and 100")
        return value
    
    def validate_leverage(self, value):
        valid_leverages = [1, 10, 25, 50, 100, 200, 400, 500]
        if value not in valid_leverages:
            raise serializers.ValidationError(f"Leverage must be one of {valid_leverages}")
        return value


class PAMMParticipantSerializer(serializers.ModelSerializer):
    """Serializer for PAMM Participant"""
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()
    pamm_name = serializers.CharField(source='pamm.name', read_only=True)
    current_balance = serializers.SerializerMethodField()
    profit_loss = serializers.SerializerMethodField()
    share_percentage = serializers.SerializerMethodField()
    unit_price = serializers.SerializerMethodField()
    
    class Meta:
        model = PAMMParticipant
        fields = [
            'id', 'user', 'user_email', 'user_name', 'pamm', 'pamm_name',
            'role', 'units', 'total_deposited', 'total_withdrawn',
            'current_balance', 'profit_loss', 'share_percentage',
            'unit_price', 'joined_at', 'last_transaction_at'
        ]
        read_only_fields = ['id', 'joined_at', 'last_transaction_at']
    
    def get_user_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.email
    
    def get_current_balance(self, obj):
        """Get current value in USD"""
        return str(obj.current_balance())
    
    def get_profit_loss(self, obj):
        """Get P/L in USD"""
        return str(obj.profit_loss())
    
    def get_share_percentage(self, obj):
        """Get ownership percentage"""
        return str(obj.share_percentage())
    
    def get_unit_price(self, obj):
        """Get current unit price"""
        return str(obj.pamm.unit_price())


class PAMMTransactionSerializer(serializers.ModelSerializer):
    """Serializer for PAMM Transaction"""
    participant_email = serializers.EmailField(source='participant.user.email', read_only=True)
    participant_name = serializers.SerializerMethodField()
    pamm_name = serializers.CharField(source='pamm.name', read_only=True)
    approved_by_email = serializers.EmailField(source='approved_by.email', read_only=True)
    
    class Meta:
        model = PAMMTransaction
        fields = [
            'id', 'pamm', 'pamm_name', 'participant', 'participant_email',
            'participant_name', 'transaction_type', 'amount', 'units_added',
            'units_removed', 'unit_price_at_transaction', 'payment_method',
            'payment_proof', 'status', 'approved_by', 'approved_by_email',
            'approved_at', 'rejection_reason', 'created_at', 'completed_at', 'notes'
        ]
        read_only_fields = [
            'id', 'created_at', 'approved_at', 'completed_at',
            'units_added', 'units_removed', 'unit_price_at_transaction'
        ]
    
    def get_participant_name(self, obj):
        if obj.participant:
            user = obj.participant.user
            return f"{user.first_name} {user.last_name}".strip() or user.email
        return "System"


class PAMMDepositRequestSerializer(serializers.Serializer):
    """Serializer for deposit requests"""
    pamm_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, min_value=Decimal('10.00'))
    method = serializers.ChoiceField(choices=['usdt', 'manual'])
    proof = serializers.FileField(required=False)
    
    def validate_pamm_id(self, value):
        try:
            pamm = PAMMAccount.objects.get(id=value)
            if pamm.status != 'ACTIVE':
                raise serializers.ValidationError("PAMM account is not active")
            return value
        except PAMMAccount.DoesNotExist:
            raise serializers.ValidationError("PAMM account not found")
    
    def validate(self, data):
        # Require proof for certain payment methods
        if data['method'] in ['usdt', 'manual'] and not data.get('proof'):
            raise serializers.ValidationError({"proof": "Payment proof is required for this method"})
        return data


class PAMMWithdrawRequestSerializer(serializers.Serializer):
    """Serializer for withdrawal requests"""
    pamm_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, min_value=Decimal('1.00'))
    method = serializers.ChoiceField(choices=['usdt', 'manual'])
    
    def validate_pamm_id(self, value):
        try:
            pamm = PAMMAccount.objects.get(id=value)
            if pamm.status != 'ACTIVE':
                raise serializers.ValidationError("PAMM account is not active")
            return value
        except PAMMAccount.DoesNotExist:
            raise serializers.ValidationError("PAMM account not found")


class PAMMInvestSerializer(serializers.Serializer):
    """Serializer for investor joining a PAMM"""
    pamm_id = serializers.IntegerField()
    investor_name = serializers.CharField(max_length=100, required=False)
    
    def validate_pamm_id(self, value):
        try:
            pamm = PAMMAccount.objects.get(id=value)
            if pamm.status != 'ACTIVE':
                raise serializers.ValidationError("PAMM account is not active")
            if not pamm.is_accepting_investors:
                raise serializers.ValidationError("PAMM is not accepting new investors")
            return value
        except PAMMAccount.DoesNotExist:
            raise serializers.ValidationError("PAMM account not found")


class PAMMEquitySnapshotSerializer(serializers.ModelSerializer):
    """Serializer for equity snapshots (charting)"""
    pamm_name = serializers.CharField(source='pamm.name', read_only=True)
    
    class Meta:
        model = PAMMEquitySnapshot
        fields = [
            'id', 'pamm', 'pamm_name', 'equity', 'total_units', 'unit_price',
            'manager_units', 'investor_units', 'investor_count', 'timestamp'
        ]
        read_only_fields = ['id', 'timestamp']


class PAMMDetailSerializer(PAMMAccountSerializer):
    """Extended serializer with full PAMM details including participants"""
    participants = PAMMParticipantSerializer(many=True, read_only=True)
    recent_transactions = serializers.SerializerMethodField()
    manager_participant = serializers.SerializerMethodField()
    
    class Meta(PAMMAccountSerializer.Meta):
        fields = PAMMAccountSerializer.Meta.fields + [
            'participants', 'recent_transactions', 'manager_participant'
        ]
    
    def get_recent_transactions(self, obj):
        """Get last 10 transactions"""
        transactions = obj.transactions.all()[:10]
        return PAMMTransactionSerializer(transactions, many=True).data
    
    def get_manager_participant(self, obj):
        """Get manager's participant record"""
        try:
            manager_part = obj.participants.get(user=obj.manager, role='MANAGER')
            return PAMMParticipantSerializer(manager_part).data
        except PAMMParticipant.DoesNotExist:
            return None
