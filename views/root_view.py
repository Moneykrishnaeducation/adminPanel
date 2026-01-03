from django.shortcuts import redirect
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from adminPanel.roles import is_admin, is_manager, is_client
import os
from django.conf import settings
import mimetypes
from rest_framework.permissions import IsAuthenticated

class RootView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request):
        # Check if it's a public path
        if (request.path.startswith('/static/') or 
            request.path.startswith('/.well-known/') or 
            request.path == '/favicon.ico' or
            any(request.path.startswith(path) for path in settings.PUBLIC_PATHS)):
            return self.serve_static_file('client/index.html')

        # Check if accessing login pages
        if request.path == '/admin/login/':
            return self.serve_static_file('admin/login.html')
        elif request.path == '/client/login/':
            return self.serve_static_file('client/login.html')

        # Handle non-public paths
        if not request.user.is_authenticated:
            # For admin paths, redirect to admin login
            if '/admin/' in request.path:
                return redirect('/admin/login/')
            # For all other paths, redirect to client login
            return redirect('/client/login/')

        # Handle authenticated users
        if is_admin(request.user):
            return redirect('admin-dashboard')
        elif is_manager(request.user):
            return redirect('manager-dashboard')
        elif is_client(request.user):
            return redirect('client-dashboard')
        
        # For root path ('/') with no auth, serve the main index
        return self.serve_static_file('client/index.html')

    def serve_static_file(self, relative_path):
        file_path = os.path.join(settings.BASE_DIR, 'static', relative_path)
        try:
            with open(file_path, 'rb') as f:
                content_type, _ = mimetypes.guess_type(file_path)
                return HttpResponse(f.read(), content_type=content_type or 'application/octet-stream')
        except FileNotFoundError:
            return HttpResponse(f'File not found: {relative_path}', status=404)
