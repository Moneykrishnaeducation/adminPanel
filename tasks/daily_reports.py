from datetime import datetime, timedelta, date, time
from django.utils import timezone
from celery import shared_task
from django.db import transaction
from adminPanel.models import TradingAccount, DailyTradingReport
from django.db.models import Exists, OuterRef, Q
from adminPanel.tasks.monthly_reports import MonthlyReportGenerator
import tempfile
import os
from django.conf import settings

@shared_task(bind=True)
def daily_trading_report_runner(self, report_date_str=None, dry_run=False):
    """Scheduler entry: find eligible accounts and enqueue per-account tasks."""
    if report_date_str:
        report_date = date.fromisoformat(report_date_str)
    else:
        report_date = (timezone.now() - timedelta(days=1)).date()

    # Compute day range in UTC (assumes UTC evaluation)
    start = datetime.combine(report_date, time.min)
    end = start + timedelta(days=1)
    try:
        start = timezone.make_aware(start, timezone.get_current_timezone())
        end = timezone.make_aware(end, timezone.get_current_timezone())
    except Exception:
        pass

    # Simple eligibility: account has open positions OR intraday trades
    # Placeholder models `Position` and `Trade` may need to be replaced with repo-specific models
    from adminPanel.models import Position, Trade  # may raise ImportError if not present

    open_pos_qs = Position.objects.filter(trading_account=OuterRef('pk'), is_open=True)
    intraday_qs = Trade.objects.filter(trading_account=OuterRef('pk')).filter(
        Q(open_time__gte=start, open_time__lt=end) | Q(close_time__gte=start, close_time__lt=end)
    )

    eligible_qs = TradingAccount.objects.annotate(
        has_open=Exists(open_pos_qs),
        has_trade=Exists(intraday_qs)
    ).filter(Q(has_open=True) | Q(has_trade=True)).values_list('id', flat=True)

    # Dispatch per-account tasks in batches
    batch_size = 200
    ids = list(eligible_qs)
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i+batch_size]
        for account_id in batch:
            if dry_run:
                # simply create record
                DailyTradingReport.objects.get_or_create(trading_account_id=account_id, report_date=report_date)
            else:
                process_account_for_daily_report.delay(account_id, report_date.isoformat())


