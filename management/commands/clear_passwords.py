"""
Django management command to clear all user passwords.
Run with: python manage.py clear_passwords
"""

from django.core.management.base import BaseCommand
from adminPanel.models import CustomUser


class Command(BaseCommand):
    help = 'Clear all user passwords by setting them to unusable state (properly hashed)'

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.SUCCESS("CRM Password Clearing Command"))
        self.stdout.write("=" * 60)
        
        # Get all users
        all_users = CustomUser.objects.all()
        total_users = all_users.count()
        
        self.stdout.write(f"\nFound {total_users} users in the database.")
        self.stdout.write(self.style.WARNING(f"\n⚠️  This will make ALL {total_users} user passwords unusable."))
        self.stdout.write("   Users will need to reset their passwords to login again.\n")
        
        # Confirmation
        confirm = input("Type 'YES' to continue: ")
        
        if confirm != 'YES':
            self.stdout.write(self.style.ERROR("\n❌ Operation cancelled."))
            return
        
        self.stdout.write("\n🔄 Processing users...")
        
        updated_count = 0
        
        for user in all_users:
            # Set password to unusable (creates a hashed unusable password)
            user.set_unusable_password()
            user.save(update_fields=['password'])
            updated_count += 1
            
            if updated_count % 10 == 0:
                self.stdout.write(f"   Processed {updated_count}/{total_users} users...")
        
        self.stdout.write(self.style.SUCCESS(f"\n✅ Successfully cleared passwords for {updated_count} users."))
        self.stdout.write("   All passwords are now set to unusable state (properly hashed).")
        self.stdout.write("\n📝 Note: Users will need to use password reset to set new passwords.")
        self.stdout.write("=" * 60)
