from django.core.mail import EmailMultiAlternatives, get_connection
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

class EmailSender:
    @staticmethod
    def send_kyc_document_rejected_email(user_email, user_name, support_url, upload_url, rejected_identity=False, rejected_residence=False):
        """Send KYC document rejected email to user"""
        both_rejected = rejected_identity and rejected_residence
        return EmailSender._send_email(
            user_email,
            'KYC Document Rejected',
            'kyc_document_rejected',
            {
                'user_name': user_name,
                'support_url': support_url,
                'upload_url': upload_url,
                'rejected_identity': rejected_identity,
                'rejected_residence': rejected_residence,
                'both_rejected': both_rejected
            }
        )
    @staticmethod
    def send_kyc_verified_email(user_email, user_name, login_url, support_url, current_year):
        """Send KYC verified email to user"""
        return EmailSender._send_email(
            user_email,
            'Your KYC Has Been Verified',
            'kyc_verified',
            {
                'user_name': user_name,
                'login_url': login_url,
                'support_url': support_url,
                'current_year': current_year
            }
        )

    @staticmethod
    def _send_email(to_email, subject, template_name, context, css_styles=None):
        """Internal method to send emails using Django's email backend for better performance."""
        try:
            # Ensure context is a dict we can mutate safely
            if context is None:
                context = {}

            # Provide sensible defaults so template always shows company/button/support info
            context.setdefault('company_name', getattr(settings, 'DEFAULT_COMPANY_NAME', 'VTIndex'))
            context.setdefault('support_email', getattr(settings, 'SUPPORT_EMAIL', 'support@vtindex.com'))
            context.setdefault('button_text', context.get('button_text', 'Go to Dashboard'))
            context.setdefault('button_url', context.get('button_url', 'https://client.vtindex.com'))
            context.setdefault('current_year', context.get('current_year') or getattr(settings, 'CURRENT_YEAR', None) or datetime.now().year)
            # Normalize username from multiple possible keys or derive from email
            if not context.get('username'):
                context['username'] = context.get('user_name') or context.get('first_name') or ''


            # Update context with custom CSS if provided
            if css_styles:
                context['custom_styles'] = css_styles

            # Render email template
            html_content = render_to_string(f'emails/{template_name}.html', context)
            text_content = strip_tags(html_content)

            # Use Django's email backend and connection pooling
            connection = get_connection()
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to_email],
                connection=connection
            )
            email.attach_alternative(html_content, "text/html")


            email.send(fail_silently=False)

            return True
        except Exception as e:
            logger.error(f"Failed to send {template_name} email to {to_email}: {str(e)}")
            return False

    @staticmethod
    def send_welcome_email(user_email, user_name):
        """Send welcome email to newly registered users"""
        return EmailSender._send_email(
            user_email,
            'Welcome to VTIndex',
            'new_user_welcome',
            {'username': user_name, 'login_url': 'https://client.vtindex.com'}
        )

    @staticmethod
    def send_password_reset_email(user_email, reset_link):
        """Send password reset email"""
        return EmailSender._send_email(
            user_email,
            'Password Reset Request',
            'password_reset',
            {'reset_link': reset_link, 'user_email': user_email}
        )

    @staticmethod
    def send_test_email(email):
        """Send a test email to verify configuration"""
        return EmailSender._send_email(
            email,
            'Test Email from VTIndex',
            'test_email',
            {'email': email}
        )

    @staticmethod
    def send_withdrawal_confirmation(user_email, username, account_id, amount, transaction_id, transaction_date):
        """Send withdrawal confirmation email"""
        return EmailSender._send_email(
            user_email,
            'Your Withdrawal Has Been Processed',
            'withdrawal',
            {
                'username': username,
                'account_id': account_id,
                'withdrawal_amount': round(float(amount), 2),
                'transaction_id': transaction_id,
                'transaction_date': transaction_date
            }
        )

    @staticmethod
    def send_deposit_confirmation(user_email, username, account_id, amount, transaction_id, transaction_date):
        """Send deposit confirmation email"""
        return EmailSender._send_email(
            user_email,
            'Your Deposit Has Been Processed',
            'new_deposit',
            {
                'username': username,
                'account_id': account_id,
                'deposit_amount': round(float(amount), 2),
                'transaction_id': transaction_id,
                'transaction_date': transaction_date
            }
        )

    @staticmethod
    def send_prop_approval(user_email, username):
        """Send prop trading approval email"""
        return EmailSender._send_email(
            user_email,
            'Your Prop Trading Request Has Been Approved',
            'prop_approved',
            {'username': username}
        )

    @staticmethod
    def send_otp_email(user_email, otp):
        """Send OTP verification email"""
        return EmailSender._send_email(
            user_email,
            'Your OTP Verification Code',
            'otp_email',
            {'otp': otp}
        )

    @staticmethod
    def send_login_otp_email(user_email, otp, ip_address=None, login_time=None, first_name=None):
        """Send OTP email specifically for login verification (new IP). Includes optional IP, time and recipient name."""
        context = {'otp': otp}
        if first_name:
            context['first_name'] = first_name
        if ip_address:
            context['ip_address'] = ip_address
        if login_time:
            context['login_time'] = login_time
        return EmailSender._send_email(
            user_email,
            'Your VTIndex Login Verification Code',
            'login_otp_email',
            context
        )

    @staticmethod
    def send_new_ip_login_email(user_email, user_name, ip_address, login_time, user_agent):
        """Send notification when a login is detected from a new IP address."""
        return EmailSender._send_email(
            user_email,
            'New IP Login Detected',
            'login_new_ip',
            {
                'user_name': user_name,
                'ip_address': ip_address,
                # devices: a list of strings describing other devices seen for this IP
                'devices': [],
                'login_time': login_time,
                'user_agent': user_agent
            }
        )

    @staticmethod
    def send_new_user_from_admin(email, first_name, password):
        """Send welcome email for users created by admin"""
        return EmailSender._send_email(
            email,
            'Welcome to VTIndex',
            'new_user_from_admin',
            {
                'first_name': first_name,
                'email': email,
                'password': password
            }
        )

    @staticmethod
    def send_new_investor_account(investor_email, account_id, investor_password, mt5_server):
        """Send new MAM investor account details"""
        return EmailSender._send_email(
            investor_email,
            'Your MAM Investment Account Has Been Created',
            'new_investor_account',
            {
                'account_id': account_id,
                'investor_password': investor_password,
                'mt5_server': mt5_server
            }
        )

    @staticmethod
    def send_new_investor_notification(mam_manager_email, mam_manager_name, investor_name, investor_email, investor_account_id):
        """Send notification to MAM manager about new investor"""
        return EmailSender._send_email(
            mam_manager_email,
            'New Investor Connected to Your MAM Account',
            'new_investor',
            {
                'mam_manager_name': mam_manager_name,
                'investor_name': investor_name,
                'investor_email': investor_email,
                'investor_account_id': investor_account_id
            }
        )

    @staticmethod
    def send_pamm_account_created_email(user_email, user_name, pamm_name, account_id, master_password, investor_password, leverage, profit_share, login_url, company_name, current_year=None):
        """Send email when a PAMM account is created (manager)"""
        if not current_year:
            current_year = datetime.now().year

        return EmailSender._send_email(
            user_email,
            'Your PAMM Account Has Been Created',
            'pamm_account_created',
            {
                'user_name': user_name,
                'pamm_name': pamm_name,
                'account_id': account_id,
                'master_password': master_password,
                'investor_password': investor_password,
                'leverage': leverage,
                'profit_share': profit_share,
                'login_url': login_url,
                'company_name': company_name,
                'current_year': current_year
            }
        )

    @staticmethod
    def send_pamm_investment_credentials_email(user_email, user_name, pamm_name, manager_name, investment_amount, account_id, investor_password, login_url, company_name, current_year=None):
        """Send email to investor with PAMM investment credentials"""
        if not current_year:
            current_year = datetime.now().year

        try:
            investment_amount = round(float(investment_amount), 2)
        except Exception:
            # leave as-is if conversion fails
            pass

        return EmailSender._send_email(
            user_email,
            'Your PAMM Investment Details',
            'pamm_investment_credentials',
            {
                'user_name': user_name,
                'pamm_name': pamm_name,
                'manager_name': manager_name,
                'investment_amount': investment_amount,
                'account_id': account_id,
                'investor_password': investor_password,
                'login_url': login_url,
                'company_name': company_name,
                'current_year': current_year
            }
        )

    @staticmethod
    def send_new_account_creation(user_email, username, account_id, master_password, investor_password, mt5_server_name=None):
        """Send new trading account details"""
        # Get the MT5 server name from settings if not provided
        server_name = mt5_server_name
        if not server_name:
            try:
                from adminPanel.mt5.models import ServerSetting
                latest_setting = ServerSetting.objects.latest('created_at')
                server_name = latest_setting.server_name_client if latest_setting else 'VTIndex-MT5'
            except Exception:
                server_name = 'VTIndex-MT5'  # Fallback
        
        return EmailSender._send_email(
            user_email,
            'Your New Trading Account Has Been Created',
            'new_account_creation',
            {
                'username': username,
                'account_id': account_id,
                'master_password': master_password,
                'investor_password': investor_password,
                'mt5_server': server_name
            }
        )

    @staticmethod
    def send_demo_account_creation(user_email, username, account_id, master_password, investor_password, balance, leverage, mt5_server_name=None):
        """Send new demo account details"""
        # Get the MT5 server name from settings if not provided
        server_name = mt5_server_name
        if not server_name:
            try:
                from adminPanel.mt5.models import ServerSetting
                latest_setting = ServerSetting.objects.latest('created_at')
                server_name = latest_setting.server_name_client if latest_setting else 'VTIndex-MT5'
            except Exception:
                server_name = 'VTIndex-MT5'  # Fallback
        
        return EmailSender._send_email(
            user_email,
            'Your Demo Account Has Been Created',
            'demo_account_creation',
            {
                'username': username,
                'account_id': account_id,
                'master_password': master_password,
                'investor_password': investor_password,
                'balance': round(float(balance), 2),
                'leverage': leverage,
                'mt5_server': server_name
            }
        )

    @staticmethod
    def send_mam_account_creation(user_email, username, account_id, master_password, investor_password):
        """Send new MAM account details"""
        return EmailSender._send_email(
            user_email,
            'Your MAM Manager Account Has Been Created',
            'mam_creation',
            {
                'username': username,
                'account_id': account_id,
                'master_password': master_password,
                'investor_password': investor_password,
                'mt5_server': 'VTIndex-MT5'
            }
        )

    @staticmethod
    def send_ib_approval(user_email, username):
        """Send IB approval email"""
        return EmailSender._send_email(
            user_email,
            'Your IB Request Has Been Approved',
            'ib_approved',
            {'username': username}
        )

    @staticmethod
    def send_birthday_wishes(user_email, username):
        """Send birthday wishes email"""
        return EmailSender._send_email(
            user_email,
            'Happy Birthday from VTIndex!',
            'birthday',
            {'username': username}
        )

    @staticmethod
    def send_bulk_emails(recipients, subject, template_name, template_context=None, batch_size=None, batch_delay=None):
        """Send bulk emails in batches using a single SMTP connection and configurable delays.

        Returns a tuple: (success_count, failed_emails)
        """
        if not recipients:
            return 0, []

        # Normalize recipients
        if isinstance(recipients, str):
            recipients = [recipients]

        template_context = template_context or {}
        batch_size = batch_size or getattr(settings, 'EMAIL_BATCH_SIZE', 50)
        batch_delay = batch_delay if batch_delay is not None else getattr(settings, 'EMAIL_SENDING_DELAY', 2.0)

        success_count = 0
        failed_emails = []

        connection = get_connection()
        try:
            # Try opening the connection once to reuse it across messages
            try:
                connection.open()
            except Exception:
                # Some backends open lazily; ignore failures here and let send_messages handle it
                pass

            messages_batch = []

            for i, email in enumerate(recipients):
                try:
                    # Per-recipient context
                    local_ctx = dict(template_context) if isinstance(template_context, dict) else {}
                    local_ctx.setdefault('username', '')
                    local_ctx.setdefault('company_name', getattr(settings, 'DEFAULT_COMPANY_NAME', 'VTIndex'))
                    local_ctx.setdefault('support_email', getattr(settings, 'SUPPORT_EMAIL', 'support@vtindex.com'))
                    local_ctx.setdefault('button_text', local_ctx.get('button_text', 'Go to Dashboard'))
                    local_ctx.setdefault('button_url', local_ctx.get('button_url', 'https://client.vtindex.com'))
                    local_ctx.setdefault('current_year', local_ctx.get('current_year') or getattr(settings, 'CURRENT_YEAR', None))

                    try:
                        html_content = render_to_string(f'emails/{template_name}.html', local_ctx)
                        text_content = strip_tags(html_content)
                    except Exception:
                        # If template rendering fails, fall back to plain message body from context
                        text_content = template_context.get('message', '') or ''
                        html_content = text_content

                    msg = EmailMultiAlternatives(
                        subject=subject,
                        body=text_content,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        to=[email],
                        connection=connection
                    )
                    if html_content and html_content != text_content:
                        msg.attach_alternative(html_content, 'text/html')

                    messages_batch.append(msg)

                    # If batch full, send and sleep
                    if len(messages_batch) >= batch_size:
                        try:
                            connection.send_messages(messages_batch)
                            success_count += len(messages_batch)
                        except Exception as e:
                            logger.exception('Failed to send batch of emails: %s', str(e))
                            # mark all as failed
                            for m in messages_batch:
                                failed_emails.extend(m.to)
                        messages_batch = []
                        if batch_delay and i < len(recipients) - 1:
                            time.sleep(batch_delay)

                except Exception:
                    logger.exception('Failed preparing email for %s', email)
                    failed_emails.append(email)

            # Send any remaining messages
            if messages_batch:
                try:
                    connection.send_messages(messages_batch)
                    success_count += len(messages_batch)
                except Exception as e:
                    logger.exception('Failed to send final batch of emails: %s', str(e))
                    for m in messages_batch:
                        failed_emails.extend(m.to)

        finally:
            try:
                connection.close()
            except Exception:
                pass

        return success_count, failed_emails
