from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
import logging
import time
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from adminPanel.models import CustomUser, ActivityLog
from adminPanel.permissions import IsAdmin, IsManager, OrPermission
from adminPanel.EmailSender import EmailSender
from adminPanel.views.views import get_client_ip
from rest_framework.permissions import IsAuthenticated

logger = logging.getLogger(__name__)


class BroadcastEmailView(APIView):
    """
    API view to send broadcast emails to all active users or specified recipients.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def post(self, request):
        """
        Send broadcast email to users.
        Expected payload:
        {
            "subject": "Email subject",
            "message": "Email message/body",
            "recipients": ["email1@example.com", "email2@example.com"] // Optional, if not provided sends to all active users
        }
        """
        try:
            # Extract data from request
            subject = request.data.get('subject', '').strip()
            message = request.data.get('message', '').strip()
            recipients = request.data.get('recipients', [])
            
            # Validate required fields
            if not subject or not message:
                return Response({
                    'error': 'Subject and message are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # If no specific recipients provided, send to all active users
            if not recipients:
                active_users = CustomUser.objects.filter(is_active=True)
                recipients = list(active_users.values_list('email', flat=True))
                logger.info(f"Sending broadcast email to all {len(recipients)} active users")
            else:
                logger.info(f"Sending email to {len(recipients)} specified recipients")
            
            if not recipients:
                return Response({
                    'error': 'No active users found to send email to'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Decide which template to use: prefer client-provided, otherwise default
            template_name = request.data.get('template') or getattr(settings, 'DEFAULT_EMAIL_TEMPLATE', 'black_gold_template')
            template_context = request.data.get('context') or {}
            # Debug: log template info and chosen template
            logger.debug('BroadcastEmailView received template=%s context=%s, chosen_template=%s', request.data.get('template'), request.data.get('context'), template_name)

            # Send email to each recipient
            success_count = 0
            failed_count = 0
            failed_emails = []
            
            # Get email sending delay from settings. For broadcast sends we prefer
            # EMAIL_SEND_DELAY_SECONDS (new, repo-wide setting) and fall back to
            # legacy EMAIL_SENDING_DELAY or 30 seconds as a sensible default.
            email_delay = getattr(settings, 'EMAIL_SEND_DELAY_SECONDS', None)
            if email_delay is None:
                email_delay = getattr(settings, 'EMAIL_SENDING_DELAY', 30.0)
            try:
                email_delay = float(email_delay)
            except Exception:
                email_delay = 30.0
            logger.debug(f"Using email_delay={email_delay} seconds for broadcast/send-all")
            
            for i, email in enumerate(recipients):
                try:
                    # Build per-recipient context so name/email are available in template
                    local_context = dict(template_context) if isinstance(template_context, dict) else {}
                    local_context.setdefault('header', subject)
                    local_context.setdefault('message', message)
                    # Try to attach user's name fields if available
                    try:
                        user = CustomUser.objects.filter(email=email).first()
                        if user:
                            local_context.setdefault('username', getattr(user, 'username', '') or '')
                            local_context.setdefault('first_name', getattr(user, 'first_name', '') or '')
                            local_context.setdefault('user_name', (getattr(user, 'first_name', '') + ' ' + getattr(user, 'last_name', '')).strip())
                            local_context.setdefault('email', getattr(user, 'email', ''))
                    except Exception:
                        # Ignore user lookup failures and continue with what we have
                        pass

                    # Provide safe defaults for UI elements so emails always include branding/contact
                    local_context.setdefault('company_name', getattr(settings, 'DEFAULT_COMPANY_NAME', 'VTIndex'))
                    local_context.setdefault('support_email', getattr(settings, 'SUPPORT_EMAIL', 'support@vtindex.com'))
                    local_context.setdefault('button_text', local_context.get('button_text', 'Go to Dashboard'))
                    local_context.setdefault('button_url', local_context.get('button_url', 'https://client.vtindex.com'))
                    local_context.setdefault('current_year', local_context.get('current_year') or getattr(settings, 'CURRENT_YEAR', None))

                    # Provide safe defaults for UI elements so emails always include branding/contact
                    template_context.setdefault('company_name', getattr(settings, 'DEFAULT_COMPANY_NAME', 'VTIndex'))
                    template_context.setdefault('support_email', getattr(settings, 'SUPPORT_EMAIL', 'support@vtindex.com'))
                    template_context.setdefault('button_text', template_context.get('button_text', 'Go to Dashboard'))
                    template_context.setdefault('button_url', template_context.get('button_url', 'https://client.vtindex.com'))
                    template_context.setdefault('current_year', template_context.get('current_year') or getattr(settings, 'CURRENT_YEAR', None))
                    template_context.setdefault('username', template_context.get('username', ''))
                    logger.debug('Using template context defaults: company=%s support=%s button=%s %s', template_context['company_name'], template_context['support_email'], template_context['button_text'], template_context['button_url'])

                    if template_name:
                        try:
                            html_content = render_to_string(f'emails/{template_name}.html', local_context)
                            text_content = strip_tags(html_content)

                            email_message = EmailMultiAlternatives(
                                subject=subject,
                                body=text_content,
                                from_email=settings.DEFAULT_FROM_EMAIL,
                                to=[email],
                            )
                            email_message.attach_alternative(html_content, "text/html")
                            email_message.send()
                        except Exception as e:
                            # If template rendering fails, fall back to plain message
                            logger.exception('Template render failed, falling back to plain message')
                            email_message = EmailMessage(
                                subject=subject,
                                body=message,
                                from_email=settings.DEFAULT_FROM_EMAIL,
                                to=[email],
                            )
                            if '<' in message and '>' in message:
                                email_message.content_subtype = 'html'
                            email_message.send()
                    else:
                        # Create email message
                        email_message = EmailMessage(
                            subject=subject,
                            body=message,
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            to=[email],
                        )
                        
                        # Set content type based on message content
                        if '<' in message and '>' in message:  # Basic HTML detection
                            email_message.content_subtype = 'html'
                        
                        # Send email
                        email_message.send()
                    success_count += 1
                    logger.info(f"Successfully sent email to {email} ({i + 1}/{len(recipients)})")
                    
                    # Add delay between emails (except for the last one)
                    if i < len(recipients) - 1:
                        logger.debug(f"Waiting {email_delay} seconds before sending next email...")
                        time.sleep(email_delay)
                    
                except Exception as e:
                    failed_count += 1
                    failed_emails.append(email)
                    logger.error(f"Failed to send email to {email}: {str(e)}")
            
            # Log activity
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Sent broadcast email '{subject}' to {success_count} recipient(s). {failed_count} failed.",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_type="Broadcast Email"
            )
            
            # Prepare response
            response_data = {
                'message': f'Broadcast email sent successfully to {success_count} recipient(s)',
                'success_count': success_count,
                'failed_count': failed_count,
                'total_recipients': len(recipients),
                'template_used': True if template_name else False,
                'template_name': template_name
            }
            
            if failed_emails:
                response_data['failed_emails'] = failed_emails
                response_data['message'] += f'. {failed_count} email(s) failed to send.'
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error in broadcast email: {str(e)}")
            return Response({
                'error': f'Failed to send broadcast email: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SingleEmailView(APIView):
    """
    API view to send email to a single recipient or specific list of recipients.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def post(self, request):
        """
        Send email to specific recipients.
        Expected payload:
        {
            "to": ["email1@example.com", "email2@example.com"],
            "subject": "Email subject",
            "message": "Email message/body",
            "is_html": false // Optional, defaults to false
        }
        """
        try:
            # Extract data from request
            recipients = request.data.get('to', [])
            subject = request.data.get('subject', '').strip()
            message = request.data.get('message', '').strip()
            is_html = request.data.get('is_html', False)
            
            # Validate required fields
            if not recipients or not subject or not message:
                return Response({
                    'error': 'Recipients, subject, and message are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Ensure recipients is a list
            if isinstance(recipients, str):
                recipients = [recipients]
            
            # Decide which template to use: prefer client-provided, otherwise default
            template_name = request.data.get('template') or getattr(settings, 'DEFAULT_EMAIL_TEMPLATE', 'black_gold_template')
            template_context = request.data.get('context') or {}
            # Debug: log template info and chosen template
            logger.debug('SingleEmailView received template=%s context=%s, chosen_template=%s', request.data.get('template'), request.data.get('context'), template_name)

            # Send email to each recipient
            success_count = 0
            failed_count = 0
            failed_emails = []
            
            # Get email sending delay from settings (default 1 second)
            email_delay = getattr(settings, 'EMAIL_SENDING_DELAY', 1.0)
            
            for i, email in enumerate(recipients):
                try:
                    # Build per-recipient context so name/email are available in template
                    local_context = dict(template_context) if isinstance(template_context, dict) else {}
                    local_context.setdefault('header', subject)
                    local_context.setdefault('message', message)
                    try:
                        user = CustomUser.objects.filter(email=email).first()
                        if user:
                            local_context.setdefault('username', getattr(user, 'username', '') or '')
                            local_context.setdefault('first_name', getattr(user, 'first_name', '') or '')
                            local_context.setdefault('user_name', (getattr(user, 'first_name', '') + ' ' + getattr(user, 'last_name', '')).strip())
                            local_context.setdefault('email', getattr(user, 'email', ''))
                    except Exception:
                        pass

                    # Provide safe defaults for UI elements
                    local_context.setdefault('company_name', getattr(settings, 'DEFAULT_COMPANY_NAME', 'VTIndex'))
                    local_context.setdefault('support_email', getattr(settings, 'SUPPORT_EMAIL', 'support@vtindex.com'))
                    local_context.setdefault('button_text', local_context.get('button_text', 'Go to Dashboard'))
                    local_context.setdefault('button_url', local_context.get('button_url', 'https://client.vtindex.com'))
                    local_context.setdefault('current_year', local_context.get('current_year') or getattr(settings, 'CURRENT_YEAR', None))

                    # Provide safe defaults for UI elements so emails always include branding/contact
                    template_context.setdefault('company_name', getattr(settings, 'DEFAULT_COMPANY_NAME', 'VTIndex'))
                    template_context.setdefault('support_email', getattr(settings, 'SUPPORT_EMAIL', 'support@vtindex.com'))
                    template_context.setdefault('button_text', template_context.get('button_text', 'Go to Dashboard'))
                    template_context.setdefault('button_url', template_context.get('button_url', 'https://client.vtindex.com'))
                    template_context.setdefault('current_year', template_context.get('current_year') or getattr(settings, 'CURRENT_YEAR', None))
                    template_context.setdefault('username', template_context.get('username', ''))
                    logger.debug('Using template context defaults: company=%s support=%s button=%s %s', template_context['company_name'], template_context['support_email'], template_context['button_text'], template_context['button_url'])

                    if template_name:
                        try:
                            html_content = render_to_string(f'emails/{template_name}.html', local_context)
                            text_content = strip_tags(html_content)

                            email_message = EmailMultiAlternatives(
                                subject=subject,
                                body=text_content,
                                from_email=settings.DEFAULT_FROM_EMAIL,
                                to=[email.strip()],
                            )
                            email_message.attach_alternative(html_content, "text/html")
                            email_message.send()
                        except Exception:
                            logger.exception('Template render failed, falling back to plain message')
                            email_message = EmailMessage(
                                subject=subject,
                                body=message,
                                from_email=settings.DEFAULT_FROM_EMAIL,
                                to=[email.strip()],
                            )
                            if is_html:
                                email_message.content_subtype = 'html'
                            email_message.send()
                    else:
                        # Create email message
                        email_message = EmailMessage(
                            subject=subject,
                            body=message,
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            to=[email.strip()],
                        )
                        
                        # Set content type
                        if is_html:
                            email_message.content_subtype = 'html'
                        
                        # Send email
                        email_message.send()
                    success_count += 1
                    logger.info(f"Successfully sent email to {email} ({i + 1}/{len(recipients)})")
                    
                    # Add delay between emails (except for the last one)
                    if i < len(recipients) - 1:
                        logger.debug(f"Waiting {email_delay} seconds before sending next email...")
                        time.sleep(email_delay)
                    
                except Exception as e:
                    failed_count += 1
                    failed_emails.append(email)
                    logger.error(f"Failed to send email to {email}: {str(e)}")
            
            # Log activity
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Sent email '{subject}' to {success_count} recipient(s). {failed_count} failed.",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_type="Email"
            )
            
            # Prepare response
            response_data = {
                'message': f'Email sent successfully to {success_count} recipient(s)',
                'success_count': success_count,
                'failed_count': failed_count,
                'total_recipients': len(recipients),
                'template_used': True if template_name else False,
                'template_name': template_name
            }
            
            if failed_emails:
                response_data['failed_emails'] = failed_emails
                response_data['message'] += f'. {failed_count} email(s) failed to send.'
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}")
            return Response({
                'error': f'Failed to send email: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GetActiveUsersEmailsView(APIView):
    """
    API view to get email addresses of all active users.
    """
    permission_classes = [OrPermission(IsAdmin, IsManager)]

    def get(self, request):
        """
        Get email addresses of all active users.
        """
        try:
            # Get all active users' emails
            active_users = CustomUser.objects.filter(is_active=True).values('email', 'first_name', 'last_name')
            
            # Format the response
            users_data = []
            emails = []
            
            for user in active_users:
                users_data.append({
                    'email': user['email'],
                    'name': f"{user['first_name']} {user['last_name']}".strip()
                })
                emails.append(user['email'])
            
            return Response({
                'users': users_data,
                'emails': emails,
                'total_count': len(emails)
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error fetching user emails: {str(e)}")
            return Response({
                'error': f'Failed to fetch user emails: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([OrPermission(IsAdmin, IsManager)])
def send_test_email(request):
    """
    Send a test email to verify email configuration.
    """
    try:
        # Get email from request or use current user's email
        test_email = request.data.get('email', request.user.email)
        
        if not test_email:
            return Response({
                'error': 'Email address is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Send test email using EmailSender
        success = EmailSender.send_test_email(test_email)
        
        if success:
            # Log activity
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Sent test email to {test_email}",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_type="Test Email"
            )
            
            return Response({
                'message': f'Test email sent successfully to {test_email}'
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'error': 'Failed to send test email'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except Exception as e:
        logger.error(f"Error sending test email: {str(e)}")
        return Response({
            'error': f'Failed to send test email: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
