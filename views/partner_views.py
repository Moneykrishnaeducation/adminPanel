from django.http import JsonResponse
from django.db import models
from django.db.models import Q
from django.utils import timezone
import logging
logger = logging.getLogger(__name__)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from adminPanel.permissions import IsAdminOrManager

from django.http import JsonResponse
from adminPanel.models import CustomUser  # Use CustomUser as the user model


@api_view(['POST'])
@permission_classes([IsAuthenticated])


def disable_ib_user_view(request, user_id):
    user = request.user
    username = getattr(user, 'username', '')
    email = getattr(user, 'email', '')
    display_name = username if username else email
    # Get target IB user info
    from adminPanel.models import CustomUser
    try:
        target_user = CustomUser.objects.get(user_id=user_id)
        target_username = getattr(target_user, 'username', '')
        target_email = getattr(target_user, 'email', '')
        target_display = target_username if target_username else target_email
        # Actually disable IB status
        target_user.IB_status = False
        target_user.save(update_fields=['IB_status'])
        # Unassign all child clients
        from adminPanel.models import CustomUser
        affected_clients = CustomUser.objects.filter(parent_ib=target_user)
        affected_count = affected_clients.update(parent_ib=None)
        logger.info(f"[IB DISABLE] Target IB user {user_id} ({target_display}) disabled by admin id={getattr(user, 'id', 'unknown')}, name={display_name}. Unassigned {affected_count} clients.")
        return JsonResponse({'success': True, 'message': f'IB disabled and {affected_count} clients unassigned'})
    except Exception as e:
        logger.error(f"[IB DISABLE] Failed for user {user_id}: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@api_view(['POST'])
@permission_classes([IsAuthenticated])


def enable_ib_user_view(request, user_id):
    user = request.user
    username = getattr(user, 'username', '')
    email = getattr(user, 'email', '')
    display_name = username if username else email
    # Get target IB user info
    from adminPanel.models import CustomUser
    try:
        target_user = CustomUser.objects.get(user_id=user_id)
        target_username = getattr(target_user, 'username', '')
        target_email = getattr(target_user, 'email', '')
        target_display = target_username if target_username else target_email
        # Actually enable IB status
        target_user.IB_status = True
        target_user.save(update_fields=['IB_status'])
        logger.info(f"[IB ENABLE] Target IB user {user_id} ({target_display}) enabled by admin id={getattr(user, 'id', 'unknown')}, name={display_name}")
        return JsonResponse({'success': True, 'message': 'IB enabled'})
    except Exception as e:
        logger.error(f"[IB ENABLE] Failed for user {user_id}: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from ..decorators import role_required
from ..roles import UserRole

@api_view(['GET'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def commissioning_profiles_list(request):
    return Response({'message': 'Commissioning profiles list'})

@api_view(['GET'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def get_partner_profile(request, partner_id):
    from adminPanel.models import CustomUser
    try:
        partner = CustomUser.objects.get(user_id=partner_id)
        profile_name = getattr(partner, "commission_profile_name", None)
        profile_id = None
        commissioning_profile = getattr(partner, "commissioning_profile", None)
        if commissioning_profile:
            if isinstance(commissioning_profile, int):
                profile_id = commissioning_profile
            elif hasattr(commissioning_profile, "id"):
                profile_id = commissioning_profile.id
                if not profile_name:
                    profile_name = getattr(commissioning_profile, "name", "N/A")
        if not profile_name:
            profile_name = "N/A"
        return Response({
            "profileName": profile_name,
            "profileId": profile_id
        }, status=status.HTTP_200_OK)
    except CustomUser.DoesNotExist:
        return Response({"error": "Partner not found."}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST', 'PUT'])
@role_required([UserRole.ADMIN.value])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def update_partner_profile(request, partner_id):
    from adminPanel.models import CustomUser
    from adminPanel.models import CommissioningProfile
    if request.method == 'POST':
        profile_id = request.data.get('profile_id')
        if not profile_id:
            return Response({'error': 'Missing profile_id'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            partner = CustomUser.objects.get(user_id=partner_id)
        except CustomUser.DoesNotExist:
            return Response({'error': 'Partner not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            profile = CommissioningProfile.objects.get(id=profile_id)
        except CommissioningProfile.DoesNotExist:
            return Response({'error': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        partner.commissioning_profile = profile
        partner.commission_profile_name = profile.name
        partner.save()
        return Response({'success': True, 'profileName': profile.name, 'profileId': profile.id}, status=status.HTTP_200_OK)
    return Response({'error': 'Method not allowed'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


def ib_user_statistics_view(request, user_id):
    # Example logic: count clients, sum earnings, sum commission for the IB user
    try:
        ib_user = CustomUser.objects.get(user_id=user_id, IB_status=True)
        # Count clients where parent_ib is this IB user
        total_clients = CustomUser.objects.filter(parent_ib=ib_user).count()
        # Compute total earnings and withdrawals using the same safe logic as the client panel
        # (fall back to older fields if the newer ones are not present)
        try:
            total_earnings = float(getattr(ib_user, 'total_earnings', 0) or 0)
        except Exception:
            try:
                total_earnings = float(getattr(ib_user, 'earnings', 0) or 0)
            except Exception:
                total_earnings = 0.0

        try:
            total_withdrawals = float(getattr(ib_user, 'total_commission_withdrawals', 0) or 0)
        except Exception:
            total_withdrawals = 0.0

        # Withdrawable balance mirrors the client panel calculation
        withdrawable_balance = total_earnings - total_withdrawals

        # Keep legacy/other commission field for backward compatibility
        commission = getattr(ib_user, 'commission', 0)


        # Calculate actual withdrawable commission from CommissionTransaction
        from adminPanel.models import CommissionTransaction, Transaction
        # Debug and fetch withdrawals with flexible status check
        withdrawals = Transaction.objects.filter(
            user=ib_user,
            transaction_type="commission_withdrawal"
        )

    
        
        # logger.info(f"Withdrawn commission for IB {ib_user.email}: {withdrawn_commission}")


        # Dynamic levels breakdown based on commission profile
        levels = []
        commission_profile = getattr(ib_user, 'commissioning_profile', None)
        if commission_profile and hasattr(commission_profile, 'get_level_percentages_list'):
            percentages = commission_profile.get_level_percentages_list()
            # If profile exists but returns empty percentages, fall back to a single-level summary
            if not percentages:
                # aggregate total commission across all levels - exclude demo account commissions
                total_comm = CommissionTransaction.objects.filter(
                    ib_user=ib_user
                ).exclude(
                    client_trading_account__account_type='demo'
                ).aggregate(total=models.Sum('commission_to_ib'))['total'] or 0
                levels.append({
                    'level': 1,
                    'client_count': total_clients,
                    'total_commission': float(total_comm)
                })
                percentages = []
            # Calculate commission for each level from CommissionTransaction
            for idx, pct in enumerate(percentages, 1):  # start from 1 for level numbers
                level_commission = CommissionTransaction.objects.filter(
                    ib_user=ib_user,
                    ib_level=idx
                ).exclude(
                    client_trading_account__account_type='demo'
                ).aggregate(total=models.Sum('commission_to_ib'))['total'] or 0
                
                # Count clients at each level with detailed logging
                if idx == 1:
                    # Level 1: All direct clients (both regular clients and IB clients)
                    level_clients = CustomUser.objects.filter(parent_ib=ib_user).count()
                    direct_clients = CustomUser.objects.filter(parent_ib=ib_user, IB_status=False).count()
                    direct_ibs = CustomUser.objects.filter(parent_ib=ib_user, IB_status=True).count()
                    
                elif idx == 2:
                    # Level 2: Clients of direct IB clients
                    direct_ibs = CustomUser.objects.filter(parent_ib=ib_user, IB_status=True)
                    level_clients = 0
                    for direct_ib in direct_ibs:
                        ib_clients = CustomUser.objects.filter(parent_ib=direct_ib).count()
                        level_clients += ib_clients
                    
                elif idx == 3:
                    # Level 3: Clients of level 2 IBs
                    level_2_ibs = CustomUser.objects.filter(
                        parent_ib__parent_ib=ib_user,
                        parent_ib__IB_status=True,
                        IB_status=True
                    )
                    level_clients = 0
                    for l2_ib in level_2_ibs:
                        ib_clients = CustomUser.objects.filter(parent_ib=l2_ib).count()
                        level_clients += ib_clients
                else:
                    level_clients = 0
                

                
                levels.append({
                    'level': idx,
                    'client_count': level_clients,
                    'total_commission': float(level_commission)
                })
        else:
            # Fallback: include level 1 summary using CommissionTransaction aggregate if available
            # Exclude demo account commissions
            total_comm = CommissionTransaction.objects.filter(
                ib_user=ib_user
            ).exclude(
                client_trading_account__account_type='demo'
            ).aggregate(total=models.Sum('commission_to_ib'))['total'] or 0
            levels.append({
                'level': 1,
                'client_count': total_clients,
                'total_commission': float(total_comm)
            })

        return JsonResponse({
            'total_clients': total_clients,
            'total_earnings': total_earnings, #totalCommission
            'commission': commission,
            'withdrawable_balance': float(withdrawable_balance), #withdrawableCommission
            'total_withdrawals': float(total_withdrawals), #withdrawn_commission
            'levels': levels
        })
    except CustomUser.DoesNotExist:
        return JsonResponse({'error': 'IB user not found'}, status=404)
