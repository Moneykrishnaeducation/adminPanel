"""
Test MT5 deposit for PAMM account
"""

from django.core.management.base import BaseCommand
from adminPanel.mt5.services import MT5ManagerActions
from adminPanel.models_pamm import PAMMAccount
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Test MT5 deposit for a PAMM account'

    def add_arguments(self, parser):
        parser.add_argument('pamm_id', type=int, help='PAMM Account ID')
        parser.add_argument('--amount', type=float, default=10.0, help='Amount to deposit')

    def handle(self, *args, **options):
        pamm_id = options['pamm_id']
        amount = options['amount']
        
        try:
            pamm = PAMMAccount.objects.get(id=pamm_id)
            self.stdout.write(f"\n📊 PAMM Account: {pamm.name}")
            self.stdout.write(f"   MT5 Account: {pamm.mt5_account_id}")
            self.stdout.write(f"   Current Equity: ${pamm.total_equity}")
            
            if not pamm.mt5_account_id:
                self.stdout.write(self.style.ERROR("❌ No MT5 account ID"))
                return
            
            # Get current MT5 balance BEFORE deposit
            self.stdout.write(f"\n🔍 Checking MT5 account {pamm.mt5_account_id}...")
            mt5_manager = MT5ManagerActions()
            
            try:
                user_info = mt5_manager.manager.UserGet(int(pamm.mt5_account_id))
                if user_info:
                    balance_before = user_info.Balance
                    self.stdout.write(f"   Balance BEFORE: ${balance_before}")
                    self.stdout.write(f"   Credit: ${user_info.Credit}")
                else:
                    self.stdout.write(self.style.ERROR("   ❌ Account not found in MT5"))
                    return
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"   ❌ Error getting account info: {e}"))
                return
            
            # Test deposit
            self.stdout.write(f"\n💰 Testing deposit of ${amount}...")
            try:
                result = mt5_manager.deposit_funds(
                    login_id=int(pamm.mt5_account_id),
                    amount=float(amount),
                    comment=f"Test Deposit - {pamm.name}"
                )
                
                if result:
                    self.stdout.write(self.style.SUCCESS(f"   ✅ Deposit returned: {result}"))
                else:
                    self.stdout.write(self.style.ERROR(f"   ❌ Deposit returned: {result}"))
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"   ❌ Deposit failed with exception: {e}"))
                import traceback
                traceback.print_exc()
                return
            
            # Get balance AFTER deposit
            self.stdout.write(f"\n🔍 Checking balance after deposit...")
            try:
                user_info = mt5_manager.manager.UserGet(int(pamm.mt5_account_id))
                if user_info:
                    balance_after = user_info.Balance
                    self.stdout.write(f"   Balance AFTER: ${balance_after}")
                    self.stdout.write(f"   Credit: ${user_info.Credit}")
                    self.stdout.write(f"   Change: ${balance_after - balance_before}")
                    
                    if balance_after > balance_before:
                        self.stdout.write(self.style.SUCCESS("\n✅ DEPOSIT SUCCESSFUL!"))
                    else:
                        self.stdout.write(self.style.ERROR("\n❌ DEPOSIT FAILED - Balance unchanged"))
                else:
                    self.stdout.write(self.style.ERROR("   ❌ Account not found"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"   ❌ Error checking after balance: {e}"))
                
        except PAMMAccount.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"❌ PAMM Account {pamm_id} not found"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Unexpected error: {e}"))
            import traceback
            traceback.print_exc()
