from django.core.management.base import BaseCommand
from adminPanel.mt5.services import MT5ManagerActions
from adminPanel.models import TradingAccount
from datetime import datetime, timedelta
from django.utils import timezone

class Command(BaseCommand):
    help = 'Check MT5 server directly for actual trades and commissions.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=365, help='Number of days to look back')
        parser.add_argument('--max-accounts', type=int, default=10, help='Maximum accounts to check')

    def handle(self, *args, **options):
        days_back = options['days']
        max_accounts = options['max_accounts']
        
        print(f"Checking MT5 server directly for trades (last {days_back} days)...")
        
        mt5 = MT5ManagerActions()
        
        # Check MT5 connection
        if not mt5.manager:
            print("ERROR: MT5 Manager not connected!")
            return
        
        print("SUCCESS: MT5 Manager connected")
        
        # Get test accounts
        test_accounts = TradingAccount.objects.all()[:max_accounts]
        print(f"Testing {len(test_accounts)} accounts...")
        
        total_trades_found = 0
        accounts_with_trades = 0
        
        for i, account in enumerate(test_accounts):
            print(f"\nAccount {i+1}/{len(test_accounts)}: {account.account_id}")
            print(f"  User: {account.user.email}")
            
            try:
                # Check with broad date range
                from_date = timezone.now() - timedelta(days=days_back)
                closed_trades = mt5.get_closed_trades(account.account_id, from_date=from_date)
                
                trade_count = len(closed_trades) if closed_trades else 0
                total_trades_found += trade_count
                
                print(f"  Trades found: {trade_count}")
                
                if trade_count > 0:
                    accounts_with_trades += 1
                    print(f"  Sample trades:")
                    
                    # Show first 3 trades
                    for j, trade in enumerate(closed_trades[:3]):
                        try:
                            deal_id = getattr(trade, 'Deal', 'N/A')
                            position_id = getattr(trade, 'Position', 'N/A')
                            symbol = getattr(trade, 'Symbol', 'N/A')
                            volume = getattr(trade, 'Volume', 0)
                            commission = getattr(trade, 'Commission', 0)
                            profit = getattr(trade, 'Profit', 0)
                            time_attr = getattr(trade, 'Time', 0)
                            
                            # Convert time
                            if time_attr:
                                try:
                                    trade_time = datetime.fromtimestamp(int(time_attr))
                                    time_str = trade_time.strftime('%Y-%m-%d %H:%M:%S')
                                except:
                                    time_str = str(time_attr)
                            else:
                                time_str = 'N/A'
                            
                            lot_size = float(volume) / 10000.0 if volume > 0 else 0.0
                            
                            print(f"    {j+1}. Deal: {deal_id}, Position: {position_id}")
                            print(f"       Symbol: {symbol}, Lots: {lot_size}")
                            print(f"       Commission: ${commission}, Profit: ${profit}")
                            print(f"       Time: {time_str}")
                            
                        except Exception as e:
                            print(f"    Error reading trade {j+1}: {e}")
                    
                    # If we found trades, we can stop here for initial analysis
                    if j == 0:  # Found trades in first account, that's enough for now
                        break
                
            except Exception as e:
                print(f"  ERROR: {e}")
        
        # Summary
        print(f"\n=== SUMMARY ===")
        print(f"Total accounts checked: {len(test_accounts)}")
        print(f"Accounts with trades: {accounts_with_trades}")
        print(f"Total trades found: {total_trades_found}")
        
        if total_trades_found > 0:
            print(f"\nSUCCESS: Found {total_trades_found} trades on MT5 server!")
            print(f"The commission sync should be processing these trades.")
        else:
            print(f"\nNO TRADES FOUND: MT5 server shows no trading activity in last {days_back} days")
            print(f"This could mean:")
            print(f"  - No actual trading has occurred")
            print(f"  - Trades are in a different time period")
            print(f"  - MT5 data access issues")
        
        # Test basic MT5 operations
        print(f"\n=== MT5 CONNECTION TEST ===")
        try:
            first_account = test_accounts[0] if test_accounts else None
            if first_account:
                balance = mt5.get_balance(first_account.account_id)
                equity = mt5.get_equity(first_account.account_id)
                print(f"Account {first_account.account_id}:")
                print(f"  Balance: ${balance}")
                print(f"  Equity: ${equity}")
        except Exception as e:
            print(f"Error testing MT5 operations: {e}")