import os
import logging
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)


def _is_allowed_extension(filename):
    ext = os.path.splitext(filename)[1].lower()
    allowed = getattr(settings, 'ADMIN_UPLOAD_ALLOWED_EXTENSIONS', None)
    if allowed is None:
        return True
    return ext in allowed


def _ensure_unique_filename(dest_dir, filename):
    base, ext = os.path.splitext(filename)
    candidate = filename
    i = 1
    while os.path.exists(os.path.join(dest_dir, candidate)):
        candidate = f"{base}_{i}{ext}"
        i += 1
    return candidate


@csrf_exempt
def upload_admin_files(request):
    """Accept multipart POST with files in field 'files' and save them
    to the configured `ADMIN_UPLOAD_DIR` (defaults to <project>/admin_uploads).
    Only allow staff/superuser users. Preserves original filenames; if a
    collision occurs a numeric suffix is appended (e.g. file_1.pdf).
    Performs extension and max-size checks based on settings.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    # Allow uploads for staff/superuser OR for users with role='admin' or manager_admin_status='Admin'
    allowed = False
    if  getattr(user, 'is_superuser', False):
        allowed = True

        role = getattr(user, 'role', None)
        manager_status = getattr(user, 'manager_admin_status', None)
        if role and str(role).lower() == 'admin':
            allowed = True
        if manager_status and str(manager_status).lower() == 'admin':
            allowed = True

    else:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    files = request.FILES.getlist('files')
    if not files:
        return JsonResponse({'error': 'No files provided'}, status=400)

    # Destination directory: prefer explicit ADMIN_UPLOAD_DIR, fallback to MEDIA_ROOT/admin_uploads
    admin_dir = getattr(settings, 'ADMIN_UPLOAD_DIR', None)
    if not admin_dir:
        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if media_root:
            # Use MEDIA_ROOT directly (do not create an extra sub-folder)
            admin_dir = media_root
        else:
            base_dir = getattr(settings, 'BASE_DIR', os.getcwd())
            admin_dir = os.path.join(base_dir, 'admin_uploads')

    admin_dir = os.path.abspath(admin_dir)
    os.makedirs(admin_dir, exist_ok=True)

    max_bytes = getattr(settings, 'ADMIN_UPLOAD_MAX_BYTES', None)

    saved = []
    try:
        for f in files:
            # Extension check
            if not _is_allowed_extension(f.name):
                return JsonResponse({'error': 'Invalid file type', 'details': f"{f.name} not allowed"}, status=400)

            # Size check
            if max_bytes is not None and f.size > max_bytes:
                return JsonResponse({'error': 'File too large', 'details': f"{f.name} exceeds {max_bytes} bytes"}, status=400)

            # Preserve original filename; handle collisions by appending suffix
            safe_name = _ensure_unique_filename(admin_dir, f.name)
            dest_path = os.path.join(admin_dir, safe_name)

            with open(dest_path, 'wb+') as out:
                for chunk in f.chunks():
                    out.write(chunk)

            saved.append({'original_name': f.name, 'saved_name': safe_name, 'size': f.size, 'path': dest_path})

        return JsonResponse({'uploaded': saved, 'message': 'Files uploaded'}, status=201)
    except Exception as e:
        logger.exception('Error while saving admin upload files')
        return JsonResponse({'error': 'Internal server error', 'details': str(e)}, status=500)
