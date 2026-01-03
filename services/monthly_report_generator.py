from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML
import os
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
import logging
from django.conf import settings
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from adminPanel.models import CustomUser, Transaction, CommissionTransaction, TradingAccount
from adminPanel.mt5.services import MT5ManagerActions

# Try to import pikepdf for PDF encryption, but make it optional
try:
    import pikepdf
    PIKEPDF_AVAILABLE = True
except ImportError:
    PIKEPDF_AVAILABLE = False
    pikepdf = None

logger = logging.getLogger(__name__)


class MonthlyTradeReportGenerator:
    # The following ReportLab-related methods are no longer used and are commented out for cleanup:
    # def _create_header(self, story):
    #     pass
    # def _create_summary_section(self, story, data):
    #     pass
    # def _create_trading_positions_section(self, story, data):
    #     pass
    # def _create_commission_section(self, story, data):
    #     pass
    # def _create_footer(self, story):
    #     pass

    def generate_html_pdf_report(self, output_path=None):
        """
        Generate a PDF report using HTML/CSS (Jinja2 + WeasyPrint).
        Args:
            output_path: Optional path to save the PDF. If None, creates a temp file.
        Returns:
            str: Path to the generated PDF file
        """
        try:
            logger.info("Starting PDF report generation...")
            
            # Prepare output path
            if output_path is None:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
                output_path = temp_file.name
                temp_file.close()

            # Gather data
            logger.info("Gathering trading data...")
            data = self._get_trading_data()
            summary = data['summary']
            trades = data['trading_positions']
            
            logger.info(f"Found {len(trades)} trades, summary data: {summary}")

            # Prepare template environment
            template_dir = os.path.dirname(os.path.abspath(__file__))
            logger.info(f"Template directory: {template_dir}")
            
            env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=select_autoescape(['html', 'xml'])
            )
            template = env.get_template('report_template.html')
            logger.info("Template loaded successfully")

            # Render HTML
            try:
                # Convert Decimal values to float safely
                starting_balance_float = float(summary['starting_balance']) if summary['starting_balance'] is not None else 0.0
                ending_balance_float = float(summary['ending_balance']) if summary['ending_balance'] is not None else 0.0
                total_pnl_float = float(summary['total_pnl']) if summary['total_pnl'] is not None else 0.0
                
                # Get user name safely
                user_name = ""
                if hasattr(self.user, 'get_full_name') and self.user.get_full_name():
                    user_name = self.user.get_full_name()
                elif hasattr(self.user, 'first_name') and hasattr(self.user, 'last_name'):
                    user_name = f"{self.user.first_name} {self.user.last_name}".strip()
                else:
                    user_name = getattr(self.user, 'email', 'Unknown User')
                
                # Get account ID safely - use primary trading account ID if available
                primary_account = data['trading_accounts'].first() if data['trading_accounts'] else None
                if primary_account:
                    account_id = primary_account.account_id
                else:
                    account_id = getattr(self.user, 'user_id', None) or getattr(self.user, 'id', 'N/A')
                
                logger.info(f"Rendering template for user: {user_name}")
                logger.info(f"Using account ID: {account_id}")
                
                html_content = template.render(
                    company_name=getattr(settings, 'COMPANY_NAME', 'VT Index'),
                    logo_path=getattr(settings, 'COMPANY_LOGO_PATH', None),
                    report_month=self.start_date.strftime('%B %Y'),
                    client_name=user_name,
                    account_id=str(account_id),
                    starting_balance=f"{starting_balance_float:,.2f}",
                    ending_balance=f"{ending_balance_float:,.2f}",
                    total_pnl=f"{total_pnl_float:,.2f}",
                    trades=trades or []  # Ensure trades is never None
                )
                logger.info("Template rendered successfully")
            except Exception as template_error:
                logger.error(f"Error rendering template: {str(template_error)}")
                raise

            # Generate PDF from HTML
            logger.info("Generating PDF from HTML...")
            HTML(string=html_content, base_url=template_dir).write_pdf(output_path)
            logger.info(f"PDF generated successfully: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error generating HTML-based PDF report: {str(e)}")
            # Log more details for debugging
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise
    @staticmethod
    def generate_report_password(user):
        name_part = ''.join(user.first_name.upper().replace(' ', '')[:4])
        dob_part = user.dob.strftime('%d%m') if user.dob else '0000'
        return f"{name_part}{dob_part}"
    """Service class to generate monthly trade reports as password-protected PDFs"""
    
    def __init__(self, user, report_month):
        """
        Initialize the report generator
        
        Args:
            user: CustomUser instance
            report_month: datetime.date object representing the month (YYYY-MM-01)
        """
        self.user = user
        self.report_month = report_month
        self.start_date = report_month
        self.end_date = self._get_month_end_date(report_month)
        # self.styles = getSampleStyleSheet()  # Removed ReportLab style setup
        # self._setup_custom_styles()  # Removed, no longer needed
        
    def _get_month_end_date(self, month_date):
        """Get the last day of the month"""
        next_month = month_date.replace(month=month_date.month + 1) if month_date.month < 12 else month_date.replace(year=month_date.year + 1, month=1)
        return next_month - timedelta(days=1)
    
    # ReportLab style setup removed (no longer needed)
    
    def _get_trading_data(self):
        """
        Fetch and aggregate all trading-related data for the report period, using real MT5 data.
        Returns a dictionary with all relevant data for the report.
        """
        try:
            # --- Django ORM for internal data (deposits, withdrawals, commissions) ---
            trading_accounts = TradingAccount.objects.filter(user=self.user)
            if not trading_accounts.exists():
                logger.warning(f"No trading accounts found for user {self.user.email}")
            
            transactions = Transaction.objects.filter(
                user=self.user,
                created_at__date__range=[self.start_date, self.end_date],
                status='approved'
            ).order_by('created_at')
            
            commission_transactions = CommissionTransaction.objects.filter(
                ib_user=self.user,
                created_at__date__range=[self.start_date, self.end_date]
            ).order_by('created_at')

            deposit_amount = transactions.filter(
                transaction_type__in=['deposit_trading', 'credit_in']
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            
            withdrawal_amount = transactions.filter(
                transaction_type__in=['withdraw_trading', 'credit_out', 'commission_withdrawal']
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            
            total_commission_earned = commission_transactions.aggregate(
                total=Sum('commission_to_ib')
            )['total'] or Decimal('0')

            # --- MT5 Integration for balances and trades ---
            mt5_manager = None
            try:
                mt5_manager = MT5ManagerActions()
            except Exception as e:
                logger.error(f"Failed to initialize MT5 manager: {str(e)}")
            
            trading_positions = []
            starting_balance = Decimal('0')
            ending_balance = Decimal('0')
            total_pnl = Decimal('0')

            # Get data for each trading account
            for account in trading_accounts:
                try:
                    if mt5_manager is None:
                        # Fall back to stored values if MT5 is unavailable
                        logger.warning(f"MT5 unavailable, using stored balance for account {account.account_id}")
                        starting_balance += account.balance or Decimal('0')
                        ending_balance += account.balance or Decimal('0')
                        continue
                    
                    # Get real-time account balance and equity (current/ending)
                    account_balance = mt5_manager.get_balance(int(account.account_id))
                    account_equity = mt5_manager.get_equity(int(account.account_id))
                    
                    logger.info(f"Account {account.account_id} - MT5 Balance: {account_balance}, Equity: {account_equity}")
                    
                    # Ensure we have valid numeric values
                    if account_balance is not None and account_balance is not False:
                        current_balance = Decimal(str(account_balance))
                        current_equity = Decimal(str(account_equity)) if account_equity else current_balance
                        
                        # Get historical starting balance (balance at start of month)
                        account_starting_balance = self._get_historical_balance(account.account_id, self.start_date, current_balance)
                        
                        starting_balance += account_starting_balance
                        ending_balance += current_equity
                        
                        logger.info(f"Account {account.account_id} - Starting: {account_starting_balance}, Ending: {current_equity}")
                    else:
                        # Fallback to stored balance if MT5 fails
                        logger.warning(f"MT5 data unavailable for account {account.account_id}, using stored balance")
                        starting_balance += account.balance or Decimal('0')
                        ending_balance += account.balance or Decimal('0')
                        starting_balance += account.balance or Decimal('0')
                        ending_balance += account.balance or Decimal('0')
                    
                    # Get trading history for this account for the period
                    account_trades = self._get_mt5_account_trades(account.account_id)
                    trading_positions.extend(account_trades)
                    
                except Exception as e:
                    logger.warning(f"Could not fetch MT5 data for account {account.account_id}: {str(e)}")
                    # Fallback to stored balance if MT5 fails
                    starting_balance += account.balance or Decimal('0')
                    ending_balance += account.balance or Decimal('0')

            logger.info(f"=== Monthly Report Data Summary for {self.user.email} ===")
            logger.info(f"Period: {self.start_date} to {self.end_date}")
            logger.info(f"Total Starting Balance: ${starting_balance}")
            logger.info(f"Total Ending Balance: ${ending_balance}")
            logger.info(f"Total Deposits: ${deposit_amount}")
            logger.info(f"Total Withdrawals: ${withdrawal_amount}")
            logger.info(f"Total Trades Found: {len(trading_positions)}")
            
            # Calculate total P/L from all positions and account equity changes
            trades_pnl = sum(Decimal(str(pos.get('profit', 0))) for pos in trading_positions)
            
            # Calculate P/L from account equity changes (more accurate for overall performance)
            # P/L = (Ending Balance - Starting Balance) - (Deposits - Withdrawals)
            balance_change = ending_balance - starting_balance
            net_deposits = deposit_amount - withdrawal_amount
            equity_pnl = balance_change - net_deposits
            
            logger.info(f"Balance Change: ${balance_change}")
            logger.info(f"Net Deposits: ${net_deposits}")
            logger.info(f"Equity P/L: ${equity_pnl}")
            logger.info(f"Trades P/L: ${trades_pnl}")
            
            # Use the equity P/L as it represents the actual account performance
            # This accounts for all trading activity, not just individual trades
            total_pnl = equity_pnl
            
            # If we have individual trades and the difference is significant, log it for review
            if trading_positions and abs(trades_pnl - equity_pnl) > Decimal('10'):
                logger.info(f"P/L calculation difference for user {self.user.email}: trades={trades_pnl}, equity={equity_pnl}, using equity P/L")
            
            # Ensure we don't show negative P/L if there are no trades and no deposits/withdrawals
            if not trading_positions and net_deposits == 0 and total_pnl < 0:
                logger.info(f"Adjusting P/L for user {self.user.email}: no trades, no deposits, using balance change directly")
                total_pnl = balance_change
            
            logger.info(f"Final P/L: ${total_pnl}")

            net_balance_change = deposit_amount - withdrawal_amount

            return {
                'trading_accounts': trading_accounts,
                'transactions': transactions,
                'commission_transactions': commission_transactions,
                'trading_positions': trading_positions,
                'summary': {
                    'starting_balance': starting_balance,
                    'ending_balance': ending_balance,
                    'total_pnl': total_pnl,
                    'total_deposits': deposit_amount,
                    'total_withdrawals': withdrawal_amount,
                    'total_commission_earned': total_commission_earned,
                    'net_balance_change': net_balance_change,
                    'transaction_count': transactions.count(),
                    'commission_count': commission_transactions.count()
                }
            }
        
        except Exception as e:
            logger.error(f"Error in _get_trading_data: {str(e)}")
            # Return minimal valid data structure
            return {
                'trading_accounts': [],
                'transactions': [],
                'commission_transactions': [],
                'trading_positions': [],
                'summary': {
                    'starting_balance': Decimal('0'),
                    'ending_balance': Decimal('0'),
                    'total_pnl': Decimal('0'),
                    'total_deposits': Decimal('0'),
                    'total_withdrawals': Decimal('0'),
                    'total_commission_earned': Decimal('0'),
                    'net_balance_change': Decimal('0'),
                    'transaction_count': 0,
                    'commission_count': 0
                }
            }
    
    def _get_mt5_account_trades(self, account_id):
        """
        Get trading history for a specific account from MT5 Manager for the report period.
        """
        try:
            mt5_manager = MT5ManagerActions()
            
            # Restore: Use report's start_date and end_date for trade history
            if hasattr(self.start_date, 'timestamp'):
                start_timestamp = int(self.start_date.timestamp())
            else:
                from datetime import datetime
                start_datetime = datetime.combine(self.start_date, datetime.min.time())
                start_timestamp = int(start_datetime.timestamp())

            if hasattr(self.end_date, 'timestamp'):
                end_timestamp = int(self.end_date.timestamp())
            else:
                from datetime import datetime
                end_datetime = datetime.combine(self.end_date, datetime.max.time())
                end_timestamp = int(end_datetime.timestamp())
            
            # Get deals/trades from MT5 Manager for this account and period
            deals = []
            trades = []
            
            # Debug prints removed for production
            try:
                # Method 1: Try HistoryDealsGet if available (now on mt5_manager)
                if hasattr(mt5_manager, 'HistoryDealsGet'):
                    logger.info(f"Using HistoryDealsGet for account {account_id}")
                    deals = mt5_manager.HistoryDealsGet(
                        int(account_id), 
                        start_timestamp, 
                        end_timestamp
                    )
                    # Debug print removed
                    if not deals or deals is False:
                        logger.warning(f"[MT5] DealRequest failed for login_id={account_id}: {deals}")
                        deals = []
                    else:
                        logger.info(f"Found {len(deals)} deals for account {account_id}")
                # Method 2: Try getting current positions (open trades)
                elif hasattr(mt5_manager, 'get_open_positions'):
                    logger.info(f"Using get_open_positions for account {account_id}")
                    positions = mt5_manager.get_open_positions(int(account_id))
                    # Debug print removed
                    if positions:
                        logger.info(f"Found {len(positions)} open positions for account {account_id}")
                        # Convert positions to trade format
                        for pos in positions:
                            trades.append({
                                'open_time': pos.get('date', 'N/A'),
                                'close_time': 'Open',
                                'symbol': pos.get('symbol', 'N/A'),
                                'type': pos.get('type', 'N/A'),
                                'volume': float(pos.get('volume', 0)),
                                'profit': float(pos.get('profit', 0))
                            })
                    else:
                        logger.info(f"No open positions found for account {account_id}")
                        # If no open positions but there's a balance discrepancy, create a summary entry
                        account_balance = mt5_manager.get_balance(int(account_id))
                        account_equity = mt5_manager.get_equity(int(account_id))
                        
                        # Check for any unrealized P/L or closed trades not showing up
                        if account_balance and account_equity and abs(account_equity - account_balance) > 0.01:
                            unrealized_pnl = float(account_equity - account_balance)
                            logger.info(f"Creating unrealized P/L entry: {unrealized_pnl}")
                            trades.append({
                                'open_time': 'N/A',
                                'close_time': 'Current',
                                'symbol': 'FLOATING P/L',
                                'type': 'N/A',
                                'volume': 0.0,
                                'profit': unrealized_pnl
                            })
                        
                        # Also check if there were any closed trades that resulted in the current balance
                        # If we have deposits but balance is less than deposits, there were trading losses
                        try:
                            # Get transaction data to infer trading activity
                            from adminPanel.models import Transaction
                            period_deposits = Transaction.objects.filter(
                                trading_account__account_id=account_id,
                                created_at__date__range=[self.start_date, self.end_date],
                                transaction_type__in=['deposit_trading', 'credit_in'],
                                status='approved'
                            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
                            
                            if period_deposits > 0 and account_balance < period_deposits:
                                trading_loss = float(period_deposits - Decimal(str(account_balance)))
                                logger.info(f"Inferred trading loss from balance analysis: {trading_loss}")
                                trades.append({
                                    'open_time': self.start_date.strftime('%Y-%m-%d'),
                                    'close_time': 'Period End',
                                    'symbol': 'TRADING ACTIVITY',
                                    'type': 'N/A',
                                    'volume': 0.0,
                                    'profit': -trading_loss
                                })
                        except Exception as txn_error:
                            logger.warning(f"Could not analyze transaction-based trades: {str(txn_error)}")
                
                
                # Method 3: Fallback - check if account exists and create placeholder data
                else:
                    logger.warning(f"No deal history method available for account {account_id}")
                    # Try to get some basic account trading info
                    if hasattr(mt5_manager.manager, 'UserGet'):
                        user_info = mt5_manager.manager.UserGet(int(account_id))
                        if user_info:
                            logger.info(f"Account {account_id} exists in MT5")
                            # If we can't get trade history, create a summary entry based on balance changes
                            account_balance = mt5_manager.get_balance(int(account_id))
                            account_equity = mt5_manager.get_equity(int(account_id))
                            
                            # Check if there's any profit/loss to report
                            if account_balance and account_equity and abs(account_equity - account_balance) > 0.01:
                                unrealized_pnl = float(account_equity - account_balance)
                                trades.append({
                                    'open_time': self.start_date.strftime('%Y-%m-%d'),
                                    'close_time': 'Open Positions',
                                    'symbol': 'MULTIPLE',
                                    'type': 'N/A',
                                    'volume': 0.0,
                                    'profit': unrealized_pnl
                                })
                                logger.info(f"Added summary trade entry for account {account_id}: P/L = {unrealized_pnl}")
                    
                    # Also try to find any recent transactions that might indicate trading activity
                    try:
                        from adminPanel.models import Transaction
                        recent_transactions = Transaction.objects.filter(
                            trading_account__account_id=account_id,
                            created_at__date__range=[self.start_date, self.end_date],
                            transaction_type__in=['profit', 'loss', 'commission'],
                            status='approved'
                        )
                        
                        for txn in recent_transactions:
                            trades.append({
                                'open_time': txn.created_at.strftime('%Y-%m-%d %H:%M'),
                                'close_time': txn.created_at.strftime('%Y-%m-%d %H:%M'),
                                'symbol': 'TRANSACTION',
                                'type': 'N/A',
                                'volume': 0.0,
                                'profit': float(txn.amount)
                            })
                        
                        if recent_transactions.exists():
                            logger.info(f"Found {recent_transactions.count()} transaction-based trades for account {account_id}")
                            
                    except Exception as txn_error:
                        logger.warning(f"Could not get transaction-based trades for account {account_id}: {str(txn_error)}")
                    
            except Exception as api_error:
                logger.warning(f"MT5 API error for account {account_id}: {str(api_error)}")
                return trades  # Return any trades we found so far
            


            trades = []
            # Add closed trades (deals)
            if deals:
                for deal in deals:
                    try:
                        # Filter for actual trade deals (buy/sell, not deposits/withdrawals)
                        deal_type = getattr(deal, 'Type', None) or getattr(deal, 'Action', None)
                        if deal_type is not None and deal_type in [0, 1]:  # 0=Buy, 1=Sell
                            symbol = getattr(deal, 'Symbol', 'N/A')
                            volume = getattr(deal, 'Volume', 0)
                            profit = getattr(deal, 'Profit', 0)
                            deal_time = getattr(deal, 'Time', 0)
                            # Convert volume to standard lots (MT5 usually stores in micro lots)
                            lots = volume / 10000 if volume > 0 else volume
                            trade_type_str = 'Buy' if deal_type == 0 else 'Sell' if deal_type == 1 else 'Other'
                            trades.append({
                                'open_time': self._format_mt5_time(deal_time),
                                'close_time': self._format_mt5_time(deal_time),  # For deals, open/close might be same
                                'symbol': symbol,
                                'type': trade_type_str,
                                'volume': float(lots) if lots else 0.0,
                                'profit': float(profit) if profit else 0.0,
                                'status': 'Closed'
                            })
                    except Exception as deal_error:
                        logger.warning(f"Error processing deal for account {account_id}: {str(deal_error)}")
                        continue

            # Add open positions (always, if available)
            if hasattr(mt5_manager, 'get_open_positions'):
                try:
                    open_positions = mt5_manager.get_open_positions(int(account_id))
                    if open_positions:
                        logger.info(f"Found {len(open_positions)} open positions for account {account_id}")
                        for pos in open_positions:
                            open_time_val = pos.get('date', 'N/A')
                            # Convert timestamp to readable date/time if it's an int or float
                            if isinstance(open_time_val, (int, float)):
                                try:
                                    open_time_str = datetime.fromtimestamp(open_time_val).strftime('%Y-%m-%d %H:%M')
                                except Exception:
                                    open_time_str = str(open_time_val)
                            else:
                                open_time_str = str(open_time_val)
                            trades.append({
                                'open_time': open_time_str,
                                'close_time': '-',
                                'symbol': pos.get('symbol', 'N/A'),
                                'type': pos.get('type', 'N/A'),
                                'volume': float(pos.get('volume', 0)),
                                'profit': float(pos.get('profit', 0)),
                                'status': 'Open'
                            })
                except Exception as open_error:
                    logger.warning(f"Error fetching open positions for account {account_id}: {str(open_error)}")

            logger.info(f"Final result for account {account_id}: {len(trades)} trades found (closed + open)")
            for i, trade in enumerate(trades):
                logger.info(f"  Trade {i+1}: {trade['symbol']} - {trade['open_time']} - P/L: {trade['profit']} - Status: {trade.get('status', 'N/A')}")
            return trades
            
        except Exception as e:
            logger.error(f"Error fetching MT5 trades for account {account_id}: {str(e)}")
            return []

    def _get_historical_balance(self, account_id, date, current_balance=None):
        """
        Get historical balance for an account at a specific date.
        This calculates what the balance should have been at the start of the reporting period.
        """
        try:
            # Get transactions since the specified date to work backwards from current balance
            transactions_since_date = Transaction.objects.filter(
                trading_account__account_id=account_id,
                created_at__date__gt=date,
                status='approved'
            ).aggregate(
                deposits_since=Sum('amount', filter=Q(transaction_type__in=['deposit_trading', 'credit_in'])),
                withdrawals_since=Sum('amount', filter=Q(transaction_type__in=['withdraw_trading', 'credit_out']))
            )
            
            deposits_since = transactions_since_date['deposits_since'] or Decimal('0')
            withdrawals_since = transactions_since_date['withdrawals_since'] or Decimal('0')
            
            # If we have a current balance, work backwards
            if current_balance is not None and current_balance > 0:
                # Starting balance = Current balance - deposits since start + withdrawals since start
                calculated_starting = Decimal(str(current_balance)) - deposits_since + withdrawals_since
                
                logger.info(f"Account {account_id} balance calculation:")
                logger.info(f"  Current balance: {current_balance}")
                logger.info(f"  Deposits since {date}: {deposits_since}")
                logger.info(f"  Withdrawals since {date}: {withdrawals_since}")
                logger.info(f"  Calculated starting balance: {calculated_starting}")
                
                # Don't automatically set negative starting balances to 0
                # If the calculation shows negative, it likely means the account had no initial balance
                # and deposits exceeded the current balance due to trading losses
                if calculated_starting < 0:
                    logger.info(f"Calculated negative starting balance for account {account_id}")
                    # Check if this makes sense given the transaction history
                    if deposits_since > 0 and abs(calculated_starting) <= deposits_since:
                        # This suggests account started with 0, received deposits, but had trading losses
                        logger.info(f"Account likely started with $0, received deposits, with trading losses")
                        return Decimal('0')  # Return 0 as true starting balance
                    else:
                        logger.warning(f"Unexpected negative starting balance calculation, using absolute value")
                        return abs(calculated_starting)
                
                return calculated_starting
            
            # Fallback: Get all transactions up to the specified date
            historical_transactions = Transaction.objects.filter(
                trading_account__account_id=account_id,
                created_at__date__lte=date,
                status='approved'
            ).aggregate(
                deposits=Sum('amount', filter=Q(transaction_type__in=['deposit_trading', 'credit_in'])),
                withdrawals=Sum('amount', filter=Q(transaction_type__in=['withdraw_trading', 'credit_out']))
            )
            
            deposits = historical_transactions['deposits'] or Decimal('0')
            withdrawals = historical_transactions['withdrawals'] or Decimal('0')
            
            calculated_balance = deposits - withdrawals
            
            logger.info(f"Account {account_id} fallback calculation:")
            logger.info(f"  Deposits up to {date}: {deposits}")
            logger.info(f"  Withdrawals up to {date}: {withdrawals}")
            logger.info(f"  Calculated balance: {calculated_balance}")
            
            return max(calculated_balance, Decimal('0'))  # Ensure non-negative
            
        except Exception as e:
            logger.warning(f"Could not calculate historical balance for account {account_id}: {str(e)}")
            # If all else fails, return a reasonable starting balance based on current balance
            if current_balance is not None and current_balance > 0:
                # Assume most of the current balance was there at the start of the period
                return Decimal(str(current_balance)) * Decimal('0.9')  # Conservative estimate
            return Decimal('0')

    def _format_mt5_time(self, timestamp):
        """Format MT5 timestamp to readable string."""
        try:
            return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')
        except (ValueError, TypeError, OSError):
            return 'N/A'
    
    def _create_header(self, story):
        """
        Create a visually appealing report header with branding, title, and client info.
        """
        company_name = getattr(settings, 'COMPANY_NAME', 'VT Index')
        logo_path = getattr(settings, 'COMPANY_LOGO_PATH', None)

        # Add logo if available
        if logo_path and os.path.exists(logo_path):
            logo = Image(logo_path, width=1.2*inch, height=1.2*inch)
            logo.hAlign = 'LEFT'
            story.append(logo)

        # Title and period
        title = Paragraph(f"<b>{company_name} Trading Statement</b> – {self.start_date.strftime('%B %Y')}", self.title_style)
        story.append(title)
        story.append(Spacer(1, 10))

        # Client info block
        client_info = (
            f"<b>Client Name:</b> {self.user.get_full_name()}"
            f"&nbsp;&nbsp;&nbsp;&nbsp;<b>Account ID:</b> {self.user.user_id or self.user.id}"
        )
        client_para = Paragraph(client_info, self.normal_style)
        story.append(client_para)
        story.append(Spacer(1, 20))
    
    def _create_summary_section(self, story, data):
        """
        Add a summary section with balances and P/L, styled for clarity.
        """
        summary = data['summary']
        # Use a table for better alignment and visual appeal
        summary_data = [
            [Paragraph('<b>Starting Balance</b>', self.normal_style), f"$ {summary['starting_balance']:,.2f}"],
            [Paragraph('<b>Ending Balance</b>', self.normal_style), f"$ {summary['ending_balance']:,.2f}"],
            [Paragraph('<b>Total P/L</b>', self.normal_style), f"$ {summary['total_pnl']:,.2f}"]
        ]
        summary_table = Table(summary_data, colWidths=[2.5*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
            ('BACKGROUND', (0, 1), (-1, 1), colors.whitesmoke),
            ('BACKGROUND', (0, 2), (-1, 2), colors.beige),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.darkblue),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey)
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 20))
    
    def _create_trading_positions_section(self, story, data):
        """
        Add a detailed, styled table of trading positions.
        """
        positions = data['trading_positions']
        if not positions:
            story.append(Paragraph("No trading positions found for this period.", self.normal_style))
            story.append(Spacer(1, 20))
            return

        # Section separator
        story.append(Spacer(1, 10))
        story.append(Paragraph("<b>Trade Details</b>", self.subtitle_style))
        story.append(Paragraph("<font color='grey'>-------------------------------------------------------------</font>", self.normal_style))

        # Table headers and data
        pos_data = [[
            Paragraph('<b>Open Time</b>', self.normal_style),
            Paragraph('<b>Close Time</b>', self.normal_style),
            Paragraph('<b>Symbol</b>', self.normal_style),
            Paragraph('<b>Lots</b>', self.normal_style),
            Paragraph('<b>P/L</b>', self.normal_style)
        ]]
        for position in positions:
            pos_data.append([
                position.get('open_time', 'N/A'),
                position.get('close_time', 'N/A'),
                position.get('symbol', 'N/A'),
                f"{position.get('lots', 0):.2f}",
                f"{position.get('pnl', 0):,.2f}"
            ])

        pos_table = Table(pos_data, colWidths=[1.5*inch, 1.5*inch, 1*inch, 0.8*inch, 1*inch])
        pos_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('ALIGN', (0, 1), (-2, -1), 'CENTER'),
            ('ALIGN', (4, 1), (4, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey)
        ]))
        story.append(pos_table)
        story.append(Spacer(1, 20))
    
    def _create_commission_section(self, story, data):
        """Create commission earnings section for IB users"""
        if not self.user.IB_status or not data['commission_transactions']:
            return
        
        story.append(Paragraph("Commission Earnings (IB)", self.subtitle_style))
        
        # Create commission table
        comm_data = [['Date', 'Client', 'Symbol', 'Level', 'Commission']]
        
        for comm in data['commission_transactions']:
            comm_data.append([
                comm.created_at.strftime('%d/%m/%Y'),
                comm.client_user.get_full_name(),
                comm.position_symbol,
                f"Level {comm.ib_level}",
                f"${comm.commission_to_ib:,.2f}"
            ])
        
        comm_table = Table(comm_data, colWidths=[1*inch, 2*inch, 1*inch, 1*inch, 1.5*inch])
        comm_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (4, 1), (4, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
        ]))
        
        story.append(comm_table)
        story.append(Spacer(1, 20))
    
    def _create_footer(self, story):
        """
        Add a professional, branded footer with notices and contact info.
        """
        story.append(Spacer(1, 30))
        notices = (
            "<b>Important Notices:</b><br/>"
            "• This report is confidential and intended solely for the named recipient.<br/>"
            "• Trading involves substantial risk of loss and is not suitable for all investors.<br/>"
            "• Past performance is not indicative of future results.<br/>"
            "• Please verify all transactions with your MT5 platform records.<br/>"
            "• For questions about this report, contact our support team.<br/><br/>"
        )
        contact = (
            "<b>Contact Information:</b><br/>"
            "Email: <font color='blue'>support@vtindex.com</font><br/>"
            "Website: <font color='blue'>www.vtindex.com</font>"
        )
        footer = Paragraph(notices + contact, self.small_style)
        story.append(footer)
    
    def generate_pdf(self, output_path=None):
        """
        Generate the PDF report using the HTML/CSS template (WeasyPrint).
        Args:
            output_path: Optional path to save the PDF. If None, creates a temp file.
        Returns:
            str: Path to the generated PDF file
        """
        return self.generate_html_pdf_report(output_path)
    
    def encrypt_pdf(self, input_path, password, output_path=None):
        """
        Encrypt PDF with password using pikepdf
        
        Args:
            input_path: Path to the unencrypted PDF
            password: Password to encrypt the PDF with
            output_path: Optional path for encrypted PDF. If None, overwrites input.
            
        Returns:
            str: Path to the encrypted PDF file
        """
        try:
            if not PIKEPDF_AVAILABLE:
                logger.warning("pikepdf not available, returning unencrypted PDF")
                return input_path
                
            if output_path is None:
                output_path = input_path
            
            # Open the PDF and encrypt it
            with pikepdf.open(input_path) as pdf:
                # Set encryption with user password
                pdf.save(
                    output_path,
                    encryption=pikepdf.Encryption(
                        user=password,
                        owner=password,
                        R=4,  # Encryption revision
                        allow=pikepdf.Permissions(
                            accessibility=True,
                            extract=False,
                            modify_annotation=False,
                            modify_assembly=False,
                            modify_form=False,
                            modify_other=False,
                            print_lowres=True,
                            print_highres=True
                        )
                    )
                )
            
            # Remove unencrypted file if different paths
            if input_path != output_path and os.path.exists(input_path):
                os.remove(input_path)
            
            logger.info(f"PDF encrypted successfully: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error encrypting PDF: {str(e)}")
            # Return unencrypted file if encryption fails
            return input_path
    
    def generate_encrypted_report(self, output_path=None):
        """
        Generate and encrypt the complete monthly report
        
        Args:
            output_path: Optional path to save the encrypted PDF
        Returns:
            Tuple[str, str]: Path to the encrypted PDF and the password used
        """
        try:
            # Generate unencrypted PDF first
            unencrypted_path = self.generate_pdf()
            # Use centralized password logic
            password = self.generate_report_password(self.user)
            # logger.info(f"[PDF PASSWORD] For user {self.user.email}: {password}")
            # Encrypt the PDF
            if output_path is None:
                # Create encrypted filename
                base_name = os.path.splitext(unencrypted_path)[0]
                output_path = f"{base_name}_encrypted.pdf"
            encrypted_path = self.encrypt_pdf(unencrypted_path, password, output_path)
            return encrypted_path, password
        except Exception as e:
            logger.error(f"Error generating encrypted report: {str(e)}")
            raise
