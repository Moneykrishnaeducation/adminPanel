from decimal import Decimal, InvalidOperation
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from adminPanel.permissions import IsAdminOrManager
from adminPanel.models import TradingAccount, Transaction, ActivityLog, CustomUser
from .views import send_deposit_email, send_withdrawal_email, get_client_ip
import logging
from rest_framework.permissions import IsAuthenticated

logger = logging.getLogger(__name__)

class SimpleDepositView(APIView):
    """
    Simplified Deposit View - Bypasses MT5 for testing
    Use this for initial testing when MT5 is not available
    """
    # Use the custom BlacklistCheckingJWTAuthentication from settings instead of overriding
    # authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAdminOrManager]
    
    def options(self, request, *args, **kwargs):
        """Handle CORS preflight requests"""
        response = Response({
            "message": "Simple Deposit View OPTIONS successful",
            "allowed_methods": ["GET", "POST", "OPTIONS"]
        })
        response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-CSRFToken'
        response['Allow'] = 'GET, POST, OPTIONS'
        return response
    
    def get(self, request, *args, **kwargs):
        """Handle GET requests for testing"""
        return Response({
            "message": "Simple DepositView is working correctly",
            "endpoint": "/api/simple-deposit/",
            "methods_supported": ["GET", "POST", "OPTIONS"],
            "user": str(request.user),
            "authenticated": request.user.is_authenticated,
            "permissions": {
                "is_admin": getattr(request.user, 'manager_admin_status', None) == 'Admin',
                "is_manager": getattr(request.user, 'manager_admin_status', None) == 'Manager'
            },
            "status": "ready_for_deposits",
            "mt5_integration": False,
            "test_mode": True
        })

    def post(self, request, *args, **kwargs):
        """Handle POST requests for deposits WITHOUT MT5 integration"""
        logger.info(f"Simple deposit request from user: {request.user.username}")
        
        try:
            # Extract and validate request data
            account_id = request.data.get('account_id')
            amount = request.data.get('amount')
            comment = request.data.get('comment', 'Admin deposit (Test Mode)')
            
            logger.info(f"Deposit data: account_id={account_id}, amount={amount}, comment={comment}")
            
            # Validation
            if not account_id:
                return Response({
                    "error": "account_id is required",
                    "received_data": dict(request.data)
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if not amount:
                return Response({
                    "error": "amount is required",
                    "received_data": dict(request.data)
                }, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                amount = float(Decimal(str(amount)))
                if amount <= 0:
                    return Response({
                        "error": "amount must be greater than zero"
                    }, status=status.HTTP_400_BAD_REQUEST)
            except (ValueError, TypeError, InvalidOperation):
                return Response({
                    "error": "amount must be a valid number"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Find the trading account
            try:
                trading_account = TradingAccount.objects.get(account_id=account_id)
                logger.info(f"Found trading account: {trading_account.account_id} for user: {trading_account.user.username}")
            except TradingAccount.DoesNotExist:
                logger.error(f"Trading account not found: {account_id}")
                return Response({
                    "error": f"Trading account {account_id} not found"
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Check permissions for managers
            if hasattr(request.user, 'manager_admin_status') and request.user.manager_admin_status == 'Manager':
                if getattr(trading_account.user, 'created_by', None) != request.user:
                    return Response({
                        "error": "You don't have permission to deposit to this account"
                    }, status=status.HTTP_403_FORBIDDEN)
            
            # Update account balance directly (WITHOUT MT5)
            old_balance = trading_account.balance
            trading_account.balance += Decimal(str(amount))
            trading_account.save()
            
            logger.info(f"Updated account balance from {old_balance} to {trading_account.balance}")
            
            # Create transaction record
            transaction = Transaction.objects.create(
                user=trading_account.user,
                trading_account=trading_account,
                transaction_type='deposit_trading',
                amount=Decimal(str(amount)),
                description=comment,
                status='approved',
                approved_by=request.user,
                source="Admin Operation (Test Mode)",
                approved_at=timezone.now()
            )
            
            # Create activity log
            try:
                ActivityLog.objects.create(
                    user=request.user,
                    activity=f"Deposited ${amount} to account {account_id}. New balance: ${trading_account.balance} (Test Mode)",
                    ip_address=request.META.get('REMOTE_ADDR', ''),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    timestamp=timezone.now(),
                    related_object_id=transaction.id,
                    related_object_type="Transaction"
                )
            except Exception as log_error:
                logger.warning(f"Failed to create activity log: {log_error}")
            
            # Send notification email
            try:
                send_deposit_email(trading_account.user, transaction)
                logger.info("Deposit notification email sent successfully")
            except Exception as email_error:
                logger.warning(f"Failed to send deposit email: {email_error}")
            
            logger.info(f"Simple deposit completed successfully: transaction_id={transaction.id}")
            
            return Response({
                "message": "Deposit processed successfully (Test Mode)",
                "transaction_id": transaction.id,
                "account_id": account_id,
                "amount": float(amount),
                "old_balance": float(old_balance),
                "new_balance": float(trading_account.balance),
                "comment": comment,
                "status": "approved",
                "created_at": transaction.created_at.isoformat(),
                "mt5_integration": False,
                "test_mode": True,
                "next_steps": "Integrate with MT5 for production use"
            }, status=status.HTTP_201_CREATED)
                
        except Exception as e:
            logger.error(f"Simple deposit processing error: {str(e)}", exc_info=True)
            return Response({
                "error": f"Internal server error: {str(e)}",
                "account_id": account_id if 'account_id' in locals() else None,
                "test_mode": True,
                "debug_info": {
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                }
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SimpleWithdrawView(APIView):
    """
    Simplified Withdraw View - Bypasses MT5 for testing
    """
    # Use the custom BlacklistCheckingJWTAuthentication from settings instead of overriding
    # authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAdminOrManager]
    
    def options(self, request, *args, **kwargs):
        """Handle CORS preflight requests"""
        response = Response({
            "message": "Simple Withdraw View OPTIONS successful",
            "allowed_methods": ["GET", "POST", "OPTIONS"]
        })
        response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-CSRFToken'
        response['Allow'] = 'GET, POST, OPTIONS'
        return response
    
    def get(self, request, *args, **kwargs):
        """Handle GET requests for testing"""
        return Response({
            "message": "Simple WithdrawView is working correctly",
            "endpoint": "/api/simple-withdraw/",
            "methods_supported": ["GET", "POST", "OPTIONS"],
            "user": str(request.user),
            "authenticated": request.user.is_authenticated,
            "status": "ready_for_withdrawals",
            "mt5_integration": False,
            "test_mode": True
        })

    def post(self, request, *args, **kwargs):
        """Handle POST requests for withdrawals WITHOUT MT5 integration"""
        logger.info(f"Simple withdraw request from user: {request.user.username}")

        try:
            # Extract and validate request data
            account_id = request.data.get('account_id')
            amount = request.data.get('amount')
            comment = request.data.get('comment', 'Admin withdrawal (Test Mode)')

            # Validation
            if not account_id:
                return Response({
                    "error": "account_id is required"
                }, status=status.HTTP_400_BAD_REQUEST)

            if not amount:
                return Response({
                    "error": "amount is required"
                }, status=status.HTTP_400_BAD_REQUEST)

            try:
                amount = float(Decimal(str(amount)))
                if amount <= 0:
                    return Response({
                        "error": "amount must be greater than zero"
                    }, status=status.HTTP_400_BAD_REQUEST)
            except (ValueError, TypeError, InvalidOperation):
                return Response({
                    "error": "amount must be a valid number"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Find the trading account
            try:
                trading_account = TradingAccount.objects.get(account_id=account_id)
                logger.info(f"Found trading account: {trading_account.account_id}")
            except TradingAccount.DoesNotExist:
                return Response({
                    "error": f"Trading account {account_id} not found"
                }, status=status.HTTP_404_NOT_FOUND)

            # KYC check: block withdrawal if user is not verified
            user = trading_account.user
            if not (getattr(user, 'id_proof_verified', False) and getattr(user, 'address_proof_verified', False)):
                # Log blocked withdrawal attempt
                ActivityLog.objects.create(
                    user=user,
                    activity=f"Blocked withdrawal attempt: KYC incomplete for user {user.email}",
                    ip_address=request.META.get('REMOTE_ADDR', ''),
                    endpoint=request.path,
                    activity_type="create",
                    activity_category="management",
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )
                return Response({
                    "error": "Withdrawal blocked: Please complete KYC verification before making withdrawals."
                }, status=status.HTTP_403_FORBIDDEN)

            # Check if sufficient balance
            if trading_account.balance < Decimal(str(amount)):
                return Response({
                    "error": f"Insufficient balance. Current balance: ${trading_account.balance}, Requested: ${amount}"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Update account balance directly (WITHOUT MT5)
            old_balance = trading_account.balance
            trading_account.balance -= Decimal(str(amount))
            trading_account.save()

            # Create transaction record
            transaction = Transaction.objects.create(
                user=trading_account.user,
                trading_account=trading_account,
                transaction_type='withdrawal_trading',
                amount=Decimal(str(amount)),
                description=comment,
                status='approved',
                approved_by=request.user,
                source="Admin Operation (Test Mode)",
                approved_at=timezone.now()
            )

            # Send notification email
            try:
                send_withdrawal_email(trading_account.user, transaction)
                logger.info("Withdrawal notification email sent successfully")
            except Exception as email_error:
                logger.warning(f"Failed to send withdrawal email: {email_error}")

            return Response({
                "message": "Withdrawal processed successfully (Test Mode)",
                "transaction_id": transaction.id,
                "account_id": account_id,
                "amount": float(amount),
                "old_balance": float(old_balance),
                "new_balance": float(trading_account.balance),
                "comment": comment,
                "status": "approved",
                "test_mode": True
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Simple withdraw processing error: {str(e)}", exc_info=True)
            return Response({
                "error": f"Internal server error: {str(e)}",
                "test_mode": True
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
