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

        # Helper function to check if account is CENT type
        def is_cent_account(account, mt5_mgr):
            """Check if account uses CENT alias by querying MT5 and TradeGroup"""
            try:
                from adminPanel.models import TradeGroup
                from django.db.models import Q
                
                # Get group from MT5 directly
                mt5_group = mt5_mgr.get_group_of(int(account.account_id))
                
                print(f"[CENT DEBUG] Account {account.account_id} MT5 group: '{mt5_group}'")
                
                if mt5_group:
                    # Pattern 1: Contains "cent" in the name
                    if 'cent' in mt5_group.lower():
                        print(f"[CENT DEBUG] Account {account.account_id} detected as CENT (contains 'cent')")
                        return True
                    
                    # Pattern 2: Contains "-C-" which typically indicates CENT
                    if '-c-' in mt5_group.lower():
                        print(f"[CENT DEBUG] Account {account.account_id} detected as CENT (contains '-c-')")
                        return True
                    
                    # Pattern 3: Query TradeGroup by MT5 group name and check alias
                    trade_group = TradeGroup.objects.filter(
                        Q(name=mt5_group) | Q(group_id=mt5_group)
                    ).first()
                    
                    if trade_group and trade_group.alias and trade_group.alias.upper() == 'CENT':
                        print(f"[CENT DEBUG] Account {account.account_id} detected as CENT (TradeGroup alias)")
                        return True
                
                # Fallback: check if group_name field contains "cent"
                if account.group_name and 'cent' in account.group_name.lower():
                    print(f"[CENT DEBUG] Account {account.account_id} detected as CENT (account.group_name)")
                    return True
                    
                print(f"[CENT DEBUG] Account {account.account_id} NOT detected as CENT")
                    
            except Exception as e:
                print(f"[CENT ERROR] Error checking CENT account for {account.account_id}: {e}")
            
            return False

        # Check if accounts are CENT type
        from_is_cent = is_cent_account(from_acc, mt5_manager)
        to_is_cent = is_cent_account(to_acc, mt5_manager)
        
        print(f"[CENT DEBUG] Transfer: {from_account_no} (CENT={from_is_cent}) -> {to_account_no} (CENT={to_is_cent}), Amount: {amount}")
        
        # Track actual amounts for different scenarios
        actual_withdraw_amount = amount
        actual_deposit_amount = amount
        
        # Perform MT5 transfer with CENT conversion if needed
        if from_is_cent and not to_is_cent:
            # FROM CENT to regular: amount is in cents, convert to USD
            actual_withdraw_amount = amount
            actual_deposit_amount = amount / 100
            print(f"[CENT DEBUG] CENT->Regular: Withdraw {actual_withdraw_amount} cents, Deposit {actual_deposit_amount} USD")
            
            # Use separate withdraw/deposit operations
            if not mt5_manager.withdraw_funds(int(from_account_no), actual_withdraw_amount, f"Internal transfer to {to_account_no}"):
                return Response({'error': 'MT5 Error - Could not withdraw from source account'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            if not mt5_manager.deposit_funds(int(to_account_no), actual_deposit_amount, f"Internal transfer from {from_account_no}"):
                # Rollback
                mt5_manager.deposit_funds(int(from_account_no), actual_withdraw_amount, f"Rollback transfer to {to_account_no}")
                return Response({'error': 'MT5 Error - Could not deposit to destination account'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            transfer_result = True
            
        elif not from_is_cent and to_is_cent:
            # FROM regular to CENT: amount is in USD, convert to cents
            actual_withdraw_amount = amount
            actual_deposit_amount = amount * 100
            print(f"[CENT DEBUG] Regular->CENT: Withdraw {actual_withdraw_amount} USD, Deposit {actual_deposit_amount} cents")
            
            # Use separate withdraw/deposit operations
            if not mt5_manager.withdraw_funds(int(from_account_no), actual_withdraw_amount, f"Internal transfer to {to_account_no}"):
                return Response({'error': 'MT5 Error - Could not withdraw from source account'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            if not mt5_manager.deposit_funds(int(to_account_no), actual_deposit_amount, f"Internal transfer from {from_account_no}"):
                # Rollback
                mt5_manager.deposit_funds(int(from_account_no), actual_withdraw_amount, f"Rollback transfer to {to_account_no}")
                return Response({'error': 'MT5 Error - Could not deposit to destination account'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            transfer_result = True
            
        else:
            # Both CENT or both regular: standard 1:1 transfer
            print(f"[CENT DEBUG] Same type transfer: {amount}")
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
        ActivityLog.objects.create(
            user=from_acc.user,
            activity=f"Internal transfer: {amount} from {from_account_no} to {to_account_no}. Note: {note}",
            ip_address=request.META.get('REMOTE_ADDR', ''),
            endpoint=request.path,
            activity_type="internal_transfer",
            activity_category="management",
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
