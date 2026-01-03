from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.conf import settings
from django.http import FileResponse, Http404
from django.contrib.auth import get_user_model
import os

User = get_user_model()

class AdminUserProfileImageView(APIView):
    """
    API endpoint to get a user's profile image by email (admin access).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, email):
        try:
            user = User.objects.get(email=email)
            # Try to use the profile_pic field if set and file exists
            if user.profile_pic:
                profile_pic_path = str(user.profile_pic)
                if profile_pic_path.startswith(settings.MEDIA_URL):
                    profile_pic_path = profile_pic_path[len(settings.MEDIA_URL):]
                file_path = os.path.join(settings.MEDIA_ROOT, profile_pic_path)
                if os.path.exists(file_path):
                    ext = os.path.splitext(file_path)[1].lower()
                    content_type = {
                        '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg',
                        '.png': 'image/png',
                        '.webp': 'image/webp',
                        '.gif': 'image/gif',
                    }.get(ext, 'application/octet-stream')
                    return FileResponse(open(file_path, 'rb'), content_type=content_type)
            # If not found, try to find by email-based filename (new and legacy)
            base_dir = os.path.join(settings.MEDIA_ROOT, 'profile_images')
            possible_files = []
            for f in os.listdir(base_dir):
                # Check for new format: full email at the start
                if f.startswith(email):
                    possible_files.append(f)
                # Check for legacy format: email with _at_ and _
                if f.startswith(''.join([c if c.isalnum() else '_' for c in email])):
                    possible_files.append(f)
            if possible_files:
                # Use the most recent file (by modified time)
                possible_files = sorted(possible_files, key=lambda x: os.path.getmtime(os.path.join(base_dir, x)), reverse=True)
                file_path = os.path.join(base_dir, possible_files[0])
                ext = os.path.splitext(file_path)[1].lower()
                content_type = {
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.png': 'image/png',
                    '.webp': 'image/webp',
                    '.gif': 'image/gif',
                }.get(ext, 'application/octet-stream')
                return FileResponse(open(file_path, 'rb'), content_type=content_type)
            raise Http404("No profile image found for this user.")
        except User.DoesNotExist:
            raise Http404("User not found.")
        except Exception as e:
            raise Http404(str(e))
