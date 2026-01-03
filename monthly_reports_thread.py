import threading
import time
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from adminPanel.models import ReportGenerationSchedule
from adminPanel.tasks.monthly_reports import MonthlyReportGenerator

logger = logging.getLogger(__name__)

class MonthlyReportsThread:
    """Background thread to handle monthly report generation and scheduling"""
    
    def __init__(self):
        self.interval = 3600  # Check every hour (3600 seconds)
        self.thread = None
        self.stop_event = threading.Event()
        self.running = False
        self.last_check_date = None
        
    def start(self):
        """Start the monthly reports thread"""
        if self.running:
            # logger.info("Monthly reports thread is already running")
            return
            
        self.running = True
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        # logger.info("Monthly reports thread started")
    # 
    def stop(self):
        """Stop the monthly reports thread"""
        if not self.running:
            return
            
        self.running = False
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)
        # logger.info("Monthly reports thread stopped")
    
    def _run(self):
        """Main thread loop"""
        # logger.info("Monthly reports thread is now running")
        
        while not self.stop_event.is_set():
            try:
                self._check_and_generate_reports()
            except Exception as e:
                logger.error(f"Error in monthly reports thread: {e}")
            
            # Wait for the next check interval
            self.stop_event.wait(self.interval)
    
    def _check_and_generate_reports(self):
        """Check if it's time to generate monthly reports"""
        try:
            current_time = timezone.now()
            
            # Check if we should generate reports
            if self._should_generate_reports(current_time):
                # logger.info("Time to generate monthly reports")
                self._generate_monthly_reports()
                self.last_check_date = current_time.date()
            
        except Exception as e:
            logger.error(f"Error checking for report generation: {e}")
    
    def _should_generate_reports(self, current_time):
        """Determine if it's time to generate reports"""
        try:
            # Get the schedule configuration
            schedule = ReportGenerationSchedule.objects.filter(is_active=True).first()
            
            if not schedule:
                # Create default schedule if none exists
                schedule = ReportGenerationSchedule.objects.create(
                    name="Default Monthly Reports",
                    is_active=True,
                    generation_day=1,
                    include_all_users=True,
                    email_from="support@vtindex.com"
                )
                # logger.info("Created default monthly report schedule")
            
            # Check if it's the right day of the month
            if current_time.day != schedule.generation_day:
                return False
            
            # Check if we've already run today
            if self.last_check_date == current_time.date():
                return False
            
            # Check if it's the right time (2:00 AM equivalent)
            # For testing, we'll allow any time on the 1st
            target_hour = 2  # 2:00 AM
            if current_time.hour < target_hour:
                return False
            
            # Check if we already ran this month
            if schedule.last_run:
                last_run_month = schedule.last_run.month
                last_run_year = schedule.last_run.year
                
                if (last_run_month == current_time.month and 
                    last_run_year == current_time.year):
                    # logger.info("Reports already generated this month")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking report generation schedule: {e}")
            return False
    
    def _generate_monthly_reports(self):
        """Generate monthly reports for all eligible users"""
        try:
            # Get the schedule
            schedule = ReportGenerationSchedule.objects.filter(is_active=True).first()
            if not schedule:
                logger.error("No active report schedule found")
                return
            
            # Calculate the previous month
            current_time = timezone.now()
            if current_time.month == 1:
                report_year = current_time.year - 1
                report_month = 12
            else:
                report_year = current_time.year
                report_month = current_time.month - 1
            
            # logger.info(f"Generating monthly reports for {report_year}-{report_month:02d}")
            
            # Initialize the report generator
            generator = MonthlyReportGenerator()
            
            # Generate reports
            results = generator.generate_reports_for_all_users(
                year=report_year,
                month=report_month,
                force_regenerate=False
            )
            
            # Update the schedule
            with transaction.atomic():
                schedule.last_run = current_time
                schedule.save()
            
            # logger.info(f"Monthly report generation completed: {results}")
            
        except Exception as e:
            logger.error(f"Error generating monthly reports: {e}")
    
    def force_run_monthly_reports(self, month_year=None):
        """Manually trigger monthly report generation"""
        try:
            if month_year:
                # Parse month_year format "YYYY-MM"
                year, month = map(int, month_year.split('-'))
            else:
                # Default to previous month
                current_time = datetime.now()
                if current_time.month == 1:
                    year = current_time.year - 1
                    month = 12
                else:
                    year = current_time.year
                    month = current_time.month - 1
            
            # logger.info(f"Force generating monthly reports for {year}-{month:02d}")
            
            generator = MonthlyReportGenerator()
            results = generator.generate_reports_for_all_users(
                year=year,
                month=month,
                force_regenerate=True
            )
            
            # logger.info(f"Force generation completed: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Error in force generation: {e}")
            raise
    
    def retry_failed_emails(self, month_year=None):
        """Retry sending failed report emails"""
        try:
            from adminPanel.models import MonthlyTradeReport
            
            if month_year:
                year, month = map(int, month_year.split('-'))
                failed_reports = MonthlyTradeReport.objects.filter(
                    year=year,
                    month=month,
                    status='email_failed'
                )
            else:
                # Retry all recent failed emails
                failed_reports = MonthlyTradeReport.objects.filter(
                    status='email_failed',
                    created_at__gte=timezone.now() - timedelta(days=7)
                )
            
            generator = MonthlyReportGenerator()
            success_count = 0
            
            for report in failed_reports:
                try:
                    if generator.send_report_email(report):
                        success_count += 1
                        # logger.info(f"Successfully retried email for {report.user.email}")
                    else:
                        # logger.warning(f"Retry failed for {report.user.email}")
                        pass
                except Exception as e:
                    logger.error(f"Error retrying email for {report.user.email}: {e}")
            
            # logger.info(f"Email retry completed: {success_count}/{failed_reports.count()} successful")
            return success_count
            
        except Exception as e:
            logger.error(f"Error retrying failed emails: {e}")
            raise

# Global instance
monthly_reports_thread = MonthlyReportsThread()

# Helper functions for management
def start_monthly_reports_thread():
    """Start the monthly reports thread"""
    monthly_reports_thread.start()

def stop_monthly_reports_thread():
    """Stop the monthly reports thread"""
    monthly_reports_thread.stop()

def force_generate_reports(month_year=None):
    """Force generate monthly reports"""
    return monthly_reports_thread.force_run_monthly_reports(month_year)

def retry_failed_report_emails(month_year=None):
    """Retry failed report emails"""
    return monthly_reports_thread.retry_failed_emails(month_year)
