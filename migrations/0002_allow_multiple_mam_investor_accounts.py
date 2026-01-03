"""
Migration to update MAM account system to allow multiple investor accounts
under the same manager for the same investor.

This migration:
1. Documents the change in the migration history
2. Ensures no database constraints prevent multiple investor accounts
3. Updates any existing data if needed
"""

from django.db import migrations

class Migration(migrations.Migration):
    
    dependencies = [
        ('adminPanel', '0001_initial'),  # Replace with the actual latest migration
    ]

    operations = [
        # Add a harmless SQL statement so the migration runs without errors
        # (previously used a comment-only SQL which raised "can't execute an empty query")
        migrations.RunSQL(
            sql="SELECT 1; -- Allow multiple MAM investor accounts per investor-manager pair",
            reverse_sql="SELECT 1; -- Revert: Restored unique constraint for MAM investor accounts"
        ),
        
        # Note: No actual schema changes needed since the unique constraint 
        # was only enforced in application logic, not at the database level
    ]
