from django.core.management.base import BaseCommand
from adminPanel.models import CustomUser, CommissionTransaction, TradingAccount
from django.db.models import Sum


class Command(BaseCommand):
    help = 'Get lot size info for an IB user (by email/username/referral_code/user_id)'

    def add_arguments(self, parser):
        parser.add_argument('--identifier', required=True, help='Identifier to lookup (email/username/referral_code/user_id)')
        parser.add_argument('--by', choices=['email', 'username', 'referral', 'user_id'], default='email')
        parser.add_argument('--recent', type=int, default=10, help='Number of recent commission transactions to show')

    def handle(self, *args, **options):
        identifier = options['identifier']
        by = options['by']
        recent = options['recent']

        qs = CustomUser.objects.all()
        user = None

        if by == 'email':
            user = qs.filter(email=identifier).first()
        elif by == 'username':
            user = qs.filter(username__iexact=identifier).first()
        elif by == 'referral':
            user = qs.filter(referral_code__iexact=identifier).first()
        elif by == 'user_id':
            try:
                uid = int(identifier)
                user = qs.filter(user_id=uid).first()
            except Exception:
                user = None

        if not user:
            self.stderr.write(f'No user found by {by}={identifier}')
            return

        self.stdout.write(f'Found IB user: email={user.email}, username={user.username}, user_id={user.user_id}')

        # List trading accounts for this user
        taccs = TradingAccount.objects.filter(user=user)
        if taccs.exists():
            self.stdout.write('\nTrading accounts:')
            for ta in taccs:
                self.stdout.write(f'- account_id={ta.account_id}, group={ta.group_name}, leverage={ta.leverage}, balance={ta.balance}')
        else:
            self.stdout.write('\nNo TradingAccount objects found for this user.')

        # Aggregate CommissionTransaction lot sizes
        total_lots = CommissionTransaction.objects.filter(ib_user=user).aggregate(total=Sum('lot_size'))['total'] or 0.0
        txn_count = CommissionTransaction.objects.filter(ib_user=user).count()
        avg = (float(total_lots) / txn_count) if txn_count else 0.0

        self.stdout.write(f'\nCommissionTransaction summary:')
        self.stdout.write(f'- total_lots: {float(total_lots)}')
        self.stdout.write(f'- transaction_count: {txn_count}')
        self.stdout.write(f'- average_lot_per_txn: {avg:.6f}')

        # Fetch recent transactions safely (avoid referencing columns that may not exist in older DB schema)
        try:
            recent_qs = CommissionTransaction.objects.filter(ib_user=user).order_by('-created_at')[:recent]
            if recent_qs:
                self.stdout.write(f'\nRecent {len(recent_qs)} CommissionTransactions:')
                for ct in recent_qs:
                    client_email = getattr(ct.client_user, 'email', None)
                    created = ct.created_at.isoformat() if getattr(ct, 'created_at', None) else 'N/A'
                    pos = getattr(ct, 'position_id', None)
                    lot = getattr(ct, 'lot_size', None)
                    profit = getattr(ct, 'profit', None)
                    comm = getattr(ct, 'commission_to_ib', None)
                    self.stdout.write(f"- {created} pos={pos} lot_size={lot} profit={profit} commission_to_ib={comm} client={client_email}")
            else:
                self.stdout.write('\nNo recent CommissionTransaction records found for this user.')
        except Exception as e:
            # Defensive: some environments may have missing columns or schema drift
            self.stderr.write(f'Failed to fetch recent CommissionTransaction records safely: {e}')
            # As a fallback, attempt a values() query with common fields only
            try:
                recent_vals = CommissionTransaction.objects.filter(ib_user=user).values('created_at', 'position_id', 'lot_size', 'profit', 'commission_to_ib')[:recent]
                if recent_vals:
                    self.stdout.write(f'\nRecent {len(recent_vals)} CommissionTransactions (fallback values):')
                    for ct in recent_vals:
                        client_email = ''
                        created = ct.get('created_at')
                        pos = ct.get('position_id')
                        lot = ct.get('lot_size')
                        profit = ct.get('profit')
                        comm = ct.get('commission_to_ib')
                        self.stdout.write(f"- {created} pos={pos} lot_size={lot} profit={profit} commission_to_ib={comm} client={client_email}")
                else:
                    self.stdout.write('\nNo recent CommissionTransaction records found for this user (fallback).')
            except Exception as e2:
                self.stderr.write(f'Fallback also failed: {e2}')
