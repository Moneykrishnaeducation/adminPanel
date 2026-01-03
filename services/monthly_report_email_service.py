import os
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import smtplib
from django.conf import settings
from django.template.loader import render_to_string
from django.core.files.base import ContentFile
from adminPanel.EmailSender import EmailSender

logger = logging.getLogger(__name__)


class MonthlyReportEmailService:
    """Service to send monthly trade reports via email with encrypted PDF attachments"""
    
    @staticmethod
    def send_monthly_report(user, report_instance, pdf_path, password):
        """
        Send monthly trade report email with encrypted PDF attachment
        
        Args:
            user: CustomUser instance
            report_instance: MonthlyTradeReport instance
            pdf_path: Path to the encrypted PDF file
            password: Password for the PDF (user's DOB)
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # Prepare email content
            # Compose month/year string
            month_name = [ '', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December' ][report_instance.month]
            subject = f"Monthly Trading Report - {month_name} {report_instance.year}"
            
            # Create email context
            context = {
                'user_name': user.get_full_name(),
                'report_month': f"{month_name} {report_instance.year}",
                'total_trades': report_instance.total_trades,
                'total_volume': report_instance.total_volume,
                'total_commission': report_instance.total_commission,
                'password_hint': report_instance.password_hint,
                'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@vtindex.com'),
                'company_name': getattr(settings, 'COMPANY_NAME', 'VTIndex'),
                'login_url': getattr(settings, 'CLIENT_LOGIN_URL', 'https://client.vtindex.com'),
                'generated_date': report_instance.created_at.strftime('%d %B %Y')
            }
            
            # Send email with attachment
            success = MonthlyReportEmailService._send_email_with_attachment(
                to_email=user.email,
                subject=subject,
                template_name='monthly_trade_report',
                context=context,
                attachment_path=pdf_path,
                attachment_filename=f"monthly_report_{report_instance.year}{report_instance.month:02d}.pdf"
            )
            
            if success:
                report_instance.status = 'email_sent'
                report_instance.save()
                logger.info(f"Monthly report email sent successfully to {user.email}")
            else:
                report_instance.email_attempts += 1
                report_instance.status = 'email_failed'
                report_instance.save()
                logger.error(f"Failed to send monthly report email to {user.email}")
            
            return success
            
        except Exception as e:
            error_msg = f"Error sending monthly report email: {str(e)}"
            logger.error(error_msg)
            report_instance.email_attempts += 1
            report_instance.status = 'email_failed'
            report_instance.save()
            return False
    
    @staticmethod
    def _send_email_with_attachment(to_email, subject, template_name, context, attachment_path, attachment_filename):
        """
        Send email with PDF attachment using SMTP directly
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            template_name: Email template name
            context: Template context variables
            attachment_path: Path to the PDF file to attach
            attachment_filename: Name for the attachment
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Setup SMTP connection
            server = smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT)
            server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            
            # Create message
            msg = MIMEMultipart()
            msg['From'] = settings.DEFAULT_FROM_EMAIL
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Render HTML content
            html_content = render_to_string(f'emails/{template_name}.html', context)
            
            # Attach HTML content
            html_part = MIMEText(html_content, 'html')
            msg.attach(html_part)
            
            # Attach PDF file
            if os.path.exists(attachment_path):
                with open(attachment_path, 'rb') as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                    
                # Encode file in ASCII characters to send by email
                encoders.encode_base64(part)
                
                # Add header with PDF filename
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {attachment_filename}',
                )
                
                msg.attach(part)
            else:
                logger.warning(f"Attachment file not found: {attachment_path}")
            
            # Send email
            text = msg.as_string()
            server.sendmail(settings.EMAIL_HOST_USER, to_email, text)
            server.quit()
            
            logger.info(f"Email with attachment sent successfully to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email with attachment to {to_email}: {str(e)}")
            if 'server' in locals():
                try:
                    server.quit()
                except:
                    pass
            return False
    
    @staticmethod
    def send_report_generation_notification(user, report_month, success=True, error_message=None):
        try:
            # If report_month is a string, parse year/month
            if isinstance(report_month, str):
                year, month = report_month.split('-')
                year = int(year)
                month = int(month)
                month_name = [ '', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December' ][month]
                report_month_str = f"{month_name} {year}"
            else:
                month_name = [ '', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December' ][report_month.month]
                report_month_str = f"{month_name} {report_month.year}"
            if success:
                subject = f"Monthly Report Generated - {report_month_str}"
                template_name = 'monthly_report_success'
            else:
                subject = f"Monthly Report Generation Failed - {report_month_str}"
                template_name = 'monthly_report_failed'
            context = {
                'user_name': user.get_full_name(),
                'report_month': report_month_str,
                'error_message': error_message,
                'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@vtindex.com'),
                'company_name': getattr(settings, 'COMPANY_NAME', 'VTIndex')
            }
            return EmailSender._send_email(
                to_email=user.email,
                subject=subject,
                template_name=template_name,
                context=context
            )
            
        except Exception as e:
            logger.error(f"Failed to send report generation notification: {str(e)}")
            return False
