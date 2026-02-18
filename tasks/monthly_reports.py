import os
import logging
from datetime import datetime, timedelta
import time
from decimal import Decimal
from django.conf import settings
from django.template.loader import render_to_string
from django.core.files.base import ContentFile
from django.utils import timezone
from django.db.models import Sum, Count, Q
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.barcharts import VerticalBarChart  
from django.template import Template as DjangoTemplate, Context
import tempfile
import zipfile
from io import BytesIO
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from adminPanel.models import CustomUser, MonthlyTradeReport, TradingAccount, Transaction, CommissionTransaction
from adminPanel.EmailSender import EmailSender

logger = logging.getLogger(__name__)

class MonthlyReportGenerator:
    """
    Enhanced service class for generating automated monthly trading reports.
    
    Features:
    - Automatically runs on the 1st of every month
    - Generates password-protected PDF reports 
    - Password format: first 4 letters of name (lowercase) + first 4 digits of birth year (YYYY)
    - Uses the existing pre-designed PDF template
    - Sends reports via email with password hint
    - Comprehensive error handling and logging
    """
    
    def __init__(self):
        self.report_date = datetime.now()
        # Delay (in seconds) to wait between sending emails to avoid SMTP rate limits
        # Default to 30 seconds unless overridden in Django settings or environment.
        # Read from Django settings EMAIL_SEND_DELAY_SECONDS or from env EMAIL_SEND_DELAY
        delay = getattr(settings, 'EMAIL_SEND_DELAY_SECONDS', None)
        if delay is None:
            try:
                # Default env fallback is 30 seconds
                delay = int(os.environ.get('EMAIL_SEND_DELAY', '30'))
            except Exception:
                delay = 30
        try:
            # If delay is falsy (None or 0), fallback to 30 seconds
            self.email_send_delay = int(delay or 30)
        except Exception:
            self.email_send_delay = 30
        # PDF protection removed - generated PDFs will not be encrypted.
        
    # Password generation and protection removed: PDFs will be sent without password protection.
    
    def get_trading_data_from_mt5(self, user, start_date, end_date):
        """Get trading data from MT5 for the user's accounts"""
        try:
            from adminPanel.mt5.services import MT5ManagerActions
            mt5_service = MT5ManagerActions()
            
            # Get user's trading accounts
            # By default include standard and prop accounts; include MAM accounts only if explicitly enabled
            include_mam = getattr(settings, 'REPORT_INCLUDE_MAM_TRADES', True)
            account_types = ['standard', 'prop']
            if include_mam:
                account_types.append('mam')
            trading_accounts = user.trading_accounts.filter(
                account_type__in=account_types
            )
            
            all_trades = []
            total_volume = Decimal('0.00')
            total_pnl = Decimal('0.00')
            
            for account in trading_accounts:
                try:
                    # Get deals from MT5 for this account
                    deals = mt5_service.get_closed_trades(
                        account.account_id, 
                        start_date, 
                        end_date
                    )
                    
                    if deals:
                        for deal in deals:
                            # Convert MT5 deal object to our format
                            # Handle MT5 timestamp conversion
                            try:
                                # MT5 Time is usually Unix timestamp
                                time_val = getattr(deal, 'Time', '')
                                if isinstance(time_val, (int, float)) and time_val > 0:
                                    open_time = datetime.fromtimestamp(time_val).strftime('%Y-%m-%d %H:%M:%S')
                                else:
                                    open_time = str(time_val)
                                
                                time_close_val = getattr(deal, 'TimeClose', time_val)
                                if isinstance(time_close_val, (int, float)) and time_close_val > 0:
                                    close_time = datetime.fromtimestamp(time_close_val).strftime('%Y-%m-%d %H:%M:%S')
                                else:
                                    close_time = open_time
                            except:
                                open_time = str(getattr(deal, 'Time', ''))
                                close_time = str(getattr(deal, 'TimeClose', open_time))
                            
                            # Map MT5 action types
                            action = getattr(deal, 'Action', 0)
                            trade_type = 'Buy' if action == 0 else 'Sell' if action == 1 else f'Action_{action}'
                            
                            trade_data = {
                                'open_time': open_time,
                                'close_time': close_time,
                                'symbol': getattr(deal, 'Symbol', ''),
                                'type': trade_type,
                                'volume': getattr(deal, 'Volume', 0) / 10000,  # Convert to lots
                                'profit': getattr(deal, 'Profit', 0),
                                'commission': getattr(deal, 'Commission', 0),
                                'swap': getattr(deal, 'Storage', 0),
                                'entry_type': getattr(deal, 'Entry', ''),  # 0=in, 1=out
                                'account_id': account.account_id
                            }
                            all_trades.append(trade_data)
                            
                            # Accumulate totals
                            volume = getattr(deal, 'Volume', 0)
                            profit = getattr(deal, 'Profit', 0)
                            total_volume += Decimal(str(volume / 10000 if volume else 0))  # Convert to lots
                            total_pnl += Decimal(str(profit if profit else 0))
                            
                except Exception as e:
                    logger.warning(f"Failed to get MT5 data for account {account.account_id}: {e}")
                    continue
                    
            return {
                'trades': all_trades,
                'total_volume': total_volume,
                'total_pnl': total_pnl
            }
            
        except Exception as e:
            logger.error(f"Failed to get MT5 trading data for user {user.email}: {e}")
            return {
                'trades': [],
                'total_volume': Decimal('0.00'),
                'total_pnl': Decimal('0.00')
            }
    
    def get_account_balances(self, user, start_date, end_date):
        """Get account balance information"""
        try:
            # Get primary trading account
            primary_account = user.trading_accounts.filter(
                account_type='standard'
            ).first()
            
            if not primary_account:
                primary_account = user.trading_accounts.first()
                
            if not primary_account:
                return {
                    'starting_balance': Decimal('0.00'),
                    'ending_balance': Decimal('0.00'),
                    'account_id': 'N/A',
                    'account_type': 'Standard'
                }
            
            # Try to get real-time balance from MT5
            try:
                from adminPanel.mt5.services import MT5ManagerActions
                mt5_service = MT5ManagerActions()
                account_info = mt5_service.get_account_info(primary_account.account_id)
                current_balance = Decimal(str(account_info.get('balance', primary_account.balance)))
            except:
                current_balance = primary_account.balance
            
            return {
                'starting_balance': primary_account.balance,  # This could be enhanced to get historical balance
                'ending_balance': current_balance,
                'account_id': primary_account.account_id,
                'account_type': primary_account.get_account_type_display()
            }
            
        except Exception as e:
            logger.error(f"Failed to get account balances for user {user.email}: {e}")
            return {
                'starting_balance': Decimal('0.00'),
                'ending_balance': Decimal('0.00'),
                'account_id': 'N/A',
                'account_type': 'Standard'
            }
    
    def generate_pdf_report(self, user, year, month):
        """Generate PDF report using the existing HTML template and convert to PDF"""
        try:
            # Get start and end dates for the month (make timezone-aware if needed)
            start_date = datetime(year, month, 1)
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)
            # Convert to timezone-aware datetimes to avoid naive/local mismatch when USE_TZ=True
            try:
                if getattr(settings, 'USE_TZ', False):
                    start_date = timezone.make_aware(start_date, timezone.get_current_timezone())
                    end_date = timezone.make_aware(end_date, timezone.get_current_timezone())
            except Exception:
                # If timezone not configured or make_aware fails, fall back to naive datetimes
                pass
            
            # Get the month name
            month_names = [
                '', 'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ]
            report_month = f"{month_names[month]} {year}"
            
            # Get trading data
            trading_data = self.get_trading_data_from_mt5(user, start_date, end_date)
            account_data = self.get_account_balances(user, start_date, end_date)

            # Build per-account trade grouping and account summaries
            trades_by_account = {}
            for t in trading_data.get('trades', []):
                acc = str(t.get('account_id') or 'unknown')
                trades_by_account.setdefault(acc, []).append(t)

            # Prepare all trading accounts summary (balances) for header
            accounts_summary = []
            for acc in user.trading_accounts.all():
                accounts_summary.append({
                    'account_id': acc.account_id,
                    'account_type': acc.get_account_type_display(),
                    'balance': acc.balance,
                    'equity': getattr(acc, 'equity', None),
                })
            
            # Get commission data if user is IB
            commission_transactions = CommissionTransaction.objects.filter(
                ib_user=user,
                created_at__gte=start_date,
                created_at__lt=end_date
            )
            total_commission = commission_transactions.aggregate(
                total=Sum('commission_to_ib')
            )['total'] or Decimal('0.00')
            
            # Prepare template context
            context = {
                'company_name': 'VTIndex',
                'client_name': user.get_full_name(),
                # Prefer showing the account(s) that actually have trades in this period.
                # If trades exist for other accounts (e.g., MAM), display those account ids
                # to avoid mismatch between the account summary and trade list.
                'account_id': account_data['account_id'],
                'address': f"{user.address}, {user.city}, {user.state}, {user.country}".strip(', '),
                'phone': user.phone_number or 'N/A',
                'report_date': datetime.now().strftime('%B %d, %Y'),
                'report_month': report_month,
                'account_type': account_data['account_type'],
                'starting_balance': account_data['starting_balance'],
                'ending_balance': account_data['ending_balance'],
                'total_pnl': trading_data['total_pnl'],
                'trades': trading_data['trades'],
                'total_commission': total_commission,
                'total_volume': trading_data['total_volume'],
                'logo_path': ''  # Add logo path if available (will be set below if found)
            }

            # Attempt to locate a company logo in common locations and provide an
            # absolute file URL that PDF renderers (weasyprint) can load.
            try:
                candidate_files = [
                    os.path.join(settings.BASE_DIR, 'VT 0.2 (1).png'),
                    os.path.join(settings.BASE_DIR, 'media', 'vtindex_logo.png'),
                    os.path.join(settings.BASE_DIR, 'media', 'vtindex_logo.jpg'),
                    os.path.join(settings.BASE_DIR, 'media', 'logo.png'),
                    os.path.join(settings.BASE_DIR, 'media', 'logo.jpg'),
                    os.path.join(settings.BASE_DIR, 'media', 'logos', 'vtindex.png'),
                    os.path.join(settings.BASE_DIR, 'static', 'images', 'vtindex_logo.png'),
                    os.path.join(settings.BASE_DIR, 'static', 'logo.png'),
                ]
                found = None
                for p in candidate_files:
                    if p and os.path.exists(p):
                        found = p
                        break
                if found:
                    # Use a proper file URI with percent-encoding for Windows paths so
                    # renderers correctly load files with spaces or parentheses.
                    try:
                        # Use pathlib.Path.as_uri() which correctly builds a file URI on Windows
                        from pathlib import Path
                        url = Path(found).as_uri()
                        context['logo_path'] = url
                    except Exception:
                        # Fallback: naive file:// URL (may fail if path contains special chars)
                        context['logo_path'] = 'file://' + found.replace('\\', '/')
                else:
                    context['logo_path'] = ''
            except Exception:
                context['logo_path'] = ''

            # If trades were returned and they belong to different account(s) than the primary
            # account used for balances, prefer showing the trade account(s) in the report header
            # and include a clarifying note so the balances and trades don't appear mismatched.
            trade_account_ids = set([t.get('account_id') for t in trading_data.get('trades', []) if t.get('account_id')])
            if trade_account_ids:
                # If only a single trade account, show it as the Account ID. If multiple, join them.
                if len(trade_account_ids) == 1:
                    trade_acc = next(iter(trade_account_ids))
                    context['account_id'] = trade_acc
                    # If this trade account differs from the balance account, add a note
                    if str(trade_acc) != str(account_data.get('account_id')):
                        context['account_note'] = f"Trades shown are for trading account {trade_acc}; balances shown are for account {account_data.get('account_id')}."
                else:
                    joined = ', '.join(sorted(list(trade_account_ids)))
                    context['account_id'] = joined
                    context['account_note'] = f"Trades shown are aggregated for accounts: {joined}; balances shown are for account {account_data.get('account_id')}."
            
            # Load and render the HTML template
            html_template_path = os.path.join(settings.BASE_DIR, 'report_template.html')
            with open(html_template_path, 'r', encoding='utf-8') as f:
                html_template = f.read()

            # Use Django template engine to render the HTML template string
            template = DjangoTemplate(html_template)

            # Create a ZIP archive containing one PDF per account plus a summary PDF
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                # Summary PDF (all accounts summary) - do NOT include detailed trade history here
                summary_context = context.copy()
                summary_context['accounts_summary'] = accounts_summary
                # Explicitly mark this as the summary view so template can hide trade history
                summary_context['is_summary'] = True
                # Do not pass detailed trades for the summary PDF
                summary_context['trades'] = []
                # Include deposit/withdrawal transactions for the summary PDF
                try:
                                # Only include approved transactions and map to credit/debit
                                # Include transactions either explicitly linked to the user
                                # or linked via the user's trading accounts
                                user_accounts = list(user.trading_accounts.values_list('id', flat=True))
                                # Include all transaction statuses so statements reflect pending/failed items too
                                trans_qs = Transaction.objects.filter(
                                    created_at__gte=start_date,
                                    created_at__lt=end_date,
                                    transaction_type__in=[
                                        'deposit_trading', 'withdraw_trading', 'commission_withdrawal',
                                        'credit_in', 'credit_out'
                                    ]
                                ).filter(
                                    Q(user=user) | Q(trading_account__id__in=user_accounts)
                                ).select_related('trading_account').order_by('created_at')

                                # Group transactions by account_id (use 'N/A' when trading_account is null)
                                tx_by_acc = {}
                                for t in trans_qs:
                                    raw_acc = t.trading_account.account_id if t.trading_account else 'N/A'
                                    acc_id = str(raw_acc)
                                    tx_by_acc.setdefault(acc_id, []).append(t)

                                # Build a structured transactions dict per account for the summary PDF
                                transactions_by_account = {}
                                for acc_id, tlist in tx_by_acc.items():
                                    # Try to get TradingAccount object to determine starting balance
                                    start_balance = None
                                    try:
                                        if acc_id != 'N/A':
                                            ta = TradingAccount.objects.filter(account_id=acc_id).first()
                                            if ta:
                                                post_net = Transaction.objects.filter(
                                                    trading_account=ta,
                                                    created_at__gte=start_date
                                                ).exclude(status='rejected').aggregate(
                                                    credits=Sum('amount', filter=Q(transaction_type__in=['deposit_trading','credit_in'])),
                                                    debits=Sum('amount', filter=Q(transaction_type__in=['withdraw_trading','credit_out']))
                                                )
                                                credits = post_net.get('credits') or Decimal('0.00')
                                                debits = post_net.get('debits') or Decimal('0.00')
                                                net_since = Decimal(credits) - Decimal(debits)
                                                start_balance = Decimal(ta.balance) - net_since
                                    except Exception:
                                        start_balance = None

                                    running = Decimal('0.00')
                                    rows = []
                                    for t in tlist:
                                        amount = Decimal(str(t.amount))
                                        credit = Decimal('0.00')
                                        debit = Decimal('0.00')
                                        if t.transaction_type in ('deposit_trading', 'credit_in'):
                                            credit = amount
                                            running += credit
                                        elif t.transaction_type in ('withdraw_trading', 'credit_out'):
                                            debit = amount
                                            running -= debit

                                        if start_balance is not None:
                                            available = start_balance + running
                                        else:
                                            available = running

                                        rows.append({
                                            'date': t.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                                            'account_id': acc_id,
                                            'credit': f"{credit:.2f}" if credit else '',
                                            'debit': f"{debit:.2f}" if debit else '',
                                            'available': f"{available:.2f}",
                                            'description': t.description or ''
                                        })

                                    # Normalize key to string for template lookup
                                    transactions_by_account[str(acc_id)] = rows

                                # Provide both grouped and flattened transaction lists for compatibility
                                summary_context['transactions_by_account'] = transactions_by_account
                                # Flattened list kept for templates that expect a single list
                                flat = []
                                for acc_rows in transactions_by_account.values():
                                    flat.extend(acc_rows)
                                summary_context['transactions'] = flat
                except Exception as e:
                    logger.warning(f"Failed to load transactions for summary PDF for {user.email}: {e}")
                    summary_context['transactions'] = []
                    summary_context['transactions_by_account'] = {}
                summary_html = template.render(Context(summary_context))
                summary_pdf = self._convert_html_to_pdf(summary_html, user, year, month)
                summary_name = f"monthly_report_{user.user_id}_{year}_{month:02d}_summary.pdf"
                zf.writestr(summary_name, summary_pdf)

                # Per-account PDFs (only include accounts that have trades; include empty if none)
                for acc in accounts_summary:
                    acc_id = str(acc['account_id'])
                    acc_trades = trades_by_account.get(acc_id, [])
                    # Skip accounts with no trades as requested
                    if not acc_trades:
                        continue
                    acc_context = context.copy()
                    # Ensure aggregated accounts summary is not included in per-account PDFs
                    acc_context.pop('accounts_summary', None)
                    acc_context['account_id'] = acc_id
                    acc_context['account_type'] = acc.get('account_type')
                    acc_context['starting_balance'] = acc.get('balance')
                    acc_context['ending_balance'] = acc.get('balance')
                    acc_context['trades'] = acc_trades
                        # Attach account-specific transactions when available
                    try:
                        acc_context['transactions'] = summary_context.get('transactions_by_account', {}).get(acc_id, [])
                    except Exception:
                        acc_context['transactions'] = []
                    # Mark this as an account-level PDF so template renders trade history
                    acc_context['is_summary'] = False
                    acc_html = template.render(Context(acc_context))
                    acc_pdf = self._convert_html_to_pdf(acc_html, user, year, month)
                    acc_name = f"monthly_report_{user.user_id}_{year}_{month:02d}_{acc_id}.pdf"
                    zf.writestr(acc_name, acc_pdf)

            zip_buffer.seek(0)
            return zip_buffer.getvalue()
            
        except Exception as e:
            logger.error(f"Failed to generate PDF report for user {user.email}: {e}")
            raise
    
    def _convert_html_to_pdf(self, html_content, user, year, month):
        """Convert HTML content to PDF"""
        try:
            # Prefer HTML-based rendering. Try WeasyPrint first (best CSS support)
            try:
                import weasyprint
                pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
                logger.info(f"Successfully generated PDF using WeasyPrint for {user.email}")
                return pdf_bytes
            except ImportError as ie:
                logger.warning(f"WeasyPrint not available: {ie}")
            except Exception as we:
                logger.warning(f"WeasyPrint failed (system libs?): {we}")

            # Sanitize HTML for XHTML-compatible renderers
            try:
                sanitized = html_content.replace('<br>', '<br/>')
            except Exception:
                sanitized = html_content

            # Next try xhtml2pdf (pisa) in XHTML mode
            try:
                from xhtml2pdf import pisa
                from io import BytesIO

                result = BytesIO()
                # Use xhtml=True so parser treats input as XHTML-compatible HTML
                pdf = pisa.CreatePDF(BytesIO(sanitized.encode('utf-8')), dest=result, xhtml=True)

                out_bytes = result.getvalue()
                # Accept output if it appears to be a valid PDF even when pisa reports non-zero errors
                if out_bytes and out_bytes.startswith(b'%PDF'):
                    logger.info(f"xhtml2pdf produced PDF bytes for {user.email} (accepting despite parser warnings)")
                    return out_bytes
                else:
                    logger.error(f"xhtml2pdf failed to produce valid PDF for {user.email}; parser err={getattr(pdf,'err',None)}")
            except ImportError:
                logger.warning("xhtml2pdf not available on this system")
            except Exception as xe:
                logger.error(f"xhtml2pdf failed for {user.email}: {xe}")

            # If both HTML-based converters fail, write sanitized HTML to a debug file
            try:
                import os
                debug_dir = os.path.join(getattr(settings, 'BASE_DIR', '.'), 'report_debug')
                os.makedirs(debug_dir, exist_ok=True)
                debug_path = os.path.join(debug_dir, f'report_debug_{getattr(user, "id", "unknown")}_{year}_{month:02d}.html')
                with open(debug_path, 'w', encoding='utf-8') as f:
                    f.write(sanitized)
                logger.error(f'HTML to PDF conversion failed; sanitized HTML written to {debug_path}')
            except Exception as de:
                logger.error(f'Failed to write debug HTML file: {de}')

            raise RuntimeError('HTML to PDF conversion failed: WeasyPrint/xhtml2pdf unavailable or errored')

        except Exception as e:
            logger.error(f"Failed to convert HTML to PDF for user {user.email}: {e}")
            raise
    
    # Password protection logic removed: PDFs are generated and sent without password encryption.
    
    def _generate_simple_pdf_report(self, user, year, month):
        """Generate a simple PDF report using reportlab as fallback"""
        try:
            # Create a temporary file
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            
            # Container for the 'Flowable' objects
            elements = []
            
            # Define styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=18,
                spaceAfter=30,
                textColor=colors.darkblue
            )
            
            # Add title
            month_names = [
                '', 'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ]
            title = f"Monthly Trading Report - {month_names[month]} {year}"
            elements.append(Paragraph(title, title_style))
            elements.append(Spacer(1, 12))
            
            # Add user information
            user_info = f"""
            <b>Client:</b> {user.get_full_name()}<br/>
            <b>Email:</b> {user.email}<br/>
            <b>Report Date:</b> {datetime.now().strftime('%B %d, %Y')}<br/>
            """
            elements.append(Paragraph(user_info, styles['Normal']))
            elements.append(Spacer(1, 12))
            
            # Add trading summary
            elements.append(Paragraph("Trading Summary", styles['Heading2']))
            
            # Get account information
            account_data = self.get_account_balances(user, 
                                                   datetime(year, month, 1),
                                                   datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1))
            
            summary_data = [
                ['Account ID', account_data['account_id']],
                ['Account Type', account_data['account_type']],
                ['Starting Balance', f"${account_data['starting_balance']:.2f}"],
                ['Ending Balance', f"${account_data['ending_balance']:.2f}"]
            ]
            
            summary_table = Table(summary_data, colWidths=[2*inch, 3*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 14),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            elements.append(summary_table)
            elements.append(Spacer(1, 12))
            
            # Add note about PDF access — not password protected
            password_note = (
                "<b>Important:</b> This PDF is not password protected."
            )
            # Use sanitized line breaks for reportlab paragraph
            elements.append(Paragraph(password_note, styles['Normal']))
            
            # Build PDF
            doc.build(elements)
            buffer.seek(0)
            return buffer.getvalue()
            
        except Exception as e:
            logger.error(f"Failed to generate simple PDF report: {e}")
            raise
    
    def create_monthly_report(self, user, year, month, force_regenerate=False):
        """Create or update a monthly report for a user"""
        try:
            # Check if report already exists
            report, created = MonthlyTradeReport.objects.get_or_create(
                user=user,
                year=year,
                month=month,
                defaults={
                    'status': 'pending',
                    'password_hint': 'First 4 letters of your name + first 4 digits of birth year'
                }
            )
            
            if not created and not force_regenerate and report.status == 'email_sent':
                logger.info(f"Report for {user.email} {year}-{month:02d} already completed")
                return report
            
            # Generate PDF using the new HTML-based service generator
            logger.info(f"Generating PDF report (HTML template) for {user.email} {year}-{month:02d}")
            try:
                from adminPanel.services.monthly_report_generator import MonthlyTradeReportGenerator

                gen = MonthlyTradeReportGenerator(user, datetime(year, month, 1))
                pdf_path = gen.generate_html_pdf_report()

                # Read PDF bytes and save to report_file
                with open(pdf_path, 'rb') as pf:
                    file_bytes = pf.read()

                filename = f"monthly_report_{user.user_id}_{year}_{month:02d}.pdf"
                report.report_file.save(filename, ContentFile(file_bytes))

                # Clean up temp file if generator returned a temp path
                try:
                    import os
                    if pdf_path and os.path.exists(pdf_path):
                        os.remove(pdf_path)
                except Exception:
                    pass
            except Exception as gen_e:
                logger.error(f"HTML generator failed: {gen_e}")
                # Fallback to previous generator to avoid blocking report creation
                file_bytes = self.generate_pdf_report(user, year, month)
                filename = f"monthly_report_{user.user_id}_{year}_{month:02d}.zip"
                report.report_file.save(filename, ContentFile(file_bytes))
            
            # Update report statistics
            trading_data = self.get_trading_data_from_mt5(
                user, 
                datetime(year, month, 1),
                datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
            )
            
            report.total_trades = len(trading_data['trades'])
            report.total_volume = trading_data['total_volume']
            report.status = 'generated'
            report.save()
            
            logger.info(f"Successfully generated report for {user.email} {year}-{month:02d}")
            return report
            
        except Exception as e:
            logger.error(f"Failed to create monthly report for {user.email} {year}-{month}: {e}")
            if 'report' in locals():
                report.status = 'email_failed'
                report.save()
            raise
    
    def send_report_email(self, report):
        """Send the monthly report via email with password hint"""
        try:
            user = report.user
            # Passwords removed - PDFs are sent without password protection
            password = None
            password_message = ("<b>Important:</b> This PDF report is not password protected.")
            
            # Prepare email context
            context = {
                'user_name': user.get_full_name(),
                'report_month': report.report_period,
                'company_name': 'VTIndex',
                'total_trades': report.total_trades,
                'total_volume': report.total_volume,
                'total_commission': getattr(report, 'total_commission', 0),
                'generated_date': report.created_at.strftime('%B %d, %Y'),
                'password_hint': password_message,
                'password_format': "First 4 letters of your name + first 4 digits of birth year",
                'support_email': 'support@vtindex.com',
                'login_url': 'https://client.vtindex.com'
            }
            # Add explicit filename and numeric month/year for template use
            try:
                context['report_year'] = report.year
                context['report_month_num'] = report.month
                context['report_filename'] = f"monthly_report_{report.year}{report.month:02d}.pdf"
            except Exception:
                context['report_filename'] = f"monthly_report_{report.report_period.replace(' ', '_')}.pdf"
            
            # Send email with attachment
            success = self._send_report_email_with_attachment(
                user.email,
                f"📊 Monthly Trading Report - {report.report_period}",
                context,
                report.report_file.path
            )
            
            if success:
                report.status = 'email_sent'
                report.last_email_sent_at = timezone.now()
                logger.info(f"Successfully sent report email to {user.email}")
                # Optional delay between emails to respect SMTP rate limits
                if getattr(self, 'email_send_delay', 0) > 0:
                    logger.info(f"Sleeping {self.email_send_delay}s after sending email to {user.email}")
                    time.sleep(self.email_send_delay)
            else:
                report.status = 'email_failed'
                report.email_attempts += 1
                logger.error(f"Failed to send report email to {user.email}")
            
            report.save()
            return success
            
        except Exception as e:
            logger.error(f"Failed to send report email for {report}: {e}")
            if 'report' in locals():
                report.status = 'email_failed'
                report.email_attempts += 1
                report.save()
            return False
    
    def _send_report_email_with_attachment(self, to_email, subject, context, attachment_path):
        """Send email with PDF attachment using SMTP with enhanced error handling"""
        try:
            # Setup SMTP connection with error handling
            try:
                # Allow separate SMTP settings for reports only. If REPORTS_* settings are
                # provided in Django settings, prefer those, otherwise fall back to global
                # EMAIL_* settings.
                mail_host = getattr(settings, 'REPORTS_EMAIL_HOST', getattr(settings, 'EMAIL_HOST', None))
                mail_port = getattr(settings, 'REPORTS_EMAIL_PORT', getattr(settings, 'EMAIL_PORT', None))
                mail_user = getattr(settings, 'REPORTS_EMAIL_HOST_USER', getattr(settings, 'EMAIL_HOST_USER', None))
                mail_password = getattr(settings, 'REPORTS_EMAIL_HOST_PASSWORD', getattr(settings, 'EMAIL_HOST_PASSWORD', None))
                mail_use_tls = getattr(settings, 'REPORTS_EMAIL_USE_TLS', getattr(settings, 'EMAIL_USE_TLS', True))
                mail_use_ssl = getattr(settings, 'REPORTS_EMAIL_USE_SSL', getattr(settings, 'EMAIL_USE_SSL', False))
                mail_from = getattr(settings, 'REPORTS_DEFAULT_FROM_EMAIL', getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@localhost'))

                if not mail_host or not mail_port:
                    raise RuntimeError('SMTP host/port not configured for report emails')

                # Connect using SSL if configured, otherwise plain SMTP and optionally start TLS
                if mail_use_ssl:
                    server = smtplib.SMTP_SSL(mail_host, int(mail_port), timeout=30)
                else:
                    server = smtplib.SMTP(mail_host, int(mail_port), timeout=30)
                    if mail_use_tls:
                        try:
                            server.starttls()
                        except Exception:
                            # Some SMTP servers may not support STARTTLS; continue without it
                            logger.warning('STARTTLS failed or not supported for reports SMTP server')

                # Login only when credentials are provided
                if mail_user and mail_password:
                    server.login(mail_user, mail_password)
            except Exception as smtp_error:
                logger.error(f"SMTP connection failed: {smtp_error}")
                return False
            
            # Create message
            msg = MIMEMultipart()
            # Use report-specific from-address if set, otherwise default
            msg['From'] = mail_from
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Try to render professional email template
            html_content = self._render_email_template(context)
            
            # Attach HTML content
            msg.attach(MIMEText(html_content, 'html'))
            
            # Attach file if it exists
            if os.path.exists(attachment_path):
                try:
                    with open(attachment_path, 'rb') as f:
                        content = f.read()
                        # Determine MIME subtype by extension
                        lower = attachment_path.lower()
                        if lower.endswith('.pdf'):
                            subtype = 'pdf'
                            filename = f"Monthly_Trading_Report_{context['report_month'].replace(' ', '_')}.pdf"
                        elif lower.endswith('.zip'):
                            subtype = 'zip'
                            filename = f"Monthly_Trading_Report_{context['report_month'].replace(' ', '_')}.zip"
                        else:
                            subtype = 'octet-stream'
                            filename = os.path.basename(attachment_path)

                        attachment = MIMEApplication(content, _subtype=subtype)
                        attachment.add_header('Content-Disposition', 'attachment', filename=filename)
                        msg.attach(attachment)
                        logger.info(f"Attached file: {filename}")
                except Exception as file_error:
                    logger.error(f"Failed to attach file: {file_error}")
                    return False
            else:
                logger.error(f"Attachment file not found: {attachment_path}")
                return False
            
            # Send email
            try:
                server.send_message(msg)
                server.quit()
                logger.info(f"Email successfully sent to {to_email}")
                return True
            except Exception as send_error:
                logger.error(f"Failed to send email: {send_error}")
                try:
                    server.quit()
                except:
                    pass
                return False
            
        except Exception as e:
            logger.error(f"Failed to send email with attachment to {to_email}: {e}")
            return False
    
    def _render_email_template(self, context):
        """Render email template with fallback to default template"""
        template_names = [
            'emails/monthly_trade_report_enhanced.html',
            'emails/monthly_trade_report.html'
        ]
        
        for template_name in template_names:
            try:
                html_content = render_to_string(template_name, context)
                logger.info(f"Successfully rendered email template: {template_name}")
                return html_content
            except Exception as e:
                logger.warning(f"Failed to render template {template_name}: {e}")
                continue
        
        # Fallback to embedded HTML template
        logger.warning("Using fallback embedded email template")
        return self._get_fallback_email_template(context)
    
    def _get_fallback_email_template(self, context):
        """Return fallback email template as a string"""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Monthly Trading Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
                .container {{ max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                .header {{ background: #0591c9; color: white; padding: 20px; border-radius: 5px; text-align: center; margin-bottom: 30px; }}
                .content {{ line-height: 1.6; color: #333; }}
                .password-box {{ background: #e8f4f8; border: 1px solid #0591c9; padding: 15px; border-radius: 5px; margin: 20px 0; text-align: center; }}
                .password-display {{ background: white; border: 2px dashed #0591c9; padding: 10px; margin: 10px 0; font-family: monospace; font-size: 18px; font-weight: bold; color: #0591c9; }}
                .summary {{ background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; font-size: 14px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📊 Monthly Trading Report</h1>
                    <p>{context['report_month']} • {context['company_name']}</p>
                </div>
                
                <div class="content">
                    <p>Dear {context['user_name']},</p>
                    
                    <p>We hope this email finds you well. Your monthly trading report for <strong>{context['report_month']}</strong> is now ready and attached to this email as a secure PDF document.</p>
                    
                    <div class="summary">
                        <h3>📈 Report Summary</h3>
                        <p><strong>Report Period:</strong> {context['report_month']}</p>
                        <p><strong>Total Trades:</strong> {context['total_trades']}</p>
                        <p><strong>Total Volume:</strong> ${context['total_volume']}</p>
                        <p><strong>Generated:</strong> {context['generated_date']}</p>
                    </div>
                    
                    <div class="password-box">
                        <h3>🔒 PDF Access Information</h3>
                        <p>Your PDF report is password protected. Use the password below:</p>
                        <div class="password-display">{context['password_hint']}</div>
                        <small>Password format: {context['password_format']}</small>
                    </div>
                    
                    <p>If you have any questions about your trading report or need assistance accessing the PDF, please don't hesitate to contact our support team.</p>
                    
                    <p>Thank you for choosing {context['company_name']} for your trading needs.</p>
                    
                    <p>Best regards,<br>
                    The {context['company_name']} Team</p>
                </div>
                
                <div class="footer">
                    <p>
                        <strong>Support:</strong> {context['support_email']}<br>
                        <strong>Client Portal:</strong> <a href="{context['login_url']}">{context['login_url']}</a>
                    </p>
                    <p><small>This is an automated message sent on the 1st of every month. Please do not reply to this email.</small></p>
                </div>
            </div>
        </body>
        </html>
        """
    
    def generate_reports_for_all_users(self, year=None, month=None, force_regenerate=False):
        """
        Generate monthly reports for all active users with enhanced error handling.
        This is the main method called by the automated system on the 1st of each month.
        """
        # Default to previous month if not specified
        if not year or not month:
            today = datetime.now()
            if today.month == 1:
                year = today.year - 1
                month = 12
            else:
                year = today.year
                month = today.month - 1
        
        logger.info(f"🚀 Starting automated monthly report generation for {year}-{month:02d}")
        
        # Get all active users with trading accounts
        users = CustomUser.objects.filter(
            is_active=True,
            trading_accounts__isnull=False
        ).distinct()
        
        total_users = users.count()
        successful_reports = 0
        failed_reports = 0
        skipped_reports = 0
        
        logger.info(f"Found {total_users} eligible users for monthly reports")
        
        for user in users:
            try:
                logger.info(f"Processing monthly report for user: {user.email}")
                
                # Check if user has required data for password generation
                if not user.first_name or not user.dob:
                    logger.warning(f"Skipping user {user.email} - missing first_name or date of birth")
                    skipped_reports += 1
                    continue
                
                # Generate report
                report = self.create_monthly_report(user, year, month, force_regenerate)
                
                if report:
                    # Send email
                    if self.send_report_email(report):
                        successful_reports += 1
                        logger.info(f"✅ Successfully processed report for {user.email}")
                    else:
                        failed_reports += 1
                        logger.error(f"❌ Failed to send email for {user.email}")
                else:
                    failed_reports += 1
                    logger.error(f"❌ Failed to generate report for {user.email}")
                    
            except Exception as e:
                logger.error(f"❌ Failed to process report for user {user.email}: {e}")
                failed_reports += 1
        
        # Log final results
        result_summary = {
            'total_users': total_users,
            'successful_reports': successful_reports,
            'failed_reports': failed_reports,
            'skipped_reports': skipped_reports,
            'success_rate': f"{(successful_reports/total_users*100):.1f}%" if total_users > 0 else "0%"
        }
        
        logger.info(
            f"📊 Monthly report generation completed for {year}-{month:02d}:\n"
            f"  Total users: {total_users}\n"
            f"  Successful: {successful_reports}\n"
            f"  Failed: {failed_reports}\n"
            f"  Skipped: {skipped_reports}\n"
            f"  Success rate: {result_summary['success_rate']}"
        )
        
        return result_summary
    
    def check_system_requirements(self):
        """
        Check if the system is properly configured for automated monthly reports.
        Returns a dictionary with system status and any issues found.
        """
        issues = []
        status = {
            'email_configured': False,
            'template_exists': False,
            'report_schedule_active': False,
            'users_with_trading_accounts': 0,
            'users_ready_for_reports': 0,
            'issues': issues
        }
        
        # Check email configuration
        try:
            if hasattr(settings, 'EMAIL_HOST') and settings.EMAIL_HOST:
                status['email_configured'] = True
            else:
                issues.append("EMAIL_HOST not configured in settings")
        except:
            issues.append("Email settings not properly configured")
        
        # Check if report template exists
        template_path = os.path.join(settings.BASE_DIR, 'report_template.html')
        if os.path.exists(template_path):
            status['template_exists'] = True
        else:
            issues.append(f"Report template not found at: {template_path}")
        
        # Check report schedule
        try:
            from adminPanel.models import ReportGenerationSchedule
            active_schedule = ReportGenerationSchedule.objects.filter(is_active=True).first()
            if active_schedule:
                status['report_schedule_active'] = True
            else:
                issues.append("No active report generation schedule found")
        except:
            issues.append("Error checking report generation schedule")
        
        # Check users
        try:
            users_with_accounts = CustomUser.objects.filter(
                is_active=True,
                trading_accounts__isnull=False
            ).distinct().count()
            status['users_with_trading_accounts'] = users_with_accounts
            
            users_ready = CustomUser.objects.filter(
                is_active=True,
                trading_accounts__isnull=False,
                first_name__isnull=False,
                dob__isnull=False
            ).exclude(first_name='').distinct().count()
            status['users_ready_for_reports'] = users_ready
            
            if users_with_accounts == 0:
                issues.append("No users with trading accounts found")
            elif users_ready < users_with_accounts:
                missing_count = users_with_accounts - users_ready
                issues.append(f"{missing_count} users missing first_name or date_of_birth required for password generation")
        except Exception as e:
            issues.append(f"Error checking user data: {e}")
        
        status['system_ready'] = len(issues) == 0
        
        return status
    
    def test_report_generation(self, user_email=None):
        """
        Test the report generation system with a specific user or the first available user.
        This is useful for testing the system before going live.
        """
        try:
            # Find a test user
            if user_email:
                user = CustomUser.objects.filter(email=user_email, is_active=True).first()
                if not user:
                    return {'success': False, 'error': f'User with email {user_email} not found'}
            else:
                user = CustomUser.objects.filter(
                    is_active=True,
                    trading_accounts__isnull=False,
                    first_name__isnull=False,
                    dob__isnull=False
                ).exclude(first_name='').first()
                
                if not user:
                    return {'success': False, 'error': 'No eligible users found for testing'}
            
            logger.info(f"Testing report generation for user: {user.email}")
            
            # Generate test report for previous month
            today = datetime.now()
            if today.month == 1:
                test_year = today.year - 1
                test_month = 12
            else:
                test_year = today.year
                test_month = today.month - 1
            
            # Create report
            report = self.create_monthly_report(user, test_year, test_month, force_regenerate=True)
            
            if not report:
                return {'success': False, 'error': 'Failed to generate test report'}
            
            # Test email sending (but don't actually send in test mode)
            # Password protection removed - no password will be generated
            test_result = {
                'success': True,
                'user_email': user.email,
                'report_period': report.report_period,
                'report_file_exists': bool(report.report_file and os.path.exists(report.report_file.path)),
                'password_generated': False,
                'password': None,
                'report_status': report.status
            }
            
            logger.info(f"Test report generation successful: {test_result}")
            return test_result
            
        except Exception as e:
            logger.error(f"Test report generation failed: {e}")
            return {'success': False, 'error': str(e)}

def _sanitize_reportlab_html(self, html: str) -> str:
    """
    ReportLab Paragraph does NOT support <br>.
    It MUST be <br/>.
    This prevents production crashes.
    """
    if not html:
        return html
    return html.replace('<br>', '<br/>')

