"""
Management command to create sample transaction data for testing.
"""
import random
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from adminPanel.models import Transaction, TradingAccount
from django.utils import timezone
from datetime import timedelta

User = get_user_model()

class Command(BaseCommand):
    help = 'Create sample transaction data for testing the transaction modal'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            help='Specific user ID to create transactions for'
        )
        parser.add_argument(
            '--count',
            type=int,
            default=20,
            help='Number of transactions to create (default: 20)'
        )

    def handle(self, *args, **options):
        user_id = options.get('user_id')
        count = options.get('count')

        if user_id:
            try:
                users = [User.objects.get(user_id=user_id)]
                self.stdout.write(f"Creating transactions for user ID: {user_id}")
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'User with ID {user_id} does not exist')
                )
                return
        else:
            users = User.objects.all()[:5]  # Use first 5 users
            if not users:
                self.stdout.write(
                    self.style.ERROR('No users found in the database')
                )
                return

        transaction_types = [
            'deposit_trading',
            'withdraw_trading', 
            'credit_in',
            'credit_out',
            'commission_withdrawal',
            'internal_transfer'
        ]
        
        statuses = ['pending', 'approved', 'rejected']
        sources = ['Bank', 'Crypto', 'Internal', 'Wire Transfer']
        payout_types = ['bank', 'crypto']

        created_count = 0

        for user in users:
            # Get user's trading accounts
            trading_accounts = list(TradingAccount.objects.filter(user=user))
            
            for i in range(count // len(users) + (1 if count % len(users) > 0 else 0)):
                transaction_type = random.choice(transaction_types)
                status = random.choice(statuses)
                
                # Create transaction data
                transaction_data = {
                    'user': user,
                    'transaction_type': transaction_type,
                    'amount': Decimal(str(random.uniform(10.00, 5000.00))).quantize(Decimal('0.01')),
                    'status': status,
                    'source': random.choice(sources),
                    'description': f'Sample {transaction_type.replace("_", " ").title()} transaction for testing',
                    'created_at': timezone.now() - timedelta(days=random.randint(0, 30))
                }

                # Add trading account if available and relevant
                if trading_accounts and transaction_type in ['deposit_trading', 'withdraw_trading', 'credit_in', 'credit_out']:
                    transaction_data['trading_account'] = random.choice(trading_accounts)

                # Add payout details for withdrawals
                if transaction_type in ['withdraw_trading', 'commission_withdrawal']:
                    transaction_data['payout_to'] = random.choice(payout_types)
                    if transaction_data['payout_to'] == 'bank':
                        transaction_data['external_account'] = f'****{random.randint(1000, 9999)}'
                    else:
                        transaction_data['external_account'] = f'0x{random.randint(100000000000, 999999999999):x}'

                # Handle internal transfers
                if transaction_type == 'internal_transfer' and len(trading_accounts) >= 2:
                    accounts = random.sample(trading_accounts, 2)
                    transaction_data['from_account'] = accounts[0]
                    transaction_data['to_account'] = accounts[1]

                # Add approval details for completed transactions
                if status in ['approved', 'rejected']:
                    # Try to get an admin user for approved_by
                    admin_users = User.objects.filter(is_staff=True)
                    if admin_users:
                        transaction_data['approved_by'] = random.choice(admin_users)
                        transaction_data['approved_at'] = transaction_data['created_at'] + timedelta(
                            hours=random.randint(1, 48)
                        )

                try:
                    transaction = Transaction.objects.create(**transaction_data)
                    created_count += 1
                    
                    if created_count % 5 == 0:
                        self.stdout.write(f"Created {created_count} transactions...")
                        
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f'Error creating transaction: {e}')
                    )
                    continue

        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully created {created_count} sample transactions'
            )
        )
        
        # Show summary by status
        total_pending = Transaction.objects.filter(status='pending').count()
        total_approved = Transaction.objects.filter(status='approved').count() 
        total_rejected = Transaction.objects.filter(status='rejected').count()
        
        self.stdout.write(f"\nTransaction Summary:")
        self.stdout.write(f"  Pending: {total_pending}")
        self.stdout.write(f"  Approved: {total_approved}")
        self.stdout.write(f"  Rejected: {total_rejected}")
        self.stdout.write(f"  Total: {total_pending + total_approved + total_rejected}")
