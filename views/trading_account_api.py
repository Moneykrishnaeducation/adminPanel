from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from adminPanel.models import TradingAccount
from adminPanel.serializers import TradingAccountSerializer
from adminPanel.mt5.services import MT5ManagerActions
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.conf import settings

class ListAccountsByTypeView(APIView):
    permission_classes = [AllowAny]
    """
    API endpoint to list accounts of type standard, mam, mam_investment.
    Returns: account_no, type, name, balance (real-time from MT5)
    """
    def get(self, request):
        # Filter for required account types
        account_types = ['standard', 'mam', 'mam_investment']
        accounts = TradingAccount.objects.filter(account_type__in=account_types)
        mt5_manager = MT5ManagerActions()
        # Prepare response data
        data = []
        for acc in accounts:
            # Fetch real-time balance from MT5
            try:
                balance = mt5_manager.get_balance(acc.account_id)
            except Exception:
                balance = acc.balance if hasattr(acc, 'balance') else 0
            data.append({
                'account_no': acc.account_id,  # use account_id, but keep key as 'account_no' for frontend compatibility
                'type': acc.account_type,
                'name': acc.account_name if hasattr(acc, 'account_name') else getattr(acc, 'name', ''),
                'balance': balance
            })
        return Response({'accounts': data}, status=status.HTTP_200_OK)

class InternalTransferSubmitView(APIView):
    permission_classes = [AllowAny]
    """
    API endpoint to submit an internal transfer between accounts.
    POST data: from_account_no, to_account_no, amount, note
    """
    def post(self, request):
        from_account_no = request.data.get('from_account_no')
        to_account_no = request.data.get('to_account_no')
        amount = request.data.get('amount')
        note = request.data.get('note', '')

        # Validate input
        if not from_account_no or not to_account_no or not amount:
            return Response({'error': 'Missing required fields.'}, status=status.HTTP_400_BAD_REQUEST)
        if from_account_no == to_account_no:
            return Response({'error': 'Cannot transfer to the same account.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except Exception:
            return Response({'error': 'Invalid amount.'}, status=status.HTTP_400_BAD_REQUEST)

        # Get accounts
        try:
            from_acc = TradingAccount.objects.get(account_id=from_account_no)
            to_acc = TradingAccount.objects.get(account_id=to_account_no)
        except TradingAccount.DoesNotExist:
            return Response({'error': 'Account not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Check balance (real-time)
        mt5_manager = MT5ManagerActions()
        from_balance = mt5_manager.get_balance(from_account_no)
        if amount > from_balance:
            return Response({'error': 'Insufficient balance.'}, status=status.HTTP_400_BAD_REQUEST)

        # Perform real MT5 internal transfer
        transfer_result = mt5_manager.internal_transfer(
            login_id_in=to_account_no,
            login_id_out=from_account_no,
            amount=amount
        )
        if not transfer_result:
            return Response({'error': 'Internal transfer failed. Please try again.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Get new balances after transfer
        new_from_balance = mt5_manager.get_balance(from_account_no)
        new_to_balance = mt5_manager.get_balance(to_account_no)

        # Record in Transaction history
        from adminPanel.models import Transaction, ActivityLog
        from django.utils import timezone
        from decimal import Decimal
        print("[DEBUG] Creating Transaction with values:")
        print("user:", from_acc.user)
        print("from_account:", from_acc)
        print("to_account:", to_acc)
        print("transaction_type:", 'internal_transfer')
        print("amount:", Decimal(str(amount)))
        print("status:", 'approved')
        print("description:", note)
        print("created_at:", timezone.now())
        import traceback
        try:
            transaction = Transaction.objects.create(
                user=from_acc.user,
                from_account=from_acc,
                to_account=to_acc,
                transaction_type='internal_transfer',
                amount=Decimal(str(amount)),
                status='approved',
                description=note,
                created_at=timezone.now()
            )
        except Exception as e:
            print("[ERROR] Exception while creating Transaction:", e)
            traceback.print_exc()
            return Response({'error': 'Transaction create failed', 'details': str(e)}, status=500)
        # Record in ActivityLog
        # Use request.user if authenticated (admin transfer), otherwise use from_acc.user (client transfer)
        log_user = request.user if request.user and request.user.is_authenticated else from_acc.user
        ActivityLog.objects.create(
            user=log_user,
            activity=f"Internal transfer: {amount} from {from_account_no} to {to_account_no}. Note: {note}",
            ip_address=request.META.get('REMOTE_ADDR', ''),
            endpoint=request.path,
            activity_type="create",
            activity_category="management" if (request.user and request.user.is_authenticated) else "client",
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            timestamp=timezone.now(),
            related_object_id=transaction.id,
            related_object_type="Transaction"
        )

        return Response({
            'success': True,
            'message': 'Transfer submitted successfully.',
            'from_account_no': from_account_no,
            'to_account_no': to_account_no,
            'amount': amount,
            'from_balance': new_from_balance,
            'to_balance': new_to_balance,
            'transaction_id': transaction.id
        }, status=status.HTTP_200_OK)


class SendTransferNotificationView(APIView):
    permission_classes = [IsAuthenticated]
    """
    API endpoint to send transfer notification emails to both from and to account holders.
    If both accounts belong to same user (same email), send only one email.
    If different users, send email to both.
    """
    def post(self, request):
        try:
            recipients = request.data.get('recipients', [])
            from_account = request.data.get('from_account', 'N/A')
            from_account_number = request.data.get('from_account_number', 'N/A')
            to_account = request.data.get('to_account', 'N/A')
            to_account_number = request.data.get('to_account_number', 'N/A')
            amount = request.data.get('amount', 0)
            note = request.data.get('note', '')
            
            if not recipients:
                return Response({'success': False, 'error': 'No recipients provided'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Remove duplicates while preserving order
            unique_recipients = list(dict.fromkeys(recipients))
            
            # Prepare email context
            email_context = {
                'from_account': from_account,
                'from_account_number': from_account_number,
                'to_account': to_account,
                'to_account_number': to_account_number,
                'amount': amount,
                'note': note,
                'transfer_type': 'Internal Transfer Notification'
            }
            
            # Send email to each unique recipient
            for recipient_email in unique_recipients:
                subject = f"Internal Transfer Notification - {amount} transferred"
                
                html_message = render_to_string("emails/internal_transfer.html", email_context)
                
                email = EmailMessage(
                    subject=subject,
                    body=html_message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[recipient_email],
                )
                email.content_subtype = "html"
                email.send()
            
            return Response({
                'success': True,
                'message': f'Notification emails sent to {len(unique_recipients)} recipient(s)',
                'recipients': unique_recipients
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            import traceback
            print(f"[ERROR] Failed to send transfer emails: {e}")
            traceback.print_exc()
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
