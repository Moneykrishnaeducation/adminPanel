from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db.models import Sum

from adminPanel.models import CustomUser, CommissionTransaction, Transaction


class Command(BaseCommand):
    help = "Compute withdrawable IB commission for a user or all IBs."

    def add_arguments(self, parser):
        parser.add_argument('--user', '-u', help='User identifier (user_id or email). If omitted, computes for all IB users')
        parser.add_argument('--csv', '-c', help='Path to CSV output file. If provided, writes rows (user_id,email,total,withdrawn_approved,pending,withdrawable)')

    def handle(self, *args, **options):
        user_identifier = options.get('user')
        csv_path = options.get('csv')

        def lookup_user(identifier):
            try:
                uid = int(identifier)
            except Exception:
                uid = None
            user = None
            if uid is not None:
                user = CustomUser.objects.filter(user_id=uid).first() or CustomUser.objects.filter(pk=uid).first()
            if not user:
                user = CustomUser.objects.filter(email=identifier).first()
            return user

        users = []
        if user_identifier:
            user = lookup_user(user_identifier)
            if not user:
                self.stdout.write(self.style.ERROR(f'No user found for identifier: {user_identifier}'))
                return
            users = [user]
        else:
            users = CustomUser.objects.filter(IB_status=True).all()

        rows = []
        for user in users:
            total_comm = CommissionTransaction.objects.filter(ib_user=user).aggregate(total=Sum('commission_to_ib'))['total'] or Decimal('0.00')
            withdrawn_approved = Transaction.objects.filter(user=user, transaction_type='commission_withdrawal', status__iexact='approved').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            withdrawn_pending = Transaction.objects.filter(user=user, transaction_type='commission_withdrawal', status__iexact='pending').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            withdrawable = (total_comm or Decimal('0.00')) - (withdrawn_approved or Decimal('0.00'))

            rows.append((user.user_id, user.email, total_comm, withdrawn_approved, withdrawn_pending, withdrawable))

            self.stdout.write(f"User: {user.email} (user_id={user.user_id})")
            self.stdout.write(f"  Total commission: {total_comm:.2f}")
            self.stdout.write(f"  Withdrawn (approved): {withdrawn_approved:.2f}")
            self.stdout.write(f"  Pending: {withdrawn_pending:.2f}")
            self.stdout.write(f"  Withdrawable: {withdrawable:.2f}\n")

        if csv_path:
            try:
                import csv
                with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
                    writer = csv.writer(fh)
                    writer.writerow(['user_id', 'email', 'total_commission', 'withdrawn_approved', 'withdrawn_pending', 'withdrawable'])
                    for r in rows:
                        writer.writerow([r[0], r[1], f"{r[2]:.2f}", f"{r[3]:.2f}", f"{r[4]:.2f}", f"{r[5]:.2f}"])
                self.stdout.write(self.style.SUCCESS(f'Wrote CSV to {csv_path}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to write CSV: {e}'))
