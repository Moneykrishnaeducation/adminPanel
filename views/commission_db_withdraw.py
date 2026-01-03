"""
Database-only commission withdrawal endpoint
"""
from decimal import Decimal
import logging
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from adminPanel.models import CustomUser, TradingAccount, Transaction, ActivityLog
from adminPanel.views.views import get_client_ip
from rest_framework.permissions import IsAuthenticated

class CommissionDBWithdrawView(APIView):
    """
    Admin endpoint to withdraw a specific amount of commission without performing an MT5 deposit.
    Records an approved commission_withdrawal Transaction for the specified amount.
    """
    from adminPanel.permissions import IsAdminOrManager
    permission_classes = [IsAdminOrManager]

    def post(self, request):
        try:
            user_id = request.data.get('userId') or request.data.get('user_id')
            amount = request.data.get('amount')
            
            if not user_id:
                return Response({"error": "userId is required."}, status=status.HTTP_400_BAD_REQUEST)
            
            if not amount or float(amount) <= 0:
                return Response({"error": "Valid amount is required."}, status=status.HTTP_400_BAD_REQUEST)
                
            # Convert amount to Decimal for proper calculation
            amount = Decimal(str(amount))
            
            user = CustomUser.objects.get(user_id=user_id)
            # Calculate withdrawable
            withdrawable_commission = user.total_earnings - user.total_commission_withdrawals
            
            if withdrawable_commission <= 0:
                return Response({"error": "No withdrawable commission available."}, status=status.HTTP_400_BAD_REQUEST)
                
            if amount > withdrawable_commission:
                return Response({"error": f"Amount exceeds available balance. Maximum withdrawable: {withdrawable_commission}"}, 
                               status=status.HTTP_400_BAD_REQUEST)

            # Create a dummy trading account reference if provided, else None
            account_id = request.data.get('accountId')
            trading_account = None
            if account_id:
                trading_account = TradingAccount.objects.filter(account_id=account_id).first()

            # Create approved transaction to withdraw specified amount (database only)
            transaction = Transaction.objects.create(
                user=user,
                trading_account=trading_account,
                transaction_type="commission_withdrawal",
                amount=amount,
                status="approved",
                approved_by=request.user,
                approved_at=timezone.now()
            )

            # Log activity
            ActivityLog.objects.create(
                user=request.user,
                activity=f"Database-only commission withdrawal for user {user.email} (user_id={user.user_id}) amount={amount} - No MT5 deposit",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="create",
                activity_category="management",
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                timestamp=timezone.now(),
                related_object_id=transaction.id,
                related_object_type="Transaction"
            )

            # Force refresh and compute remaining
            user = CustomUser.objects.get(id=user.id)
            remaining_balance = user.total_earnings - user.total_commission_withdrawals

            return Response({
                "success": "Database-only commission withdrawal successful.", 
                "remaining_balance": float(remaining_balance)
            }, status=status.HTTP_200_OK)

        except CustomUser.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logging.exception("Error processing database-only commission withdrawal")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)