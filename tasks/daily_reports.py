from datetime import datetime, timedelta, date, time
from django.utils import timezone
import logging
from django.db import transaction
from adminPanel.models import TradingAccount, DailyTradingReport
from adminPanel.tasks.monthly_reports import MonthlyReportGenerator
import tempfile
import os
from django.conf import settings

def daily_trading_report_runner(report_date_str=None, dry_run=False):
    """Scheduler entry: find eligible accounts and run per-account processing.
    This replaces the previous Celery-based implementation and runs in-process.

    NOTE: We do NOT pre-filter eligibility via MT5 here. Doing 1700+ MT5 calls
    per account at 02:00 fails silently and results in zero reports created.
    process_account_for_daily_report() already skips accounts with no activity,
    so all active accounts are passed through and it handles skipping internally.
    """
    logger = logging.getLogger('daily_reports')

    if report_date_str:
        report_date = date.fromisoformat(report_date_str)
    else:
        report_date = (timezone.now() - timedelta(days=1)).date()

    logger.info('daily_trading_report_runner STARTED for report_date=%s dry_run=%s', report_date, dry_run)

    # Process ALL active trading accounts. Each per-account function checks MT5
    # individually and marks the report 'skipped' if there is no activity.
    qs = TradingAccount.objects.select_related('user').filter(user__isnull=False)
    ids = list(qs.values_list('id', flat=True))

    logger.info('daily_trading_report_runner: found %d accounts to process', len(ids))

    batch_size = 50  # smaller batches to avoid overloading MT5 connections
    results = []
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i+batch_size]
        for account_id in batch:
            if dry_run:
                DailyTradingReport.objects.get_or_create(trading_account_id=account_id, report_date=report_date)
                results.append({'account_id': account_id, 'action': 'dry_created'})
            else:
                # Run synchronously in-process (no Celery)
                try:
                    res = process_account_for_daily_report(account_id, report_date.isoformat())
                    results.append({'account_id': account_id, 'result': res})
                except Exception as exc:
                    logger.exception('Failed processing account %s', account_id)
                    results.append({'account_id': account_id, 'error': str(exc)})

    logger.info('Daily trading report runner completed for %s; eligible=%d, processed=%d', report_date, len(ids), len(results))
    # Return a concise summary useful in management shells
    summary = {
        'report_date': str(report_date),
        'checked_accounts': qs.count(),
        'eligible_accounts': len(ids),
        'processed_count': len(results),
        'sample_results': results[:10]
    }
    # Also print to stdout for management shell immediate feedback
    try:
        print(summary)
    except Exception:
        pass
    return summary


def process_account_for_daily_report(account_id, report_date_str):
    """Generate and send per-account daily report. Implements idempotency via DailyTradingReport.
    Runs synchronously (no Celery)."""
    report_date = date.fromisoformat(report_date_str)
    report = None
    # Acquire or create DailyTradingReport row
    with transaction.atomic():
        report, created = DailyTradingReport.objects.select_for_update().get_or_create(
            trading_account_id=account_id,
            report_date=report_date,
            defaults={'status': 'pending'}
        )
        if report.status == 'sent':
            return {'status': 'skipped', 'reason': 'already sent'}

    # Generate per-account PDF and send email
    logger = logging.getLogger('daily_reports')
    try:
        acc = TradingAccount.objects.select_related('user').get(id=account_id)
        user = acc.user

        # Build day range as NAIVE datetimes — MT5 DealRequest does not accept
        # timezone-aware objects on Windows and silently returns empty results if given one.
        start = datetime.combine(report_date, time.min)   # 00:00:00 naive UTC
        end = start + timedelta(days=1)                    # 00:00:00 next day naive UTC

        # Fetch closed trades directly for THIS account only (not via monthly-report
        # generator which loops ALL user accounts and may silently return empty).
        from adminPanel.mt5.services import MT5ManagerActions
        mt5_manager = MT5ManagerActions()

        raw_deals = []
        try:
            raw_deals = mt5_manager.get_closed_trades(int(acc.account_id), start, end) or []
        except Exception as e:
            logger.warning('get_closed_trades failed for account %s: %s', acc.account_id, e)

        # Convert raw MT5 deal objects to trade dicts
        trades = []
        for deal in raw_deals:
            try:
                time_val = getattr(deal, 'Time', 0)
                open_time = datetime.fromtimestamp(time_val).strftime('%Y-%m-%d %H:%M:%S') if isinstance(time_val, (int, float)) and time_val > 0 else str(time_val)
                time_close_val = getattr(deal, 'TimeClose', time_val)
                close_time = datetime.fromtimestamp(time_close_val).strftime('%Y-%m-%d %H:%M:%S') if isinstance(time_close_val, (int, float)) and time_close_val > 0 else open_time
                action = getattr(deal, 'Action', None)
                trades.append({
                    'open_time': open_time,
                    'close_time': close_time,
                    'symbol': getattr(deal, 'Symbol', 'N/A'),
                    'type': 'Buy' if action == 0 else 'Sell' if action == 1 else 'Unknown',
                    'volume': round(getattr(deal, 'Volume', 0) / 10000, 2),
                    'profit': float(getattr(deal, 'Profit', 0)),
                    'commission': float(getattr(deal, 'Commission', 0)),
                    'swap': float(getattr(deal, 'Storage', 0)),
                    'status': 'Closed',
                    'account_id': str(acc.account_id),
                })
            except Exception as e:
                logger.warning('Error converting deal for account %s: %s', acc.account_id, e)

        # Fetch open positions for this account
        open_positions = []
        try:
            open_positions = mt5_manager.get_open_positions(int(acc.account_id)) or []
        except Exception as e:
            logger.warning('get_open_positions failed for account %s: %s', acc.account_id, e)

        logger.info('Account %s: closed_trades=%d open_positions=%d for %s', acc.account_id, len(trades), len(open_positions), report_date)

        if (not trades) and (not open_positions):
            # No activity — mark skipped and return (do not send email)
            with transaction.atomic():
                report.attempts += 1
                report.status = 'skipped'
                report.last_error = 'no closed trades and no open positions'
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
        generator = MonthlyReportGenerator()
        pdf_bytes = generator._convert_html_to_pdf(acc_html, user, report_date.year, report_date.month)

        # Save to temp file
        tmp_dir = getattr(settings, 'MEDIA_ROOT', None) or tempfile.gettempdir()
        tmp_fd, tmp_path = tempfile.mkstemp(suffix='.pdf', dir=tmp_dir)
        os.close(tmp_fd)
        with open(tmp_path, 'wb') as f:
            f.write(pdf_bytes)

        # Prepare email
        email_subject = f"Daily Trading Report - {report_date.strftime('%d %B %Y')} - Account {acc.account_id}"
        email_context = {
            'user_name': user.get_full_name(),
            'report_month': f"{report_date.strftime('%d %B %Y')}",
            'report_date_label': f"Daily Report - {report_date.strftime('%d %B %Y')}",
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
        # Mark failure on the report row (if available) and return
        try:
            if report:
                report.attempts += 1
                report.status = 'failed'
                report.last_error = str(exc)
                report.save()
        except Exception:
            pass
        # Propagate exception to the caller
        raise
