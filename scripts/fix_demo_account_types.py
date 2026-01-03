from adminPanel.models import TradingAccount
from django.db import transaction

def fix_demo_account_types():
    with transaction.atomic():
        # Print all unique account_type values
        unique_types = TradingAccount.objects.values_list('account_type', flat=True).distinct()
        print('Unique account_type values before:', list(unique_types))
        # Fix any variants of 'demo' to 'demo'
        demo_variants = ['Demo', 'DEMO', 'dem', 'Dem', 'dEmo', 'dEMO']
        updated = TradingAccount.objects.filter(account_type__in=demo_variants).update(account_type='demo')
        print(f'Updated {updated} accounts to account_type="demo"')
        # Print all unique account_type values after
        unique_types_after = TradingAccount.objects.values_list('account_type', flat=True).distinct()
        print('Unique account_type values after:', list(unique_types_after))

if __name__ == '__main__':
    fix_demo_account_types()
