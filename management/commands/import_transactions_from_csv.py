import csv
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime, parse_date
from datetime import datetime
from adminPanel.models import Transaction, TradingAccount, CustomUser
from django.db import transaction
from decimal import Decimal
from django.utils import timezone

CSV_FILE = 'Transactions_2025-07-31_10-28-51.csv'

class Command(BaseCommand):
    help = 'Import transactions from CSV and map to Transaction model.'

    def handle(self, *args, **options):
        with open(CSV_FILE, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            count = 0
            skipped = 0
            with transaction.atomic():
                for row in reader:
                    user_id = int(row['user_id']) if row['user_id'] else None
                    user = CustomUser.objects.filter(user_id=user_id).first() if user_id else None
                    trading_account_id = row['trading_account_id'] or None
                    trading_account = TradingAccount.objects.filter(account_id=trading_account_id).first() if trading_account_id else None

                    # Fallbacks to resolve user when user_id is missing or lookup failed.
                    # 1) If trading_account exists, use its user.
                    # 2) If CSV contains user_email or user_username, try to resolve by email/username.
                    # 3) If still unresolved, skip the row to avoid NOT NULL constraint errors.
                    if not user:
                        if trading_account and getattr(trading_account, 'user', None):
                            user = trading_account.user
                        else:
                            user_email = row.get('user_email') or None
                            user_username = row.get('user_username') or None
                            if user_email:
                                user = CustomUser.objects.filter(email__iexact=user_email).first()
                            if not user and user_username:
                                user = CustomUser.objects.filter(username__iexact=user_username).first()
                    if not user:
                        # Nothing we can do safely — log and skip this transaction row.
                        self.stdout.write(self.style.WARNING(
                            f"Skipping transaction id={row.get('id')} at {row.get('created_at')} because user could not be resolved (user_id={row.get('user_id')}, email={row.get('user_email')})."
                        ))
                        skipped += 1
                        continue

                    transaction_type = row['transaction_type'] or None
                    amount = Decimal(row['amount']) if row['amount'] else Decimal('0.00')
                    description = row['description'] or ''
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
                        if created_at:
                            self.stdout.write(self.style.NOTICE(f"Parsed Transaction.created_at for csv id={row.get('id')} trading_account={trading_account_id}: {created_at} (raw: {created_at_raw})"))
                        else:
                            self.stdout.write(self.style.WARNING(f"Could not parse Transaction.created_at for csv id={row.get('id')}: raw value '{created_at_raw}' - will use current time"))
                    if not created_at:
                        created_at = timezone.now()
                    status = row['status'] or 'pending'
                    approved_by_user_id = int(row['approved_by_user_id']) if row['approved_by_user_id'] else None
                    approved_by = CustomUser.objects.filter(user_id=approved_by_user_id).first() if approved_by_user_id else None
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
                    payout_to = row['payout_to'] or None
                    external_account = row['external_account'] or None
                    from_account_id = row['from_account_id'] or None
                    from_account = TradingAccount.objects.filter(account_id=from_account_id).first() if from_account_id else None
                    to_account_id = row['to_account_id'] or None
                    to_account = TradingAccount.objects.filter(account_id=to_account_id).first() if to_account_id else None
                    document = row['document'] or None  # FileField, skip for now

                    # Skip internal_transfer if from_account or to_account is missing
                    if transaction_type == 'internal_transfer' and (not from_account or not to_account):
                        self.stdout.write(self.style.WARNING(f"Skipping internal_transfer transaction for user {user_id} at {created_at}: missing from_account or to_account."))
                        skipped += 1
                        continue

                    tx_obj, tx_created = Transaction.objects.update_or_create(
                        user=user,
                        trading_account=trading_account,
                        transaction_type=transaction_type,
                        amount=amount,
                        defaults={
                            'source': row['source'] or None,
                            'description': description,
                            'status': status,
                            'approved_by': approved_by,
                            'approved_at': approved_at,
                            'payout_to': payout_to,
                            'external_account': external_account,
                            'from_account': from_account,
                            'to_account': to_account,
                            # 'document': document,  # FileField, handle separately if needed
                        }
                    )

                    # Explicitly set created_at/approved_at from CSV when present.
                    try:
                        changed = False
                        old_created = getattr(tx_obj, 'created_at', None)
                        old_approved = getattr(tx_obj, 'approved_at', None)
                        if created_at and old_created != created_at:
                            tx_obj.created_at = created_at
                            changed = True
                        if approved_at and old_approved != approved_at:
                            tx_obj.approved_at = approved_at
                            changed = True
                        if changed:
                            fields = []
                            if created_at:
                                fields.append('created_at')
                            if approved_at:
                                fields.append('approved_at')
                            tx_obj.save(update_fields=fields)
                            self.stdout.write(self.style.SUCCESS(f"Set Transaction(id={tx_obj.id}) timestamps: created_at {old_created} -> {created_at}, approved_at {old_approved} -> {approved_at}"))
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"Failed to set timestamps for Transaction CSV id={row.get('id')}: {e}"))
                    count += 1
            self.stdout.write(self.style.SUCCESS(f'Successfully imported/updated {count} transactions. Skipped {skipped} rows due to unresolved users or validation.'))
