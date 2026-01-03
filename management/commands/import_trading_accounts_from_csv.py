import csv
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime, parse_date
from datetime import datetime
from adminPanel.models import TradingAccount, CustomUser, Package
from django.db import transaction
from decimal import Decimal
from django.utils import timezone

CSV_FILE = 'TradingAccounts_2025-07-31_10-28-14.csv'

class Command(BaseCommand):
    help = 'Import trading accounts from CSV and map to TradingAccount model.'

    def handle(self, *args, **options):
        with open(CSV_FILE, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            count = 0
            with transaction.atomic():
                for row in reader:
                    user_id = int(row['user_id']) if row.get('user_id') else None
                    user = CustomUser.objects.filter(user_id=user_id).first() if user_id else None

                    # If user lookup by user_id failed, try common email fields as fallback
                    if not user:
                        email_candidate = (row.get('email') or row.get('user_email') or row.get('user') or None)
                        # Sometimes account_name holds an email in legacy CSVs
                        if not email_candidate and row.get('account_name') and '@' in row.get('account_name'):
                            email_candidate = row.get('account_name')
                        if email_candidate:
                            user = CustomUser.objects.filter(email=email_candidate).first()
                        if not user:
                            self.stdout.write(self.style.WARNING(f'Skipping trading account {row.get("account_id")} for user {user_id or email_candidate}: no matching user found.'))
                            continue
                    account_id = row['account_id']
                    account_type = row['account_type'] or 'standard'
                    account_name = row['account_name'] or ''
                    leverage = int(row['leverage']) if row['leverage'] else 100
                    balance = Decimal(row['balance']) if row['balance'] else Decimal('0.00')
                    is_enabled = row['is_enabled'].lower() == 'true' if row['is_enabled'] else True
                    is_trading_enabled = row['is_trading_enabled'].lower() == 'true' if row['is_trading_enabled'] else True
                    # Preserve CSV created_at when provided; accept full ISO datetime or date-only
                    created_at_raw = row['created_at'] or None
                    created_at = None
                    if created_at_raw and str(created_at_raw).lower() != 'none':
                        created_at = parse_datetime(created_at_raw)
                        if not created_at:
                            parsed_date = parse_date(created_at_raw)
                            if parsed_date:
                                created_at = datetime.combine(parsed_date, datetime.min.time())
                                try:
                                    created_at = timezone.make_aware(created_at)
                                except Exception:
                                    pass
                        # Diagnostic: show if parsing succeeded and what value we got
                        if created_at:
                            self.stdout.write(self.style.NOTICE(f"Parsed TradingAccount.created_at for account {row.get('account_id')}: {created_at} (raw: {created_at_raw})"))
                        else:
                            self.stdout.write(self.style.WARNING(f"Could not parse TradingAccount.created_at for account {row.get('account_id')}: raw value '{created_at_raw}' - will use current time"))
                    if not created_at:
                        created_at = timezone.now()
                    group_name = row['group_name'] or None
                    manager_allow_copy = row['manager_allow_copy'].lower() == 'true' if row['manager_allow_copy'] else True
                    investor_allow_copy = row['investor_allow_copy'].lower() == 'true' if row['investor_allow_copy'] else True
                    mam_master_account_id = row['mam_master_account_id'] or None
                    mam_master_account = TradingAccount.objects.filter(account_id=mam_master_account_id).first() if mam_master_account_id else None
                    profit_sharing_percentage = Decimal(row['profit_sharing_percentage']) if row['profit_sharing_percentage'] else None
                    risk_level = row['risk_level'] or None
                    is_algo_enabled = row['is_algo_enabled'].lower() == 'true' if row['is_algo_enabled'] else False
                    payout_frequency = row['payout_frequency'] or None
                    package_id = row['package_id'] or None
                    package = Package.objects.filter(id=package_id).first() if package_id else None
                    status = row['status'] or 'running'
                    approved_by_user_id = int(row['approved_by_user_id']) if row['approved_by_user_id'] else None
                    approved_by = CustomUser.objects.filter(user_id=approved_by_user_id).first() if approved_by_user_id else None
                    # Parse optional datetime fields similarly
                    approved_at_raw = row['approved_at'] or None
                    approved_at = None
                    if approved_at_raw and str(approved_at_raw).lower() != 'none':
                        approved_at = parse_datetime(approved_at_raw)
                        if not approved_at:
                            parsed_date = parse_date(approved_at_raw)
                            if parsed_date:
                                approved_at = datetime.combine(parsed_date, datetime.min.time())
                                try:
                                    approved_at = timezone.make_aware(approved_at)
                                except Exception:
                                    pass

                    start_date_raw = row['start_date'] or None
                    start_date = None
                    if start_date_raw and str(start_date_raw).lower() != 'none':
                        start_date = parse_datetime(start_date_raw)
                        if not start_date:
                            parsed_date = parse_date(start_date_raw)
                            if parsed_date:
                                start_date = datetime.combine(parsed_date, datetime.min.time())
                                try:
                                    start_date = timezone.make_aware(start_date)
                                except Exception:
                                    pass

                    end_date_raw = row['end_date'] or None
                    end_date = None
                    if end_date_raw and str(end_date_raw).lower() != 'none':
                        end_date = parse_datetime(end_date_raw)
                        if not end_date:
                            parsed_date = parse_date(end_date_raw)
                            if parsed_date:
                                end_date = datetime.combine(parsed_date, datetime.min.time())
                                try:
                                    end_date = timezone.make_aware(end_date)
                                except Exception:
                                    pass

                    # If mam_investment, must have a valid mam_master_account
                    if account_type == 'mam_investment' and not mam_master_account:
                        self.stdout.write(self.style.WARNING(f'Skipping mam_investment account {account_id} for user {user_id}: missing or invalid mam_master_account.'))
                        continue

                    ta_obj, ta_created = TradingAccount.objects.update_or_create(
                        account_id=account_id,
                        defaults={
                            'user': user,
                            'account_type': account_type,
                            'account_name': account_name,
                            'leverage': leverage,
                            'balance': balance,
                            'is_enabled': is_enabled,
                            'is_trading_enabled': is_trading_enabled,
                            'group_name': group_name,
                            'manager_allow_copy': manager_allow_copy,
                            'investor_allow_copy': investor_allow_copy,
                            'mam_master_account': mam_master_account,
                            'profit_sharing_percentage': profit_sharing_percentage,
                            'risk_level': risk_level,
                            'is_algo_enabled': is_algo_enabled,
                            'payout_frequency': payout_frequency,
                            'package': package,
                            'status': status,
                            'approved_by': approved_by,
                            'approved_at': approved_at,
                            'start_date': start_date,
                            'end_date': end_date,
                        }
                    )

                    # Explicitly set created_at from CSV on the instance to ensure preservation even if auto_now_add is set.
                    try:
                        if created_at:
                            # Only update if it's different to avoid unnecessary writes
                            old_val = getattr(ta_obj, 'created_at', None)
                            if old_val != created_at:
                                ta_obj.created_at = created_at
                                ta_obj.save(update_fields=['created_at'])
                                self.stdout.write(self.style.SUCCESS(f"Set TradingAccount(id={ta_obj.account_id}) created_at: {old_val} -> {created_at}"))
                    except Exception as e:
                        # Defensive: ignore failures to set created_at but continue import
                        self.stdout.write(self.style.ERROR(f"Failed to set created_at for TradingAccount {account_id}: {e}"))
                    count += 1
            self.stdout.write(self.style.SUCCESS(f'Successfully imported/updated {count} trading accounts.'))
