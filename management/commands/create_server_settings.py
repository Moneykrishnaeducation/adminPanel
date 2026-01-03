from django.core.management.base import BaseCommand
from adminPanel.models import ServerSetting

class Command(BaseCommand):
    help = 'Create default MT5 server settings'

    def handle(self, *args, **options):
        # Check if ServerSetting already exists
        if ServerSetting.objects.exists():
            setting = ServerSetting.objects.first()
            self.stdout.write(
                self.style.SUCCESS(f'✅ ServerSetting already exists:')
            )
            self.stdout.write(f'   Server IP: {setting.server_ip}')
            self.stdout.write(f'   Server Name: {setting.server_name}')
            self.stdout.write(f'   Login ID: {setting.login_id}')
            return

        # Create default server settings
        try:
            server_setting = ServerSetting.objects.create(
                server_ip="127.0.0.1",  # Default localhost
                server_name="MT5 Demo Server",  # Default name
                login_id=1000,  # Default login ID
                server_password="password123"  # Default password (change this!)
            )
            
            self.stdout.write(
                self.style.SUCCESS('✅ Created default ServerSetting:')
            )
            self.stdout.write(f'   Server IP: {server_setting.server_ip}')
            self.stdout.write(f'   Server Name: {server_setting.server_name}')
            self.stdout.write(f'   Login ID: {server_setting.login_id}')
            self.stdout.write('   Password: [HIDDEN]')
            self.stdout.write(
                self.style.WARNING('\n⚠️  IMPORTANT: Please update these settings via the admin panel!')
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error creating ServerSetting: {e}')
            )
