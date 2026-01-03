What changed

- Added a DB uniqueness constraint to `CommissionTransaction` to prevent duplicate records for the same position/account/IB level.
- `create_commission` now uses `get_or_create` and updates missing `lot_size`/`profit` without duplicating records.
- Management commands `sync_commissions_from_mt5` and `backfill_commissions_from_mt5` now catch `IntegrityError` and handle duplicates gracefully.
- The `create_test_commission` command now uses `get_or_create`.

Migrations

You must create and apply a Django migration to add the new unique constraint:

```powershell
python manage.py makemigrations adminPanel
python manage.py migrate
```

Notes

- The uniqueness constraint will cause an IntegrityError if duplicates already exist. If your DB currently has duplicate rows for the same `(position_id, client_trading_account, ib_user, ib_level)`, you must deduplicate before running the migration. Example SQL (Postgres):

```sql
-- Find duplicates
SELECT position_id, client_trading_account_id, ib_user_id, ib_level, COUNT(*)
FROM adminPanel_commissiontransaction
GROUP BY position_id, client_trading_account_id, ib_user_id, ib_level
HAVING COUNT(*) > 1;

-- Keep the earliest id per group and delete others (use with care)
DELETE FROM adminPanel_commissiontransaction a
USING (
  SELECT MIN(id) as keep_id, position_id, client_trading_account_id, ib_user_id, ib_level
  FROM adminPanel_commissiontransaction
  GROUP BY position_id, client_trading_account_id, ib_user_id, ib_level
  HAVING COUNT(*) > 1
) b
WHERE a.position_id = b.position_id
  AND a.client_trading_account_id = b.client_trading_account_id
  AND a.ib_user_id = b.ib_user_id
  AND a.ib_level = b.ib_level
  AND a.id <> b.keep_id;
```

- Avoid running multiple concurrent sync/backfill processes while migrating; the commands are now resilient but migrations may fail if duplicates exist.

If you'd like, I can:
- Create a migration file and attempt to run it here (requires DB connection), or
- Add a management command to deduplicate existing rows before migration.
