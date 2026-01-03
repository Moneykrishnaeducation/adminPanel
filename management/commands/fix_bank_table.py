from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Add missing columns to clientPanel_bankdetails table'

    def handle(self, *args, **options):
        self.stdout.write("🔧 Fixing clientPanel_bankdetails table...")
        
        with connection.cursor() as cursor:
            # Add ifsc_code column if it doesn't exist
            try:
                cursor.execute("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'clientPanel_bankdetails' 
                    AND column_name = 'ifsc_code'
                """)
                
                if not cursor.fetchone():
                    cursor.execute("""
                        ALTER TABLE clientPanel_bankdetails 
                        ADD COLUMN ifsc_code VARCHAR(20)
                    """)
                    self.stdout.write(
                        self.style.SUCCESS('✅ Added ifsc_code column')
                    )
                else:
                    self.stdout.write("✅ ifsc_code column already exists")
                    
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'❌ Error adding ifsc_code: {e}')
                )
            
            # Add branch_name column if it doesn't exist
            try:
                cursor.execute("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'clientPanel_bankdetails' 
                    AND column_name = 'branch_name'
                """)
                
                if not cursor.fetchone():
                    cursor.execute("""
                        ALTER TABLE clientPanel_bankdetails 
                        ADD COLUMN branch_name VARCHAR(100)
                    """)
                    self.stdout.write(
                        self.style.SUCCESS('✅ Added branch_name column')
                    )
                else:
                    self.stdout.write("✅ branch_name column already exists")
                    
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'❌ Error adding branch_name: {e}')
                )
        
        # Test the model
        try:
            from clientPanel.models import BankDetails
            count = BankDetails.objects.count()
            self.stdout.write(
                self.style.SUCCESS(f'✅ BankDetails model test passed! {count} records found')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Model test failed: {e}')
            )
        
        self.stdout.write("🎉 Database fix completed!")
