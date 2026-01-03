from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime
from adminPanel.tasks.monthly_reports import MonthlyReportGenerator
from adminPanel.monthly_reports_thread import monthly_reports_thread
import json

class Command(BaseCommand):
    help = 'Test and manage the automated monthly reports system'

    def add_arguments(self, parser):
        parser.add_argument(
            '--check-system',
            action='store_true',
            help='Check if the system is properly configured for automated reports',
        )
        parser.add_argument(
            '--test-user',
            type=str,
            help='Test report generation for a specific user email',
        )
        parser.add_argument(
            '--test-generation',
            action='store_true',
            help='Test report generation with the first available user',
        )
        parser.add_argument(
            '--force-run',
            type=str,
            help='Force run monthly reports for specific month (format: YYYY-MM)',
        )
        parser.add_argument(
            '--thread-status',
            action='store_true',
            help='Check the status of the monthly reports background thread',
        )

    def handle(self, *args, **options):
        generator = MonthlyReportGenerator()
        
        if options['check_system']:
            self.check_system_status(generator)
        elif options['test_user']:
            self.test_user_report(generator, options['test_user'])
        elif options['test_generation']:
            self.test_report_generation(generator)
        elif options['force_run']:
            self.force_run_reports(options['force_run'])
        elif options['thread_status']:
            self.check_thread_status()
        else:
            self.show_help()

    def check_system_status(self, generator):
        """Check if the automated monthly reports system is properly configured"""
        self.stdout.write(self.style.HTTP_INFO('🔍 Checking automated monthly reports system...'))
        
        status = generator.check_system_requirements()
        
        self.stdout.write(f"\n📊 System Status Report:")
        self.stdout.write(f"  Email configured: {'✅' if status['email_configured'] else '❌'}")
        self.stdout.write(f"  Report template exists: {'✅' if status['template_exists'] else '❌'}")
        self.stdout.write(f"  Report schedule active: {'✅' if status['report_schedule_active'] else '❌'}")
        self.stdout.write(f"  Users with trading accounts: {status['users_with_trading_accounts']}")
        self.stdout.write(f"  Users ready for reports: {status['users_ready_for_reports']}")
        
        if status['issues']:
            self.stdout.write(f"\n⚠️  Issues found:")
            for issue in status['issues']:
                self.stdout.write(f"    • {issue}")
        
        if status['system_ready']:
            self.stdout.write(self.style.SUCCESS('\n✅ System is ready for automated monthly reports!'))
        else:
            self.stdout.write(self.style.WARNING('\n⚠️  System needs attention before automated reports can run properly.'))

    def test_user_report(self, generator, user_email):
        """Test report generation for a specific user"""
        self.stdout.write(f"🧪 Testing report generation for user: {user_email}")
        
        result = generator.test_report_generation(user_email)
        
        if result['success']:
            self.stdout.write(self.style.SUCCESS('✅ Test report generation successful!'))
            self.stdout.write(f"  User: {result['user_email']}")
            self.stdout.write(f"  Report period: {result['report_period']}")
            self.stdout.write(f"  Report file exists: {'✅' if result['report_file_exists'] else '❌'}")
            self.stdout.write(f"  Password generated: {'✅' if result['password_generated'] else '❌'}")
            if result['password_generated']:
                self.stdout.write(f"  Password: {result['password']}")
            self.stdout.write(f"  Report status: {result['report_status']}")
        else:
            self.stdout.write(self.style.ERROR(f"❌ Test failed: {result['error']}"))

    def test_report_generation(self, generator):
        """Test report generation with the first available user"""
        self.stdout.write("🧪 Testing report generation with first available user...")
        
        result = generator.test_report_generation()
        
        if result['success']:
            self.stdout.write(self.style.SUCCESS('✅ Test report generation successful!'))
            self.stdout.write(f"  User: {result['user_email']}")
            self.stdout.write(f"  Report period: {result['report_period']}")
            self.stdout.write(f"  Report file exists: {'✅' if result['report_file_exists'] else '❌'}")
            self.stdout.write(f"  Password generated: {'✅' if result['password_generated'] else '❌'}")
            if result['password_generated']:
                self.stdout.write(f"  Password: {result['password']}")
            self.stdout.write(f"  Report status: {result['report_status']}")
        else:
            self.stdout.write(self.style.ERROR(f"❌ Test failed: {result['error']}"))

    def force_run_reports(self, month_year):
        """Force run monthly reports for a specific month"""
        try:
            year, month = map(int, month_year.split('-'))
            self.stdout.write(f"🚀 Force running monthly reports for {year}-{month:02d}...")
            
            results = monthly_reports_thread.force_run_monthly_reports(month_year)
            
            self.stdout.write(self.style.SUCCESS('✅ Force run completed!'))
            self.stdout.write(f"  Total users: {results.get('total_users', 'N/A')}")
            self.stdout.write(f"  Successful: {results.get('successful_reports', 'N/A')}")
            self.stdout.write(f"  Failed: {results.get('failed_reports', 'N/A')}")
            self.stdout.write(f"  Skipped: {results.get('skipped_reports', 'N/A')}")
            
        except ValueError:
            self.stdout.write(self.style.ERROR('❌ Invalid month format. Use YYYY-MM (e.g., 2025-01)'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Force run failed: {e}'))

    def check_thread_status(self):
        """Check the status of the monthly reports background thread"""
        self.stdout.write("🔍 Checking monthly reports thread status...")
        
        try:
            is_running = monthly_reports_thread.running
            self.stdout.write(f"  Thread running: {'✅' if is_running else '❌'}")
            
            if hasattr(monthly_reports_thread, 'last_check_date') and monthly_reports_thread.last_check_date:
                self.stdout.write(f"  Last check: {monthly_reports_thread.last_check_date}")
            else:
                self.stdout.write("  Last check: Never")
            
            # Check schedule settings
            from adminPanel.models import ReportGenerationSchedule
            schedule = ReportGenerationSchedule.objects.filter(is_active=True).first()
            
            if schedule:
                self.stdout.write(f"  Schedule active: ✅")
                self.stdout.write(f"  Generation day: {schedule.generation_day}")
                self.stdout.write(f"  Last run: {schedule.last_run or 'Never'}")
            else:
                self.stdout.write(f"  Schedule active: ❌")
            
            if not is_running:
                self.stdout.write("\n💡 To start the thread, restart the Django application.")
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error checking thread status: {e}"))

    def show_help(self):
        """Show available commands"""
        self.stdout.write(self.style.HTTP_INFO("📋 Available commands for monthly reports system:"))
        self.stdout.write("")
        self.stdout.write("  --check-system          Check if system is properly configured")
        self.stdout.write("  --test-generation       Test report generation with first available user")
        self.stdout.write("  --test-user EMAIL       Test report generation for specific user")
        self.stdout.write("  --force-run YYYY-MM     Force run reports for specific month")
        self.stdout.write("  --thread-status         Check background thread status")
        self.stdout.write("")
        self.stdout.write("Examples:")
        self.stdout.write("  python manage.py test_monthly_reports --check-system")
        self.stdout.write("  python manage.py test_monthly_reports --test-user user@example.com")
        self.stdout.write("  python manage.py test_monthly_reports --force-run 2025-01")
