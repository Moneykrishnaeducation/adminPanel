from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.template.response import TemplateResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.core.serializers import serialize
from ..decorators import role_required
from ..roles import UserRole
import os
import json
from rest_framework.permissions import IsAuthenticated

@role_required([UserRole.ADMIN.value, UserRole.MANAGER.value])
@never_cache
@csrf_exempt
def trading_accounts_page(request):
    """
    Serve the Trading Accounts admin page with proper authentication
    """
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            # Assuming you have a TradingAccount model
            trading_accounts = TradingAccount.objects.all()
            data = json.loads(serialize('json', trading_accounts))
            return JsonResponse(data, safe=False)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    # Regular page load
    # Read the HTML file content
    html_file_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'static', 'admin', 'admin', 'Components', 'Trading_account.html'
    )
    
    try:
        with open(html_file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Inject authentication token and fix API URLs
        auth_script = """
        <script>
            // Set authentication token from Django session
            localStorage.setItem('auth_token', '""" + request.session.get("auth_token", "") + """');
            
            // Fix API base URL to current domain
            window.API_BASE_URL = window.location.origin;
            
            // Override fetch to use correct base URL
            const originalFetch = window.fetch;
            window.fetch = function(url, options = {}) {
                if (url.startsWith('/')) {
                    url = window.API_BASE_URL + url;
                }
                return originalFetch(url, options);
            };
            
            console.log('Trading Accounts page loaded with authentication');
        </script>
        """
        
        # Insert the script before closing </body> tag
        html_content = html_content.replace('</body>', auth_script + '</body>')
        
        return HttpResponse(html_content, content_type='text/html')
        
    except FileNotFoundError:
        return HttpResponse("Trading Accounts page not found", status=404)
    except Exception as e:
        return HttpResponse(f"Error loading Trading Accounts page: {str(e)}", status=500)

