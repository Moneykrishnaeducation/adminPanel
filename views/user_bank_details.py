from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from ..models import CustomUser
from clientPanel.models import BankDetails as ClientBankDetails
from clientPanel.serializers import BankDetailsSerializer
from rest_framework.permissions import IsAuthenticated

class UserBankDetailsView(APIView):
    """
    GET: Return bank and crypto details for a user
    POST: Update bank and crypto details for a user
    """
    permission_classes = [IsAuthenticated]
    
    def _get_user(self, user_id):
        """Helper to get user by user_id or id"""
        # Ensure user_id is an integer
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            print(f"DEBUG: Could not convert {user_id} to int")
            pass
        
        print(f"DEBUG: _get_user called with user_id={user_id}, type={type(user_id)}")
        
        try:
            # First try by user_id field
            user = CustomUser.objects.get(user_id=user_id)
            print(f"DEBUG: _get_user SUCCESS - found by user_id: {user}")
            return user
        except CustomUser.DoesNotExist:
            print(f"DEBUG: user_id lookup failed, trying by id")
        except Exception as e:
            print(f"DEBUG: user_id lookup exception: {type(e).__name__}: {str(e)}")
        
        try:
            # Fallback to primary key id
            user = CustomUser.objects.get(id=user_id)
            print(f"DEBUG: _get_user SUCCESS - found by id: {user}")
            return user
        except CustomUser.DoesNotExist:
            print(f"DEBUG: id lookup also failed")
            raise
        except Exception as e:
            print(f"DEBUG: id lookup exception: {type(e).__name__}: {str(e)}")
            raise

    def get(self, request, user_id):
        # Try to get the clientPanel BankDetails for this user
        print(f"DEBUG: GET bank-details called with user_id={user_id}, type={type(user_id)}")
        try:
            user_id_int = int(user_id)
            print(f"DEBUG: Converted to int: {user_id_int}")
        except:
            user_id_int = user_id
            
        try:
            user = self._get_user(user_id)
            print(f"DEBUG: Found user with id={user.id}, user_id={user.user_id}, email={user.email}")
        except CustomUser.DoesNotExist as e:
            print(f"DEBUG: User not found - tried user_id and id lookup")
            print(f"DEBUG: Exception: {str(e)}")
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        try:
            bank_details = ClientBankDetails.objects.get(user__id=user.id)
            print(f"DEBUG: Found bank details: {bank_details.bank_name}")
            serializer = BankDetailsSerializer(bank_details)
            data = serializer.data
        except ClientBankDetails.DoesNotExist:
            print(f"DEBUG: No bank details found, returning empty response")
            data = {
                "bank_name": "",
                "account_number": "",
                "branch_name": "",
                "ifsc_code": "",
                "bank_doc": None,
                "status": "",
                "created_at": None,
                "updated_at": None
            }
        return Response(data)

    def post(self, request, user_id):
        try:
            user = self._get_user(user_id)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        # Update or create the clientPanel BankDetails for this user
        bank_details, created = ClientBankDetails.objects.get_or_create(user_id=user.id)
        # Only update fields that are present in the request
        for field in ["bank_name", "account_number", "branch_name", "ifsc_code"]:
            if field in request.data:
                setattr(bank_details, field, request.data[field])
        bank_details.save()
        serializer = BankDetailsSerializer(bank_details)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, user_id):
        try:
            user = self._get_user(user_id)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        # Update or create the clientPanel BankDetails for this user
        bank_details, created = ClientBankDetails.objects.get_or_create(user_id=user.id)
        # Only update fields that are present in the request
        for field in ["bank_name", "account_number", "branch_name", "ifsc_code", "wallet_address", "exchange_name"]:
            if field in request.data:
                setattr(bank_details, field, request.data[field])
        bank_details.save()
        serializer = BankDetailsSerializer(bank_details)
        return Response(serializer.data, status=status.HTTP_200_OK)
