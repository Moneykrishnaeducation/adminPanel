from django.core.management.base import BaseCommand
from django.core.management import call_command
import time
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Run commission sync continuously in an infinite loop.'

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=int, default=30, help='Seconds between sync runs (default: 30)')
        parser.add_argument('--max-errors', type=int, default=10, help='Max consecutive errors before stopping (default: 10)')

    def handle(self, *args, **options):
        interval = options['interval']
        max_errors = options['max_errors']
        
        print(f"🚀 Starting continuous commission sync...")
        print(f"   Interval: {interval} seconds")
        print(f"   Max errors: {max_errors}")
        print(f"   Press Ctrl+C to stop")
        
        error_count = 0
        cycle_count = 0
        
        try:
            while True:
                cycle_count += 1
                cycle_start = time.time()
                
                try:
                    # Run the commission sync
                    call_command('sync_commissions_from_mt5')
                    
                    # Reset error count on successful run
                    error_count = 0
                    
                    cycle_time = (time.time() - cycle_start) * 1000
                    print(f"🔄 Cycle {cycle_count} completed in {cycle_time:.1f}ms")
                    
                except Exception as e:
                    error_count += 1
                    print(f"❌ Error in cycle {cycle_count} ({error_count}/{max_errors}): {e}")
                    
                    if error_count >= max_errors:
                        print(f"💥 Too many consecutive errors ({max_errors}). Stopping.")
                        break
                
                # Wait for next cycle
                if interval > 0:
                    time.sleep(interval)
                    
        except KeyboardInterrupt:
            print(f"\n🛑 Stopped by user after {cycle_count} cycles")
        except Exception as e:
            print(f"\n💥 Fatal error: {e}")
        
        print(f"✅ Commission sync stopped")