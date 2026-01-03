from django.db import migrations


def dedupe_commissiontransactions(apps, schema_editor):
    """Remove duplicate CommissionTransaction rows that would violate the
    new unique constraint. Keeps the row with the smallest id for each
    duplicate group (position_id, client_trading_account_id, ib_user_id, ib_level).
    """
    # Use the historical model via apps to perform ORM-based deduplication which
    # avoids quoting/table-name issues across different databases.
    CommissionTransaction = apps.get_model('adminPanel', 'CommissionTransaction')

    from django.db.models import Count, Min

    duplicate_groups = (
        CommissionTransaction.objects
        .values('position_id', 'client_trading_account_id', 'ib_user_id', 'ib_level')
        .annotate(min_id=Min('id'), cnt=Count('id'))
        .filter(cnt__gt=1)
    )

    for grp in duplicate_groups:
        keep_id = grp['min_id']
        CommissionTransaction.objects.filter(
            position_id=grp['position_id'],
            client_trading_account_id=grp['client_trading_account_id'],
            ib_user_id=grp['ib_user_id'],
            ib_level=grp['ib_level'],
        ).exclude(id=keep_id).delete()


def noop_reverse(apps, schema_editor):
    # No reverse operation: once duplicates are removed it's difficult to restore them.
    return


class Migration(migrations.Migration):

    dependencies = [
        ('adminPanel', '0034_commissiontransaction_lot_size_and_more'),
    ]

    operations = [
        migrations.RunPython(dedupe_commissiontransactions, reverse_code=noop_reverse),
        migrations.AlterUniqueTogether(
            name='commissiontransaction',
            unique_together={( 'position_id', 'client_trading_account', 'ib_user', 'ib_level'),},
        ),
    ]
