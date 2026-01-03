from decimal import Decimal
import logging

from django.core.management.base import BaseCommand
from django.db.models import Q

from adminPanel.models import CustomUser, TradingAccount
from adminPanel.mt5.services import MT5ManagerActions

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Detect discrepancies between DB commission balance and MT5 account balance for IB users"

    def add_arguments(self, parser):
        parser.add_argument('--threshold', type=float, default=1.0,
                            help='Minimum absolute difference to report (default: 1.0)')
        parser.add_argument('--limit', type=int, default=0,
                            help='Limit number of IB users to check (0 = no limit)')
        parser.add_argument('--verbose', action='store_true', help='Verbose output')
        parser.add_argument('--use-trading-balance', action='store_true', help='Use TradingAccount.balance as fallback DB balance when commission totals are zero')

    def handle(self, *args, **options):
        threshold = Decimal(str(options.get('threshold') or 1.0))
        limit = options.get('limit') or 0
        verbose = options.get('verbose')
        use_trading_balance = options.get('use_trading_balance') or False

        self.stdout.write('Starting IB commission balance detection...')

        mt5 = None
        try:
            mt5 = MT5ManagerActions()
        except Exception as e:
            logger.warning(f'Failed to initialize MT5 manager: {e}')
            # proceed - get_balance will handle missing manager

        # Candidate IB users: either flagged as IB, referenced as parent_ib (clients), or have commission txns
        qs = CustomUser.objects.filter(
            Q(IB_status=True) | Q(clients__isnull=False) | Q(commission_transactions_as_ib__isnull=False)
        ).distinct()

        total_with_account = qs.filter(trading_accounts__isnull=False).distinct().count()
        self.stdout.write(f'Found {qs.count()} candidate IB users ({total_with_account} with a trading account)')

        if limit and limit > 0:
            qs = qs[:limit]

        problems = []

        for user in qs:
            try:
                # DB-side commission balance (earnings - withdrawals)
                commission_balance = (user.total_earnings - user.total_commission_withdrawals) if user else Decimal('0.00')
                commission_balance = Decimal(commission_balance).quantize(Decimal('0.01'))

                # Optional: use TradingAccount.balance sum as a fallback
                trading_balance = Decimal('0.00')
                if use_trading_balance:
                    try:
                        balances = [Decimal(str(t.balance or 0)) for t in user.trading_accounts.all()]
                        if balances:
                            trading_balance = sum(balances)
                    except Exception:
                        trading_balance = Decimal('0.00')

                if use_trading_balance and trading_balance != Decimal('0.00'):
                    db_balance = trading_balance.quantize(Decimal('0.01'))
                else:
                    db_balance = commission_balance

                # Resolve MT5 account id from related TradingAccount (read-only)
                account_id = None
                try:
                    ta = user.trading_accounts.first()
                    if ta:
                        account_id = getattr(ta, 'account_id', None)
                except Exception:
                    account_id = None

                mt5_balance = Decimal('0.00')
                try:
                    if account_id and mt5 and hasattr(mt5, 'get_balance'):
                        mt5_val = mt5.get_balance(account_id)
                        mt5_balance = Decimal(str(mt5_val or 0)).quantize(Decimal('0.01'))
                except Exception as e:
                    logger.warning(f'Error fetching MT5 balance for {user.email} (acct={account_id}): {e}')

                diff = (mt5_balance - db_balance).quantize(Decimal('0.01'))

                if verbose or abs(diff) >= threshold:
                    problems.append({
                        'user_id': user.user_id,
                        'email': user.email,
                        'account_id': account_id,
                        'db_balance': float(db_balance),
                        'mt5_balance': float(mt5_balance),
                        'difference': float(diff),
                    })

                    self.stdout.write(f"User {user.user_id} {user.email} acct={account_id} DB={db_balance} MT5={mt5_balance} DIFF={diff}")

            except Exception as e:
                logger.exception(f'Error processing user {getattr(user, "email", "<unknown>")}: {e}')

        self.stdout.write('\nSummary:')
        if not problems:
            self.stdout.write('No discrepancies found (above threshold)')
            # If no user-based problems, still optionally scan trading accounts with non-zero balances
            if not use_trading_balance:
                return

        # Optionally include standalone TradingAccount rows (non-zero balances) when requested
        if use_trading_balance:
            try:
                tas = TradingAccount.objects.filter(balance__gt=0).all()
                for ta in tas:
                    try:
                        acct_id = getattr(ta, 'account_id', None)
                        db_bal = Decimal(str(ta.balance or 0)).quantize(Decimal('0.01'))
                        mt5_bal = Decimal('0.00')
                        if acct_id and mt5 and hasattr(mt5, 'get_balance'):
                            try:
                                mval = mt5.get_balance(acct_id)
                                mt5_bal = Decimal(str(mval or 0)).quantize(Decimal('0.01'))
                            except Exception:
                                mt5_bal = Decimal('0.00')

                        diff2 = (mt5_bal - db_bal).quantize(Decimal('0.01'))
                        if verbose or abs(diff2) >= threshold:
                            owner = getattr(ta, 'user', None)
                            problems.append({
                                'user_id': getattr(owner, 'user_id', None),
                                'email': getattr(owner, 'email', None),
                                'account_id': acct_id,
                                'db_balance': float(db_bal),
                                'mt5_balance': float(mt5_bal),
                                'difference': float(diff2),
                            })
                            self.stdout.write(f"TradingAccount {acct_id} owner={getattr(owner,'email',None)} DB={db_bal} MT5={mt5_bal} DIFF={diff2}")
                    except Exception as e:
                        logger.exception(f'Error processing trading account {getattr(ta, "account_id", "<unknown>")}: {e}')
            except Exception as e:
                logger.exception(f'Error querying TradingAccount rows: {e}')

        self.stdout.write(f'Total flagged users: {len(problems)}')

        # Print a compact table
        self.stdout.write('\n{:<8} {:<30} {:<12} {:>12} {:>12} {:>12}'.format('UserID', 'Email', 'AcctID', 'DB', 'MT5', 'Diff'))
        for p in problems:
            self.stdout.write('{:<8} {:<30} {:<12} {:>12.2f} {:>12.2f} {:>12.2f}'.format(
                p['user_id'], p['email'][:29], str(p['account_id'] or ''), p['db_balance'], p['mt5_balance'], p['difference']
            ))

        self.stdout.write('\nDetection completed.')
