from django.core.management.base import BaseCommand
from django.core.cache import cache
from adminPanel.mt5.services import reset_manager_instance, force_refresh_trading_groups
from adminPanel.mt5.models import ServerSetting
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Force refresh MT5 Manager connection to reload new credentials'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear-cache',
            action='store_true',
            help='Also clear all MT5-related cache entries',
        )
        parser.add_argument(
            '--test-connection',
            action='store_true',
            help='Test the connection after refresh',
        )
        parser.add_argument(
            '--refresh-groups',
            action='store_true',
            help='Also refresh trading groups from MT5',
        )

    def handle(self, *args, **options):
        try:
            # Check if server settings exist
            if not ServerSetting.objects.exists():
                self.stdout.write(
                    self.style.ERROR('No server settings found. Please configure MT5 server settings first.')
                )
                return

            latest_setting = ServerSetting.objects.latest('created_at')
            self.stdout.write(f'Current server settings:')
            self.stdout.write(f'  Server IP: {latest_setting.server_ip}')
            self.stdout.write(f'  Login: {latest_setting.real_account_login}')
            self.stdout.write(f'  Server Name: {latest_setting.server_name_client}')
            self.stdout.write('')

            # Reset the manager instance
            self.stdout.write('Resetting MT5 Manager connection...')
            reset_manager_instance()
            
            # Refresh trading groups if requested
            if options['refresh_groups']:
                self.stdout.write('Refreshing trading groups from new MT5 Manager...')
                groups_success = force_refresh_trading_groups()
                if groups_success:
                    self.stdout.write(
                        self.style.SUCCESS('✓ Trading groups refreshed successfully!')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING('⚠ Trading groups refresh failed - will retry on next API call')
                    )
            
            # Clear additional cache if requested
            if options['clear_cache']:
                self.stdout.write('Clearing MT5-related cache entries...')
                cache_keys = [
                    'mt5_manager_error',
                    'mt5_groups_sync',
                    'mt5_connection_status'
                ]
                for key in cache_keys:
                    cache.delete(key)
                
                # Clear failed account cache pattern
                cache.clear()  # This is more aggressive but ensures clean slate
                self.stdout.write('Cache cleared successfully.')

            # Test connection if requested
            if options['test_connection']:
                self.stdout.write('Testing MT5 connection...')
                try:
                    from adminPanel.mt5.services import get_manager_instance
                    manager = get_manager_instance()
                    if manager and manager.connected:
                        self.stdout.write(
                            self.style.SUCCESS('✓ MT5 connection test successful!')
                        )
                    else:
                        self.stdout.write(
                            self.style.ERROR('✗ MT5 connection test failed. Check your credentials.')
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'✗ MT5 connection test failed: {str(e)}')
                    )

            self.stdout.write(
                self.style.SUCCESS('MT5 Manager connection refresh completed successfully!')
            )
            self.stdout.write('')
            self.stdout.write('The application will now use the new credentials for all MT5 operations.')

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to refresh MT5 connection: {str(e)}')
            )
            logger.error(f"Error in refresh_mt5_connection command: {e}")
