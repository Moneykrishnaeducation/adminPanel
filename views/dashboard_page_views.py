from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken
from django.views.decorators.cache import never_cache
from adminPanel.decorators import role_required
from adminPanel.roles import UserRole
import os
from django.conf import settings
import json
from rest_framework.permissions import IsAuthenticated


@never_cache
@csrf_exempt  
def manager_dashboard_page(request):
    """
    Serve the Manager Dashboard HTML page with client-side authentication
    """
    try:
        # Path to the actual manager dashboard HTML file (use BASE_DIR)
        dashboard_path = os.path.join(settings.BASE_DIR, 'static', 'admin', 'manager', 'main.html')
        
        # Check if file exists
        if not os.path.exists(dashboard_path):
            return HttpResponse(
                f"Manager dashboard file not found at: {dashboard_path}",
                status=404
            )
        
        # Read the HTML file
        with open(dashboard_path, 'r', encoding='utf-8') as file:
            html_content = file.read()
        
        # Inject authentication script to ensure user is authenticated before accessing
        auth_script = """
        <script>
            // Prevent redirect loops
            window.addEventListener('beforeunload', function() {
                sessionStorage.setItem('dashboardLoaded', 'true');
            });
            
            // Check if we just came from a redirect to prevent loops
            if (sessionStorage.getItem('dashboardLoaded') === 'true') {
                console.log('Dashboard already loaded, preventing redirect loop');
                sessionStorage.removeItem('dashboardLoaded');
            }
            
            // Check authentication on page load
            document.addEventListener('DOMContentLoaded', function() {
                console.log('Manager dashboard loaded successfully');
                checkManagerAuthentication();
            });

            async function checkManagerAuthentication() {
                const token = localStorage.getItem('jwt_token');
                
                try {
                    // Test the manager dashboard API endpoint with the token (if available)
                    const headers = {
                        'Accept': 'application/json'
                    };
                    
                    if (token) {
                        headers['Authorization'] = `Bearer ${token}`;
                    }
                    
                    const response = await fetch('/api/manager/dashboard/', {
                        headers: headers,
                        credentials: 'include'  // Include session cookies
                    });
                    
                    if (response.ok) {
                        const data = await response.json();
                        console.log('Manager authentication successful:', data);
                        
                        // Set user data for the dashboard
                        if (typeof window.setUserData === 'function') {
                            window.setUserData({
                                user: data.user || 'Manager',
                                role: 'manager',
                                token: token
                            });
                        }
                    } else if (response.status === 401) {
                        console.warn('Authentication failed. User may need to login again.');
                    } else {
                        console.warn(`Authentication API returned ${response.status}, but dashboard will still load`);
                    }
                    
                } catch (error) {
                    console.error('Authentication check failed, but dashboard will still load:', error);
                    // Don't redirect on error, just log it
                }
            }
            
            // Override fetch to automatically include auth token and credentials
            const originalFetch = window.fetch;
            window.fetch = function(url, options = {}) {
                const token = localStorage.getItem('jwt_token');
                
                // Always include credentials (session cookies)
                options.credentials = options.credentials || 'include';
                
                if (token) {
                    options.headers = {
                        ...options.headers,
                        'Authorization': `Bearer ${token}`
                    };
                }
                return originalFetch(url, options);
            };
        </script>
        """
        
        # Insert the script before closing </body> tag
        html_content = html_content.replace('</body>', auth_script + '</body>')
        
        return HttpResponse(html_content, content_type='text/html')
        
    except Exception as e:
        return HttpResponse(f"Error loading manager dashboard: {str(e)}", status=500)


@never_cache
@csrf_exempt  
def admin_dashboard_page(request):
    """
    Serve the Admin Dashboard HTML page with client-side authentication
    """
    try:
        # Path to the actual admin dashboard HTML file (use BASE_DIR)
        dashboard_path = os.path.join(settings.BASE_DIR, 'static', 'admin', 'admin', 'main.html')
        
        # Check if file exists
        if not os.path.exists(dashboard_path):
            return HttpResponse(
                f"Admin dashboard file not found at: {dashboard_path}",
                status=404
            )
        
        # Read the HTML file
        with open(dashboard_path, 'r', encoding='utf-8') as file:
            html_content = file.read()
        
        # Inject authentication script to ensure user is authenticated before accessing
        auth_script = """
        <script>
            // Check authentication on page load
            document.addEventListener('DOMContentLoaded', function() {
                checkAdminAuthentication();
            });

            async function checkAdminAuthentication() {
                const token = localStorage.getItem('jwt_token');
                
                try {
                    // Test the admin dashboard API endpoint with the token (if available)
                    const headers = {
                        'Accept': 'application/json'
                    };
                    
                    if (token) {
                        headers['Authorization'] = `Bearer ${token}`;
                    }
                    
                    const response = await fetch('/api/admin/dashboard/', {
                        headers: headers,
                        credentials: 'include'  // Include session cookies
                    });
                    
                    if (response.ok) {
                        const data = await response.json();
                        console.log('Admin authentication successful:', data);
                        
                        // Set user data for the dashboard
                        if (typeof window.setUserData === 'function') {
                            window.setUserData({
                                user: data.user || 'Administrator',
                                role: 'admin',
                                token: token
                            });
                        }
                    } else if (response.status === 401) {
                        console.warn('Authentication failed. User may need to login again.');
                    } else {
                        console.warn(`Authentication API returned ${response.status}, but dashboard will still load`);
                    }
                    
                } catch (error) {
                    console.error('Authentication check failed, but dashboard will still load:', error);
                    // Don't redirect on error, just log it
                }
            }
            
            // Override fetch to automatically include auth token and credentials
            const originalFetch = window.fetch;
            window.fetch = function(url, options = {}) {
                const token = localStorage.getItem('jwt_token');
                
                // Always include credentials (session cookies)
                options.credentials = options.credentials || 'include';
                
                if (token) {
                    options.headers = {
                        ...options.headers,
                        'Authorization': `Bearer ${token}`
                    };
                }
                return originalFetch(url, options);
            };
        </script>
        """
        
        # Insert the script before closing </body> tag
        html_content = html_content.replace('</body>', auth_script + '</body>')
        
        return HttpResponse(html_content, content_type='text/html')
        
    except Exception as e:
        return HttpResponse(f"Error loading admin dashboard: {str(e)}", status=500)
