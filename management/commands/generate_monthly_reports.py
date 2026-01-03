from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime
from adminPanel.tasks.monthly_reports import MonthlyReportGenerator
from adminPanel.monthly_reports_thread import monthly_reports_thread

class Command(BaseCommand):
    help = 'Generate and email monthly trading reports'

    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            type=str,
            help='Month in format YYYY-MM (e.g., 2025-01). Defaults to previous month.',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Generate report for specific user ID only',
        )
        parser.add_argument(
            '--email-only',
            action='store_true',
            help='Only send emails for already generated reports',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force regenerate reports even if they already exist',
        )
        parser.add_argument(
            '--retry-failed',
            action='store_true',
            help='Retry sending failed report emails',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually doing it',
        )

    def handle(self, *args, **options):
        try:
            if options['retry_failed']:
                return self.retry_failed_emails(options)
            
            if options['email_only']:
                return self.send_existing_reports(options)
            
            return self.generate_reports(options)
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error: {str(e)}')
            )
            raise

    def generate_reports(self, options):
        """Generate monthly reports"""
        # Parse month parameter
        if options['month']:
            try:
                year, month = map(int, options['month'].split('-'))
            except ValueError:
                self.stdout.write(
                    self.style.ERROR('Month must be in format YYYY-MM (e.g., 2025-01)')
                )
                return
        else:
            # Default to previous month
            current_time = datetime.now()
            if current_time.month == 1:
                year = current_time.year - 1
                month = 12
            else:
                year = current_time.year
                month = current_time.month - 1

        self.stdout.write(f'Processing monthly reports for {year}-{month:02d}')
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No actual changes will be made'))

        # Initialize generator
        generator = MonthlyReportGenerator()
        
        if options['user_id']:
            # Generate for specific user
            return self.generate_for_user(generator, options['user_id'], year, month, options)
        else:
            # Generate for all users
            return self.generate_for_all_users(generator, year, month, options)

    def generate_for_user(self, generator, user_id, year, month, options):
        """Generate report for a specific user"""
        from adminPanel.models import CustomUser
        
        try:
            user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'User with ID {user_id} not found')
            )
            return

        self.stdout.write(f'Generating report for user: {user.email}')
        
        if options['dry_run']:
            self.stdout.write(f'Would generate report for {user.email}')
            return

        try:
            # Create report
            report = generator.create_monthly_report(
                user, 
                year, 
                month, 
                force_regenerate=options['force']
            )
            
            # Send email
            if generator.send_report_email(report):
                self.stdout.write(
                    self.style.SUCCESS(f'Successfully processed report for {user.email}')
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f'Failed to send email for {user.email}')
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to process report for {user.email}: {str(e)}')
            )

    def generate_for_all_users(self, generator, year, month, options):
        """Generate reports for all eligible users"""
        from adminPanel.models import CustomUser
        
        # Get eligible users
        users = CustomUser.objects.filter(
            is_active=True,
            trading_accounts__isnull=False
        ).distinct()
        
        total_users = users.count()
        self.stdout.write(f'Found {total_users} eligible users')
        
        if options['dry_run']:
            self.stdout.write(f'Would process {total_users} users')
            for user in users[:5]:  # Show first 5 as example
                self.stdout.write(f'  - {user.email}')
            if total_users > 5:
                self.stdout.write(f'  ... and {total_users - 5} more users')
            return

        # Process reports
        results = generator.generate_reports_for_all_users(
            year=year,
            month=month,
            force_regenerate=options['force']
        )
        
        # Display results
        self.stdout.write(
            self.style.SUCCESS(
                f"Report generation completed:\n"
                f"  Total users: {results['total_users']}\n"
                f"  Successful: {results['successful_reports']}\n"
                f"  Failed: {results['failed_reports']}"
            )
        )

    def send_existing_reports(self, options):
        """Send emails for already generated reports"""
        from adminPanel.models import MonthlyTradeReport
        
        # Parse month parameter
        if options['month']:
            year, month = map(int, options['month'].split('-'))
            reports = MonthlyTradeReport.objects.filter(
                year=year,
                month=month,
                status='generated'
            )
        else:
            # Recent generated reports
            reports = MonthlyTradeReport.objects.filter(
                status='generated',
                created_at__gte=timezone.now() - timezone.timedelta(days=7)
            )
        
        total_reports = reports.count()
        self.stdout.write(f'Found {total_reports} generated reports to email')
        
        if options['dry_run']:
            self.stdout.write(f'Would send {total_reports} emails')
            return

        generator = MonthlyReportGenerator()
        success_count = 0
        
        for report in reports:
            try:
                if generator.send_report_email(report):
                    success_count += 1
                    self.stdout.write(f'Sent email to {report.user.email}')
                else:
                    self.stdout.write(
                        self.style.WARNING(f'Failed to send email to {report.user.email}')
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Error sending email to {report.user.email}: {str(e)}')
                )
        
        self.stdout.write(
            self.style.SUCCESS(f'Email sending completed: {success_count}/{total_reports} successful')
        )

    def retry_failed_emails(self, options):
        """Retry sending failed report emails"""
        self.stdout.write('Retrying failed report emails...')
        
        if options['dry_run']:
            self.stdout.write('Would retry failed emails')
            return

        try:
            success_count = monthly_reports_thread.retry_failed_emails(options['month'])
            self.stdout.write(
                self.style.SUCCESS(f'Retry completed: {success_count} emails sent successfully')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error retrying failed emails: {str(e)}')
            )
