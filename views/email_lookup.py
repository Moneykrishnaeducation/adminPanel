# Add a new endpoint to find users by email
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from ..models import CustomUser
from ..serializers import UserSerializer
from django.db.models import Q
from rest_framework.permissions import IsAuthenticated

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def find_user_by_email(request):
    """
    Find a user by email (exact match)
    """
    email = request.GET.get('email', '')
    if not email:
        return Response({"error": "Email parameter is required"}, status=status.HTTP_400_BAD_REQUEST)
    
    # Try to find the user by exact email match (case insensitive)
    try:
        user = CustomUser.objects.get(email__iexact=email)
        serializer = UserSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except CustomUser.DoesNotExist:
        return Response({"error": f"No user found with email: {email}"}, status=status.HTTP_404_NOT_FOUND)
    except CustomUser.MultipleObjectsReturned:
        # In case multiple users have the same email (should be prevented by unique constraint)
        users = CustomUser.objects.filter(email__iexact=email)
        serializer = UserSerializer(users[0])  # Return the first one
        return Response(serializer.data, status=status.HTTP_200_OK)
