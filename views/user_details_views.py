"""
Views for managing user bank and crypto details from admin panel
"""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from adminPanel.models import BankDetails, CryptoDetails, CustomUser
from clientPanel.serializers import BankDetailsSerializer, CryptoDetailsSerializer
from adminPanel.permissions import IsAdminOrManager


@method_decorator(csrf_exempt, name='dispatch')
class UserBankDetailsView(APIView):
    """
    API view to fetch and manage bank details for a specific user
    """
    permission_classes = [IsAuthenticated, IsAdminOrManager]

    def get(self, request, user_id):
        """
        Fetch bank and crypto details for a specific user (combined response)
        """
        try:
            user = CustomUser.objects.get(id=user_id)
            
            # Initialize response data with empty values matching frontend field names
            response_data = {
                'bank-details-name': '',
                'bank-details-account': '',
                'bank-details-ifsc': '',
                'bank-details-branch': '',
                'crypto-wallet': '',
                'crypto-exchange': '',
                'bank_status': 'not_submitted',
                'crypto_status': 'not_submitted'
            }
            
            # Check if user has bank details
            try:
                bank_details = BankDetails.objects.get(user=user)
                response_data.update({
                    'bank-details-name': bank_details.bank_name or '',
                    'bank-details-account': bank_details.account_number or '',
                    'bank-details-ifsc': bank_details.ifsc_code or '',
                    'bank-details-branch': bank_details.branch_name or '',
                    'bank_status': bank_details.status or 'not_submitted',
                    'bank_id': bank_details.id
                })
            except BankDetails.DoesNotExist:
                pass
            
            # Check if user has crypto details
            try:
                crypto_details = CryptoDetails.objects.get(user=user)
                response_data.update({
                    'crypto-wallet': crypto_details.wallet_address or '',
                    # Return currency to admin UI (e.g. BTC/ETH/USDT)
                    'crypto-exchange': crypto_details.currency or '',
                    'crypto_status': crypto_details.status or 'not_submitted',
                    'crypto_id': crypto_details.id
                })
            except CryptoDetails.DoesNotExist:
                pass
            
            response_data['user'] = user.id
            return Response(response_data, status=status.HTTP_200_OK)
                
        except CustomUser.DoesNotExist:
            return Response(
                {'error': 'User not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': f'An error occurred: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def post(self, request, user_id):
        """
        Update or create bank and crypto details for a specific user (combined)
        """
        try:
            user = CustomUser.objects.get(id=user_id)
            
            # Map frontend field names to backend field names
            bank_field_mapping = {
                'bank-details-name': 'bank_name',
                'bank-details-account': 'account_number',
                'bank-details-ifsc': 'ifsc_code',
                'bank-details-branch': 'branch_name',
            }

            # Admin UI now sends crypto as "currency" via the crypto-exchange input
            crypto_field_mapping = {
                'crypto-wallet': 'wallet_address',
                'crypto-exchange': 'currency',
            }

            # Helper: only accept a value if it's present and not an empty/whitespace-only string
            def _get_clean_value(d, key):
                if key in d:
                    val = d.get(key)
                    if val is None:
                        return None
                    if isinstance(val, str) and val.strip() == '':
                        return None
                    return val
                return None

            # Extract and map bank data (skip empty strings)
            bank_data = {}
            for frontend_field, backend_field in bank_field_mapping.items():
                val = _get_clean_value(request.data, frontend_field) or _get_clean_value(request.data, backend_field)
                if val is not None:
                    bank_data[backend_field] = val

            # Extract and map crypto data (skip empty strings)
            crypto_data = {}
            for frontend_field, backend_field in crypto_field_mapping.items():
                val = _get_clean_value(request.data, frontend_field) or _get_clean_value(request.data, backend_field)
                if val is not None:
                    crypto_data[backend_field] = val
            
            # Validation: require either a complete bank (bank_name + account_number) OR a crypto wallet
            bank_has_required = bool(bank_data.get('bank_name')) and bool(bank_data.get('account_number'))
            crypto_has_wallet = bool(crypto_data.get('wallet_address'))

            if not bank_has_required and not crypto_has_wallet:
                # Return structured errors similar to serializer validation to help client-side handling
                return Response({
                    'bank_errors': {
                        'bank_name': ['This field may not be blank.'],
                        'account_number': ['This field may not be blank.']
                    }
                }, status=status.HTTP_400_BAD_REQUEST)

            # Handle bank details if any bank data is provided
            bank_details = None
            if any(bank_data.values()):
                bank_details, created = BankDetails.objects.get_or_create(
                    user=user,
                    defaults={
                        'bank_name': bank_data.get('bank_name', ''),
                        'account_number': bank_data.get('account_number', ''),
                        'ifsc_code': bank_data.get('ifsc_code', ''),
                        'branch_name': bank_data.get('branch_name', ''),
                        'status': 'pending'
                    }
                )
                
                if not created:
                    # Update existing bank details
                    bank_details.bank_name = bank_data.get('bank_name', bank_details.bank_name)
                    bank_details.account_number = bank_data.get('account_number', bank_details.account_number)
                    bank_details.ifsc_code = bank_data.get('ifsc_code', bank_details.ifsc_code)
                    bank_details.branch_name = bank_data.get('branch_name', bank_details.branch_name)
                    bank_details.save()
            
            # Handle crypto details if any crypto data is provided
            crypto_details = None
            if any(crypto_data.values()):
                # Use currency field on model (stored in 'currency') and map accordingly
                crypto_details, created = CryptoDetails.objects.get_or_create(
                    user=user,
                    defaults={
                        'wallet_address': crypto_data.get('wallet_address', ''),
                        'currency': crypto_data.get('currency', ''),
                        'status': 'pending'
                    }
                )

                if not created:
                    # Update existing crypto details
                    crypto_details.wallet_address = crypto_data.get('wallet_address', crypto_details.wallet_address)
                    if 'currency' in crypto_data and crypto_data.get('currency'):
                        crypto_details.currency = crypto_data.get('currency')
                    crypto_details.save()
            
            # Format response data for frontend
            response_data = {
                'bank-details-name': bank_details.bank_name if bank_details else '',
                'bank-details-account': bank_details.account_number if bank_details else '',
                'bank-details-ifsc': bank_details.ifsc_code if bank_details else '',
                'bank-details-branch': bank_details.branch_name if bank_details else '',
                'crypto-wallet': crypto_details.wallet_address if crypto_details else '',
                'crypto-exchange': crypto_details.currency if crypto_details else '',
                'bank_status': bank_details.status if bank_details else 'not_submitted',
                'crypto_status': crypto_details.status if crypto_details else 'not_submitted',
                'user': user.id
            }
            
            if bank_details:
                response_data['bank_id'] = bank_details.id
            if crypto_details:
                response_data['crypto_id'] = crypto_details.id
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except CustomUser.DoesNotExist:
            return Response(
                {'error': 'User not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': f'An error occurred: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@method_decorator(csrf_exempt, name='dispatch')
class UserCryptoDetailsView(APIView):
    """
    API view to fetch and manage crypto details for a specific user
    """
    permission_classes = [IsAuthenticated, IsAdminOrManager]

    def get(self, request, user_id):
        """
        Fetch crypto details for a specific user
        """
        try:
            user = CustomUser.objects.get(id=user_id)
            
            # Check if user has crypto details
            try:
                crypto_details = CryptoDetails.objects.get(user=user)
                
                # Format data for frontend (map backend field names to frontend field names)
                response_data = {
                    'crypto-wallet': crypto_details.wallet_address or '',
                    'crypto-exchange': crypto_details.exchange_name or '',
                    'status': crypto_details.status or 'not_submitted',
                    'id': crypto_details.id,
                    'user': user.id
                }
                
                return Response(response_data, status=status.HTTP_200_OK)
            except CryptoDetails.DoesNotExist:
                return Response({
                    'message': 'No crypto details found for this user',
                    'crypto-wallet': '',
                    'crypto-exchange': '',
                    'status': 'not_submitted'
                }, status=status.HTTP_200_OK)
                
        except CustomUser.DoesNotExist:
            return Response(
                {'error': 'User not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': f'An error occurred: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def post(self, request, user_id):
        """
        Update or create crypto details for a specific user
        """
        try:
            user = CustomUser.objects.get(id=user_id)
            
            # Map frontend field names to backend field names
            field_mapping = {
                'crypto-wallet': 'wallet_address',
                'crypto-exchange': 'exchange_name',
            }
            
            # Extract and map the data
            mapped_data = {}
            for frontend_field, backend_field in field_mapping.items():
                if frontend_field in request.data:
                    mapped_data[backend_field] = request.data.get(frontend_field, '')
                elif backend_field in request.data:
                    mapped_data[backend_field] = request.data.get(backend_field, '')
            
            # Get or create crypto details for the user
            crypto_details, created = CryptoDetails.objects.get_or_create(
                user=user,
                defaults={
                    'wallet_address': mapped_data.get('wallet_address', ''),
                    'exchange_name': mapped_data.get('exchange_name', ''),
                    'status': 'pending'
                }
            )
            
            if not created:
                # Update existing crypto details
                crypto_details.wallet_address = mapped_data.get('wallet_address', crypto_details.wallet_address)
                crypto_details.exchange_name = mapped_data.get('exchange_name', crypto_details.exchange_name)
                crypto_details.save()
            
            # Format response data for frontend
            response_data = {
                'crypto-wallet': crypto_details.wallet_address or '',
                'crypto-exchange': crypto_details.exchange_name or '',
                'status': crypto_details.status,
                'id': crypto_details.id,
                'user': user.id
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except CustomUser.DoesNotExist:
            return Response(
                {'error': 'User not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': f'An error occurred: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def approve_user_bank_details(request, user_id):
    """
    Approve bank details for a specific user
    """
    try:
        user = CustomUser.objects.get(id=user_id)
        bank_details = BankDetails.objects.get(user=user)
        bank_details.status = 'approved'
        bank_details.save()
        
        # Create notification for user
        from adminPanel.utils.notification_utils import create_bank_details_notification
        create_bank_details_notification(user=user, status='approved')
        
        return Response({
            'message': 'Bank details approved successfully',
            'status': 'approved'
        }, status=status.HTTP_200_OK)
        
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    except BankDetails.DoesNotExist:
        return Response({'error': 'Bank details not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def reject_user_bank_details(request, user_id):
    """
    Reject bank details for a specific user
    """
    try:
        user = CustomUser.objects.get(id=user_id)
        bank_details = BankDetails.objects.get(user=user)
        bank_details.status = 'rejected'
        bank_details.save()
        
        return Response({
            'message': 'Bank details rejected',
            'status': 'rejected'
        }, status=status.HTTP_200_OK)
        
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    except BankDetails.DoesNotExist:
        return Response({'error': 'Bank details not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def approve_user_crypto_details(request, user_id):
    """
    Approve crypto details for a specific user
    """
    try:
        user = CustomUser.objects.get(id=user_id)
        crypto_details = CryptoDetails.objects.get(user=user)
        crypto_details.status = 'approved'
        crypto_details.save()
        
        return Response({
            'message': 'Crypto details approved successfully',
            'status': 'approved'
        }, status=status.HTTP_200_OK)
        
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    except CryptoDetails.DoesNotExist:
        return Response({'error': 'Crypto details not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def reject_user_crypto_details(request, user_id):
    """
    Reject crypto details for a specific user
    """
    try:
        user = CustomUser.objects.get(id=user_id)
        crypto_details = CryptoDetails.objects.get(user=user)
        crypto_details.status = 'rejected'
        crypto_details.save()
        
        return Response({
            'message': 'Crypto details rejected',
            'status': 'rejected'
        }, status=status.HTTP_200_OK)
        
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    except CryptoDetails.DoesNotExist:
        return Response({'error': 'Crypto details not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
