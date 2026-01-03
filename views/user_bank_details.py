from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from ..models import CustomUser
from clientPanel.models import BankDetails as ClientBankDetails
from clientPanel.serializers import BankDetailsSerializer
from ..decorators import role_required
from ..roles import UserRole
from rest_framework.permissions import IsAuthenticated

class UserBankDetailsView(APIView):
    """
    GET: Return bank and crypto details for a user
    POST: Update bank and crypto details for a user
    """

    @role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
    def get(self, request, user_id):
        # Try to get the clientPanel BankDetails for this user
        user = get_object_or_404(CustomUser, user_id=user_id)
        try:
            bank_details = ClientBankDetails.objects.get(user__id=user.id)
            serializer = BankDetailsSerializer(bank_details)
            data = serializer.data
        except ClientBankDetails.DoesNotExist:
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


    @role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
    def post(self, request, user_id):
        user = get_object_or_404(CustomUser, user_id=user_id)
        # Update or create the clientPanel BankDetails for this user
        bank_details, created = ClientBankDetails.objects.get_or_create(user_id=user.id)
        # Only update fields that are present in the request
        for field in ["bank_name", "account_number", "branch_name", "ifsc_code"]:
            if field in request.data:
                setattr(bank_details, field, request.data[field])
        bank_details.save()
        serializer = BankDetailsSerializer(bank_details)
        return Response(serializer.data, status=status.HTTP_200_OK)
