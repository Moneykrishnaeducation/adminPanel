"""
Management command to check MT5 server configuration for PAMM accounts
"""
from django.core.management.base import BaseCommand
from adminPanel.mt5.services import MT5ManagerActions, get_manager_instance
from adminPanel.mt5.models import ServerSetting
from adminPanel.models_pamm import PAMMAccount
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check MT5 server configuration and list PAMM accounts'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('\n=== MT5 PAMM Account Checker ===\n'))

        # 1. Check Server Settings
        self.stdout.write(self.style.WARNING('📡 Checking MT5 Server Settings...'))
        real_servers = ServerSetting.objects.filter(server_type=True).order_by('-created_at')
        demo_servers = ServerSetting.objects.filter(server_type=False).order_by('-created_at')

        if real_servers.exists():
            real_server = real_servers.first()
            self.stdout.write(self.style.SUCCESS(f'✅ REAL Server Found:'))
            self.stdout.write(f'   Server IP: {real_server.get_decrypted_server_ip()}')
            self.stdout.write(f'   Manager Login: {real_server.real_account_login}')
            self.stdout.write(f'   Created: {real_server.created_at}')
        else:
            self.stdout.write(self.style.ERROR('❌ No REAL server configured!'))

        if demo_servers.exists():
            demo_server = demo_servers.first()
            self.stdout.write(self.style.SUCCESS(f'\n✅ DEMO Server Found:'))
            self.stdout.write(f'   Server IP: {demo_server.get_decrypted_server_ip()}')
            self.stdout.write(f'   Manager Login: {demo_server.demo_login}')
            self.stdout.write(f'   Created: {demo_server.created_at}')
        else:
            self.stdout.write(self.style.WARNING('\n⚠️ No DEMO server configured'))

        # 2. Test MT5 Connection
        self.stdout.write(self.style.WARNING('\n\n🔌 Testing MT5 Manager Connection...'))
        try:
            mt5_service = MT5ManagerActions()
            if mt5_service.manager:
                self.stdout.write(self.style.SUCCESS('✅ MT5 Manager Connected!'))
                
                # Try to get server info
                try:
                    manager_inst = get_manager_instance()
                    if manager_inst:
                        self.stdout.write(f'   Manager Instance: {type(manager_inst).__name__}')
                        self.stdout.write(f'   Connected: {manager_inst.connected if hasattr(manager_inst, "connected") else "Unknown"}')
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'   Warning getting manager details: {e}'))
            else:
                self.stdout.write(self.style.ERROR(f'❌ MT5 Manager NOT Connected!'))
                if mt5_service.connection_error:
                    self.stdout.write(self.style.ERROR(f'   Error: {mt5_service.connection_error}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Connection Error: {str(e)}'))

        # 3. List PAMM Accounts
        self.stdout.write(self.style.WARNING('\n\n📋 PAMM Accounts in Database:'))
        pamms = PAMMAccount.objects.all().order_by('-created_at')
        
        if not pamms.exists():
            self.stdout.write(self.style.WARNING('   No PAMM accounts found'))
        else:
            for pamm in pamms:
                self.stdout.write(f'\n   🏦 PAMM ID: {pamm.id}')
                self.stdout.write(f'      Name: {pamm.name}')
                self.stdout.write(f'      Manager: {pamm.manager.email}')
                self.stdout.write(f'      MT5 Account: {pamm.mt5_account_id or "❌ NOT CREATED"}')
                self.stdout.write(f'      Status: {pamm.status}')
                self.stdout.write(f'      Leverage: {pamm.leverage}')
                self.stdout.write(f'      Created: {pamm.created_at}')
                
                if pamm.mt5_account_id:
                    # Try to verify account exists in MT5
                    try:
                        if mt5_service.manager:
                            account_info = mt5_service.get_account_info(int(pamm.mt5_account_id))
                            if account_info:
                                self.stdout.write(self.style.SUCCESS(f'      ✅ VERIFIED in MT5'))
                                balance = account_info.get('balance', 0)
                                equity = account_info.get('equity', 0)
                                self.stdout.write(f'         Balance: ${balance:.2f}')
                                self.stdout.write(f'         Equity: ${equity:.2f}')
                            else:
                                self.stdout.write(self.style.ERROR(f'      ❌ NOT FOUND in MT5!'))
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f'      ⚠️ Could not verify: {str(e)}'))

        # 4. Instructions
        self.stdout.write(self.style.SUCCESS('\n\n=== Important Notes ==='))
        self.stdout.write('📌 PAMM accounts are created on the REAL MT5 server')
        self.stdout.write('📌 Check your REAL MT5 Manager interface (not demo)')
        self.stdout.write('📌 Account passwords are logged during creation')
        self.stdout.write('📌 Check Django logs in logs/ folder for creation details')
        self.stdout.write('\n✅ Check complete!\n')
