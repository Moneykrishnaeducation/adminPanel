
def admin_dashboard(request):
    """
    Serve the main dashboard page (main.html) for /dashboard route.
    """
    file_path = os.path.join(settings.BASE_DIR, 'static', 'admin', 'admin', 'main.html')
    try:
        with open(file_path, 'rb') as f:
            return HttpResponse(f.read(), content_type='text/html')
    except FileNotFoundError:
        return HttpResponse('Dashboard not found', status=404)


    
from django.shortcuts import render, redirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from django.http import HttpResponse
from django.conf import settings
from django.views.static import serve
import os
import mimetypes
from rest_framework.permissions import IsAuthenticated

@api_view(['GET'])
@permission_classes([AllowAny])
def serve_admin_app(request):
    """
    Serve the admin SPA (index.html) for all non-static, non-dashboard routes.
    """
    host = request.get_host().lower() if hasattr(request, 'get_host') else request.META.get('HTTP_HOST','').lower()
    # Allow serving only when host contains admin. (e.g., admin.localhost, admin.vtindex.com)
    if 'admin.' not in host and not host.startswith('admin'):
        return HttpResponse('Not found', status=404)

    if request.path.startswith('/static/'):
        return serve(request, request.path[8:], document_root=settings.STATIC_ROOT)

    # If the request is for /dashboard, serve main.html instead
    if request.path == '/dashboard' or request.path == '/dashboard/':
        return admin_dashboard(request)

    file_path = os.path.join(settings.BASE_DIR, 'static', 'admin', 'index.html')
    try:
        with open(file_path, 'rb') as f:
            return HttpResponse(f.read(), content_type='text/html')
    except FileNotFoundError:
        return HttpResponse('Admin app not found', status=404)


@api_view(['GET'])
@permission_classes([AllowAny])
def redirect_manager_index(request):
    """Redirect legacy /manager/index.html requests to /manager/ (host-preserving)."""
    # Use relative redirect so host is preserved by the client
    return HttpResponse(status=302, headers={'Location': '/manager/'})
