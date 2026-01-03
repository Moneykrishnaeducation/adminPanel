from django.core.management.base import BaseCommand
from django.core.cache import cache
from django.db import transaction
from adminPanel.mt5.services import reset_manager_instance
from adminPanel.mt5.models import ServerSetting, MT5GroupConfig
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Reset MT5 database cache and connection completely'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear-groups',
            action='store_true',
            help='Clear all cached MT5 trading groups',
        )
        parser.add_argument(
            '--clear-all-cache',
            action='store_true',
            help='Clear all Django cache',
        )
        parser.add_argument(
            '--reset-connection',
            action='store_true',
            help='Reset MT5 manager connection',
        )
        parser.add_argument(
            '--full-reset',
            action='store_true',
            help='Perform complete reset (all options above)',
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

            # Determine what to reset
            reset_connection = options['reset_connection'] or options['full_reset']
            clear_groups = options['clear_groups'] or options['full_reset']
            clear_all_cache = options['clear_all_cache'] or options['full_reset']

            # Default to full reset if no specific options
            if not any([options['reset_connection'], options['clear_groups'], options['clear_all_cache']]):
                reset_connection = clear_groups = clear_all_cache = True
                self.stdout.write('No specific options provided, performing full reset...')

            operations_count = 0

            # Reset MT5 connection
            if reset_connection:
                self.stdout.write('🔄 Resetting MT5 Manager connection...')
                reset_manager_instance()
                self.stdout.write(self.style.SUCCESS('✅ MT5 connection reset'))
                operations_count += 1

            # Clear MT5 trading groups from database
            if clear_groups:
                with transaction.atomic():
                    groups_count = MT5GroupConfig.objects.count()
                    self.stdout.write(f'🗑️  Clearing {groups_count} cached MT5 trading groups...')
                    MT5GroupConfig.objects.all().delete()
                    self.stdout.write(self.style.SUCCESS('✅ MT5 trading groups cleared from database'))
                    operations_count += 1

            # Clear Django cache
            if clear_all_cache:
                self.stdout.write('🧹 Clearing all Django cache...')
                cache.clear()
                self.stdout.write(self.style.SUCCESS('✅ Django cache cleared'))
                operations_count += 1

            # Clear specific MT5 cache keys
            self.stdout.write('🧹 Clearing MT5-specific cache keys...')
            mt5_cache_keys = [
                'mt5_manager_error',
                'mt5_groups_sync',
                'mt5_connection_status',
                'mt5_leverage_options',
                'mt5_groups_last_sync'
            ]
            cleared_count = 0
            for key in mt5_cache_keys:
                if cache.get(key) is not None:
                    cache.delete(key)
                    cleared_count += 1
            
            self.stdout.write(f'✅ Cleared {cleared_count} MT5-specific cache keys')

            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(f'🎉 Database reset completed! ({operations_count} operations)'))
            self.stdout.write('')
            self.stdout.write('Next actions:')
            self.stdout.write('📊 Trading groups will be fetched fresh from MT5 on next request')
            self.stdout.write('🔗 MT5 connection will use latest credentials')
            self.stdout.write('💾 All cache will be rebuilt as needed')

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to reset database: {str(e)}')
            )
            logger.error(f"Error in reset_mt5_database command: {e}")