@shared_task(bind=True, max_retries=3)
def process_account_for_daily_report(self, account_id, report_date_str):
    """Generate and send per-account daily report. Implements idempotency via DailyTradingReport."""
    report_date = date.fromisoformat(report_date_str)
    # Acquire or create DailyTradingReport row
    with transaction.atomic():
        report, created = DailyTradingReport.objects.select_for_update().get_or_create(
            trading_account_id=account_id,
            report_date=report_date,
            defaults={'status': 'pending'}
        )
        if report.status == 'sent':
            return {'status': 'skipped', 'reason': 'already sent'}

    # TODO: generate per-account PDF and send email
    # Use existing MonthlyReportGenerator or a dedicated per-account generator
    try:
        # Placeholder: mark as sent for now
        # Generate per-account PDF for the day and send
        acc = TradingAccount.objects.select_related('user').get(id=account_id)
        user = acc.user

        # Build day range
        start = datetime.combine(report_date, time.min)
        end = start + timedelta(days=1)
        try:
            start = timezone.make_aware(start, timezone.get_current_timezone())
            end = timezone.make_aware(end, timezone.get_current_timezone())
        except Exception:
            pass

        generator = MonthlyReportGenerator()

        # Get trading data for the user for the day and filter to this account
        trading_data = generator.get_trading_data_from_mt5(user, start, end)
        trades = [t for t in trading_data.get('trades', []) if str(t.get('account_id')) == str(acc.account_id)]

        # Skip sending if there is no activity: no intraday trades and no open positions
        open_positions = []
        try:
            from adminPanel.mt5.services import MT5ManagerActions
            mt5_manager = MT5ManagerActions()
            if hasattr(mt5_manager, 'get_open_positions'):
                open_positions = mt5_manager.get_open_positions(int(acc.account_id)) or []
        except Exception:
            # If MT5 manager isn't available or errors, treat as no open positions
            open_positions = []

        if (not trades) and (not open_positions):
            # Mark report as skipped due to no activity and return
            with transaction.atomic():
                report.attempts += 1
                report.status = 'skipped'
                report.last_error = 'no open positions and no intraday trades'
                report.save()
            return {'status': 'skipped', 'reason': 'no_activity'}

        # If there are open positions, convert them to the same trade dict format
        # used by the template so they render in the trade history section.
        if open_positions:
            open_trades = []
            for pos in open_positions:
                # Normalize keys and convert timestamp if necessary
                open_time_val = pos.get('date') or pos.get('open_time') or pos.get('time')
                try:
                    if isinstance(open_time_val, (int, float)):
                        open_time_str = datetime.fromtimestamp(open_time_val).strftime('%Y-%m-%d %H:%M')
                    else:
                        open_time_str = str(open_time_val)
                except Exception:
                    open_time_str = str(open_time_val)

                open_trades.append({
                    'open_time': open_time_str,
                    'close_time': '-',
                    'symbol': pos.get('symbol') or pos.get('symbol_name') or 'N/A',
                    'type': pos.get('type') or pos.get('position_type') or 'N/A',
                    'volume': float(pos.get('volume', 0)),
                    'profit': float(pos.get('profit', 0)),
                    'status': 'Open',
                    'account_id': str(acc.account_id)
                })

            # Merge open positions into the trades list so template shows them
            trades = trades + open_trades

        # Prepare template context (reuse report_template.html expectations)
        month_names = [ '', 'January','February','March','April','May','June','July','August','September','October','November','December']
        report_month = f"{month_names[report_date.month]} {report_date.year}"

        context = {
            'company_name': 'VTIndex',
            'client_name': user.get_full_name(),
            'account_id': acc.account_id,
            'address': f"{user.address}, {user.city}, {user.state}, {user.country}".strip(', '),
            'phone': user.phone_number or 'N/A',
            'report_date': timezone.now().strftime('%B %d, %Y'),
            'report_month': report_month,
            'account_type': acc.get_account_type_display(),
            'starting_balance': acc.balance,
            'ending_balance': acc.balance,
            'total_pnl': sum([t.get('profit', 0) for t in trades]) if trades else 0,
            'trades': trades,
            'total_commission': 0,
            'total_volume': sum([t.get('volume', 0) for t in trades]) if trades else 0,
            'logo_path': ''
        }

        # Render template to HTML
        html_template_path = os.path.join(settings.BASE_DIR, 'report_template.html')
        with open(html_template_path, 'r', encoding='utf-8') as f:
            html_template = f.read()

        from django.template import Template as DjangoTemplate, Context
        template = DjangoTemplate(html_template)
        acc_context = context.copy()
        acc_context['is_summary'] = False
        acc_html = template.render(Context(acc_context))

        # Convert to PDF bytes
        pdf_bytes = generator._convert_html_to_pdf(acc_html, user, report_date.year, report_date.month)

        # Save to temp file
        tmp_dir = getattr(settings, 'MEDIA_ROOT', None) or tempfile.gettempdir()
        tmp_fd, tmp_path = tempfile.mkstemp(suffix='.pdf', dir=tmp_dir)
        os.close(tmp_fd)
        with open(tmp_path, 'wb') as f:
            f.write(pdf_bytes)

        # Prepare email
        email_subject = f"📊 Daily Trading Report - {report_month} - Account {acc.account_id}"
        email_context = {
            'user_name': user.get_full_name(),
            'report_month': report_month,
            'company_name': 'VTIndex',
            'total_trades': len(trades),
            'total_volume': acc_context['total_volume'],
            'generated_date': timezone.now().strftime('%B %d, %Y'),
            'password_hint': 'This PDF is not password protected.',
            'password_format': '',
            'support_email': 'support@vtindex.com',
            'login_url': 'https://client.vtindex.com'
        }

        sent = generator._send_report_email_with_attachment(user.email, email_subject, email_context, tmp_path)

        # Update report record
        report.attempts += 1
        if sent:
            report.status = 'sent'
            report.sent_at = timezone.now()
            report.file_url = tmp_path
        else:
            report.status = 'failed'
            report.last_error = 'Email send failed'
        report.save()

        # Cleanup temp file only if you decide to remove; keep for audit currently
        # os.remove(tmp_path)

        return {'status': report.status}
    except Exception as exc:
        report.attempts += 1
        report.status = 'failed'
        report.last_error = str(exc)
        report.save()
        raise self.retry(exc=exc)
