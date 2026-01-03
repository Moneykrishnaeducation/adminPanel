from django.core.management.base import BaseCommand
from adminPanel.models import CommissionTransaction
from decimal import Decimal

class Command(BaseCommand):
    help = 'Fix all negative IB commissions by making them positive.'

    def handle(self, *args, **options):
        count = 0
        for ct in CommissionTransaction.objects.filter(commission_to_ib__lt=0):
            ct.commission_to_ib = abs(ct.commission_to_ib)
            ct.total_commission = abs(ct.total_commission)
            ct.save(update_fields=['commission_to_ib', 'total_commission'])
            count += 1
        self.stdout.write(self.style.SUCCESS(f'Fixed {count} negative IB commissions.'))
