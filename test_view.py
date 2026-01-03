from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

@csrf_exempt
@require_http_methods(["GET"])
def test_api_endpoint(request):
    """Simple test API endpoint to verify routing works"""
    print("🧪 TEST API ENDPOINT CALLED!")
    return JsonResponse({
        "status": "success",
        "message": "Test API endpoint is working",
        "user": str(request.user),
        "path": request.path,
        "method": request.method
    })
