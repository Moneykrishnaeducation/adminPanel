from django.core.management.base import BaseCommand
from adminPanel.monthly_reports_thread import monthly_reports_thread

class Command(BaseCommand):
    help = 'Manage the monthly reports background thread'

    def add_arguments(self, parser):
        parser.add_argument(
            'action',
            choices=['start', 'stop', 'status', 'force-run', 'retry-failed'],
            help='Action to perform on the monthly reports thread'
        )
        parser.add_argument(
            '--month',
            type=str,
            help='Month in format YYYY-MM for force-run or retry-failed actions',
        )

    def handle(self, *args, **options):
        action = options['action']
        
        if action == 'start':
            self.start_thread()
        elif action == 'stop':
            self.stop_thread()
        elif action == 'status':
            self.show_status()
        elif action == 'force-run':
            self.force_run(options['month'])
        elif action == 'retry-failed':
            self.retry_failed(options['month'])

    def start_thread(self):
        """Start the monthly reports thread"""
        try:
            monthly_reports_thread.start()
            self.stdout.write(
                self.style.SUCCESS('Monthly reports thread started successfully')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to start thread: {str(e)}')
            )

    def stop_thread(self):
        """Stop the monthly reports thread"""
        try:
            monthly_reports_thread.stop()
            self.stdout.write(
                self.style.SUCCESS('Monthly reports thread stopped successfully')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to stop thread: {str(e)}')
            )

    def show_status(self):
        """Show thread status and schedule information"""
        from adminPanel.models import ReportGenerationSchedule
        
        # Thread status
        if monthly_reports_thread.running:
            self.stdout.write(
                self.style.SUCCESS('Monthly reports thread is RUNNING')
            )
            self.stdout.write(f'Check interval: {monthly_reports_thread.interval} seconds')
            if monthly_reports_thread.last_check_date:
                self.stdout.write(f'Last check: {monthly_reports_thread.last_check_date}')
        else:
            self.stdout.write(
                self.style.WARNING('Monthly reports thread is STOPPED')
            )
        
        # Schedule information
        try:
            schedules = ReportGenerationSchedule.objects.filter(is_active=True)
            if schedules.exists():
                self.stdout.write('\nActive Schedules:')
                for schedule in schedules:
                    self.stdout.write(f'  - {schedule.name}')
                    self.stdout.write(f'    Generation day: {schedule.generation_day}')
                    self.stdout.write(f'    Include all users: {schedule.include_all_users}')
                    self.stdout.write(f'    Email from: {schedule.email_from}')
                    if schedule.last_run:
                        self.stdout.write(f'    Last run: {schedule.last_run}')
                    self.stdout.write('')
            else:
                self.stdout.write(
                    self.style.WARNING('No active report schedules found')
                )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error getting schedule info: {str(e)}')
            )

    def force_run(self, month_year):
        """Force run monthly report generation"""
        try:
            self.stdout.write('Force running monthly report generation...')
            results = monthly_reports_thread.force_run_monthly_reports(month_year)
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"Force run completed:\n"
                    f"  Total users: {results['total_users']}\n"
                    f"  Successful: {results['successful_reports']}\n"
                    f"  Failed: {results['failed_reports']}"
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Force run failed: {str(e)}')
            )

    def retry_failed(self, month_year):
        """Retry failed email sends"""
        try:
            self.stdout.write('Retrying failed email sends...')
            success_count = monthly_reports_thread.retry_failed_emails(month_year)
            
            self.stdout.write(
                self.style.SUCCESS(f'Retry completed: {success_count} emails sent successfully')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Retry failed: {str(e)}')
            )
