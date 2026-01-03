from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from ..decorators import role_required
from ..roles import UserRole
from adminPanel.models import CustomUser, TradingAccount, Transaction
import csv
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from adminPanel.permissions import IsAdminOrManager


def _iso(dt):
    try:
        return dt.isoformat()
    except Exception:
        return ''


@api_view(['GET'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def export_users_csv(request):
    """Export users with exact headers requested by the frontend."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="users_export.csv"'

    writer = csv.writer(response)
    # Header row as provided
    writer.writerow([
        'user_id','first_name','last_name','dob','phone_number','email','username','address','city','zip_code','state','country','profile_pic','id_proof','address_proof','address_proof_verified','id_proof_verified','user_verified','IB_status','MAM_manager_status','created_by_user_id','created_by_username','manager_admin_status','total_earnings','total_commission_withdrawals','date_joined','is_active','is_staff','parent_ib_user_id','parent_ib_username','commissioning_profile_name','direct_client_count'
    ])

    qs = CustomUser.objects.all().order_by('user_id')
    for u in qs:
        created_by_id = u.created_by.user_id if getattr(u, 'created_by', None) else ''
        created_by_username = u.created_by.username if getattr(u, 'created_by', None) else ''
        parent_ib_id = u.parent_ib.user_id if getattr(u, 'parent_ib', None) else ''
        parent_ib_username = u.parent_ib.username if getattr(u, 'parent_ib', None) else ''
        commissioning_name = u.commissioning_profile.name if getattr(u, 'commissioning_profile', None) else ''

        writer.writerow([
            u.user_id or '',
            u.first_name or '',
            u.last_name or '',
            _iso(u.dob) if getattr(u, 'dob', None) else '',
            u.phone_number or '',
            u.email or '',
            u.username or '',
            u.address or '',
            u.city or '',
            u.zip_code or '',
            u.state or '',
            u.country or '',
            (u.profile_pic.url if getattr(u, 'profile_pic', None) and hasattr(u.profile_pic, 'url') else ''),
            (u.id_proof.url if getattr(u, 'id_proof', None) and hasattr(u.id_proof, 'url') else ''),
            (u.address_proof.url if getattr(u, 'address_proof', None) and hasattr(u.address_proof, 'url') else ''),
            'true' if getattr(u, 'address_proof_verified', False) else 'false',
            'true' if getattr(u, 'id_proof_verified', False) else 'false',
            'true' if getattr(u, 'user_verified', False) else 'false',
            'true' if getattr(u, 'IB_status', False) else 'false',
            'true' if getattr(u, 'MAM_manager_status', False) else 'false',
            created_by_id or '',
            created_by_username or '',
            u.manager_admin_status or '',
            str(u.total_earnings) if hasattr(u, 'total_earnings') else '',
            str(u.total_commission_withdrawals) if hasattr(u, 'total_commission_withdrawals') else '',
            _iso(u.date_joined) if getattr(u, 'date_joined', None) else '',
            'true' if getattr(u, 'is_active', False) else 'false',
            'true' if getattr(u, 'is_staff', False) else 'false',
            parent_ib_id or '',
            parent_ib_username or '',
            commissioning_name or '',
            str(u.direct_client_count) if hasattr(u, 'direct_client_count') else '0'
        ])

    return response


@api_view(['GET'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def export_trading_accounts_csv(request):
    """Export trading accounts using the headers provided by the user request."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="trading_accounts_export.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'id','user_id','user_username','user_email','account_id','copy_coefficient','account_type','account_name','leverage','balance','is_enabled','is_trading_enabled','created_at','group_name','manager_allow_copy','investor_allow_copy','mam_master_account_id','mam_master_account_name','profit_sharing_percentage','risk_level','is_algo_enabled','payout_frequency','package_name','package_id','status','approved_by_user_id','approved_by_username','approved_at','start_date','end_date'
    ])

    qs = TradingAccount.objects.all().order_by('id')
    for a in qs:
        writer.writerow([
            a.id,
            a.user.user_id if a.user else '',
            a.user.username if a.user else '',
            a.user.email if a.user else '',
            a.account_id or '',
            str(getattr(a, 'copy_factor', '') or ''),
            a.account_type or '',
            a.account_name or '',
            str(getattr(a, 'leverage', '')),
            str(getattr(a, 'balance', '')),
            'true' if getattr(a, 'is_enabled', False) else 'false',
            'true' if getattr(a, 'is_trading_enabled', False) else 'false',
            _iso(getattr(a, 'created_at', None)) if getattr(a, 'created_at', None) else '',
            a.group_name or '',
            'true' if getattr(a, 'manager_allow_copy', False) else 'false',
            'true' if getattr(a, 'investor_allow_copy', False) else 'false',
            a.mam_master_account.account_id if getattr(a, 'mam_master_account', None) else '',
            a.mam_master_account.account_name if getattr(a, 'mam_master_account', None) else '',
            str(getattr(a, 'profit_sharing_percentage', '') or ''),
            a.risk_level or '',
            'true' if getattr(a, 'is_algo_enabled', False) else 'false',
            a.payout_frequency or '',
            a.package.name if getattr(a, 'package', None) else '',
            a.package.id if getattr(a, 'package', None) else '',
            a.status or '',
            a.approved_by.user_id if getattr(a, 'approved_by', None) else '',
            a.approved_by.username if getattr(a, 'approved_by', None) else '',
            _iso(getattr(a, 'approved_at', None)) if getattr(a, 'approved_at', None) else '',
            _iso(getattr(a, 'start_date', None)) if getattr(a, 'start_date', None) else '',
            _iso(getattr(a, 'end_date', None)) if getattr(a, 'end_date', None) else ''
        ])

    return response


@api_view(['GET'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def export_transactions_csv(request):
    """Export transactions with the exact headers the user requested."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="transactions_export.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'id','user_id','user_username','user_email','source','trading_account_id','trading_account_name','transaction_type','amount','description','created_at','status','approved_by_user_id','approved_by_username','approved_at','payout_to','external_account','from_account_id','from_account_name','to_account_id','to_account_name','document'
    ])

    qs = Transaction.objects.all().order_by('id')
    for t in qs:
        writer.writerow([
            t.id,
            t.user.user_id if t.user else '',
            t.user.username if t.user else '',
            t.user.email if t.user else '',
            t.source or '',
            t.trading_account.account_id if getattr(t, 'trading_account', None) else '',
            t.trading_account.account_name if getattr(t, 'trading_account', None) else '',
            t.transaction_type or '',
            str(getattr(t, 'amount', '')),
            t.description or '',
            _iso(getattr(t, 'created_at', None)) if getattr(t, 'created_at', None) else '',
            t.status or '',
            t.approved_by.user_id if getattr(t, 'approved_by', None) else '',
            t.approved_by.username if getattr(t, 'approved_by', None) else '',
            _iso(getattr(t, 'approved_at', None)) if getattr(t, 'approved_at', None) else '',
            t.payout_to or '',
            t.external_account or '',
            t.from_account.account_id if getattr(t, 'from_account', None) else '',
            t.from_account.account_name if getattr(t, 'from_account', None) else '',
            t.to_account.account_id if getattr(t, 'to_account', None) else '',
            t.to_account.account_name if getattr(t, 'to_account', None) else '',
            (t.document.url if getattr(t, 'document', None) and hasattr(t.document, 'url') else '')
        ])

    return response
