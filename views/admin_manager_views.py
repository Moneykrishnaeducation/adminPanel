import logging
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Q
from adminPanel.models import CustomUser, TradeGroup, TradingAccount
from adminPanel.serializers import UserSerializer, TradingAccountSerializer
from adminPanel.permissions import IsAdmin, IsManager, IsAdminOrManager, IsSuperuser

logger = logging.getLogger(__name__)

# API endpoint to list only MAM managers
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_mam_managers(request):
    """
    List all users with MAM manager status with pagination and search support.
    Query parameters:
    - page: Page number (default: 1)
    - page_size: Number of results per page (default: 10)
    - search: Search query to filter by account_id, account_name, or username
    """
    try:
        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        search_query = request.GET.get('search', '').strip()
        
        # Start with base queryset
        mam_accounts = TradingAccount.objects.filter(account_type__in=["mam", "mam_investment"])
        
        # Apply search filter if provided
        if search_query:
            mam_accounts = mam_accounts.filter(
                Q(account_id__icontains=search_query) |
                Q(account_name__icontains=search_query) |
                Q(user__username__icontains=search_query) |
                Q(user__email__icontains=search_query)
            )
        
        # Get total count before pagination
        total_count = mam_accounts.count()
        
        # Apply pagination
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        paginated_accounts = mam_accounts[start_index:end_index]
        
        serializer = TradingAccountSerializer(paginated_accounts, many=True)
        
        return Response({
            "count": total_count,
            "next": None,
            "previous": None,
            "results": serializer.data,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size
        })
    except Exception as e:
        logger.error(f"Error listing MAM managers: {str(e)}")
        return Response({
            "error": str(e),
            "results": []
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from adminPanel.models import TradeGroup, CustomUser
from adminPanel.serializers import UserSerializer
from adminPanel.permissions import IsAdmin, IsManager, IsAdminOrManager
from adminPanel.roles import UserRole
import logging
import json

logger = logging.getLogger(__name__)

# Import MT5 services at the top to avoid repeated imports
try:
    from adminPanel.mt5.services import get_manager_instance
except ImportError:
    logger.warning("MT5 services not available")
    get_manager_instance = None

@api_view(['GET', 'HEAD'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def list_admin_managers(request):
    """List all admin and manager users"""
    try:
        # Get users with admin or manager roles or with is_staff=True
        logger.info("Fetching admin/manager users")
        admin_users_qs = CustomUser.objects.filter(
            Q(manager_admin_status__iexact='admin') |
            Q(manager_admin_status__iexact='manager') |
            Q(role__iexact='admin') |
            Q(role__iexact='manager') |
            Q(is_staff=True)
        )
        
        logger.info(f"Found {admin_users_qs.count()} admin/manager users")
        
        if request.method == 'HEAD':
            # Just verify authentication for HEAD requests
            return Response(status=status.HTTP_200_OK)
            
        admin_users = []
        for user in admin_users_qs:
            try:
                # Default to 'admin' role for staff users if manager_admin_status is not set
                role = user.manager_admin_status or ('admin' if user.is_staff else 'user')
                
                # Check if attributes exist before accessing them
                user_data = {
                    'id': user.user_id,
                    'username': user.username,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'role': role.capitalize() if role else role,
                    'elevated_date': user.date_joined.strftime('%Y-%m-%d %H:%M:%S') if user.date_joined else None,
                    'phone_number': getattr(user, 'phone_number', None),  # Only use phone_number, not phone
                    'address': getattr(user, 'address', None)  # Use getattr with default value
                }
                admin_users.append(user_data)
                # logger.info(f"Successfully processed user {user.user_id}")
            except Exception as user_error:
                logger.error(f"Error processing user {user.user_id}: {str(user_error)}")
                # Continue with the next user instead of failing the entire request
                continue
        
        # logger.info(f"Returning {len(admin_users)} admin/manager users")
        return Response({'success': True, 'admins': admin_users})
    except Exception as e:
        logger.error(f"Error fetching admin/manager users: {str(e)}", exc_info=True)
        return Response(
            {'success': False, 'message': f'Error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdmin])
def get_admin_manager_details(request, user_id):
    """Get detailed information about an admin or manager user"""
    try:
        admin_user = CustomUser.objects.filter(
            id=user_id,
            manager_admin_status__in=['admin', 'manager']
        ).first()
        
        if not admin_user:
            return Response(
                {'success': False, 'message': 'Admin/manager not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serialized_data = UserSerializer(admin_user).data
        
        return Response({'success': True, 'admin': serialized_data})
    except Exception as e:
        logger.error(f"Error fetching admin/manager details: {str(e)}")
        return Response(
            {'success': False, 'message': f'Error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdmin])
def create_admin_manager(request):
    """Create a new admin or manager user"""
    try:
        data = request.data
        
        # Basic validation
        required_fields = ['email', 'first_name', 'last_name', 'role']
        for field in required_fields:
            if field not in data:
                return Response(
                    {'success': False, 'message': f'Missing required field: {field}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Check if user with this email already exists
        if CustomUser.objects.filter(email=data['email']).exists():
            return Response(
                {'success': False, 'message': 'User with this email already exists'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate username from email
        username = data['email'].split('@')[0]
        # Ensure username is unique
        base_username = username
        counter = 1
        while CustomUser.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        # Create user with random password
        from adminPanel.urls import generate_password
        temp_password = generate_password(12)
        
        # Hash password with salt+hash format (same as signup/reset password in client)
        from clientPanel.views.auth_views import hash_password
        hashed_password = hash_password(temp_password)
        
        # Create user with admin or manager role
        user = CustomUser.objects.create(
            username=username,
            email=data['email'],
            password=hashed_password,  # Use hashed password
            first_name=data['first_name'],
            last_name=data['last_name'],
            is_staff=True if data['role'] == 'admin' else False,
            is_active=True,
            manager_admin_status=data.get('manager_admin_status', data['role']),
            role=data['role'].lower(),
            phone_number=data.get('phone_number', ''),
            address=data.get('address', '')
        )
        
        return Response({
            'success': True,
            'message': 'Admin/manager created successfully',
            'user_id': user.id,
            'temp_password': temp_password
        })
    except Exception as e:
        logger.error(f"Error creating admin/manager: {str(e)}")
        return Response(
            {'success': False, 'message': f'Error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['PUT'])
@permission_classes([IsAuthenticated, IsAdmin])
def update_admin_manager(request, user_id):
    """Update an existing admin or manager"""
    try:
        data = request.data
        
        user = CustomUser.objects.filter(
            id=user_id,
            manager_admin_status__in=['admin', 'manager']
        ).first()
        
        if not user:
            return Response(
                {'success': False, 'message': 'Admin/manager not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Update user fields
        if 'first_name' in data:
            user.first_name = data['first_name']
        if 'last_name' in data:
            user.last_name = data['last_name']
        if 'email' in data:
            # Check if email is being changed and if it's already in use
            if user.email != data['email'] and CustomUser.objects.filter(email=data['email']).exists():
                return Response(
                    {'success': False, 'message': 'Email already in use'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            user.email = data['email']
        
        # Update role
        if 'role' in data:
            user.manager_admin_status = data['role']
            user.is_staff = True if data.get('role') == 'admin' else False
        
        # Update contact info
        if 'phone_number' in data:
            user.phone = data['phone_number']
        if 'address' in data:
            user.address = data['address']
        
        user.save()
        
        return Response({'success': True, 'message': 'Admin/manager updated successfully'})
    except Exception as e:
        logger.error(f"Error updating admin/manager: {str(e)}")
        return Response(
            {'success': False, 'message': f'Error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminOrManager])
def get_available_groups(request):
    """Get list of all trading groups including MT5 groups"""
    try:
        logger.info("Fetching trading groups from database and MT5")
        
        # Get database groups
        db_groups = TradeGroup.objects.all()
        logger.info(f"Found {db_groups.count()} trading groups in database")
        
        group_data = []
        
        # Process database groups
        for group in db_groups:
            try:
                group_data.append({
                    'id': group.name,  # Use name as ID for consistency with frontend
                    'name': group.name,
                    'description': group.description,
                    'alias': group.alias,  # Include the alias field
                    'type': group.type,  # 'real' or 'demo'
                    'is_active': group.is_active,
                    'enabled': group.is_active,
                    'is_default': group.is_default,
                    'is_demo_default': group.is_demo_default,
                    'source': 'database',
                    'group_type': 'Database'
                })
            except Exception as group_error:
                logger.error(f"Error processing database group {group.id}: {str(group_error)}")
                continue
        
        # Get real MT5 groups if requested
        include_mt5 = request.query_params.get('include_mt5', 'true').lower() == 'true'
        
        if include_mt5:
            try:
                # Get MT5 manager instance
                mt5_manager_instance = get_manager_instance() if get_manager_instance else None
                if mt5_manager_instance and hasattr(mt5_manager_instance, 'manager') and mt5_manager_instance.manager:
                    logger.info("MT5 manager instance obtained, fetching groups...")
                    
                    # Get total number of groups
                    total_groups = mt5_manager_instance.manager.GroupTotal()
                    logger.info(f"MT5 reports {total_groups} total groups")
                    
                    mt5_groups = []
                    if total_groups > 0:
                        logger.debug(f"Starting to iterate through {total_groups} groups...")
                        for i in range(total_groups):  # Get all groups
                            try:
                                group = mt5_manager_instance.manager.GroupNext(i)  # Use GroupNext to get group by index
                                
                                if group is not None:
                                    # Try to get the group name from common attributes
                                    group_name = None
                                    
                                    # Common attributes that might contain the group name
                                    name_attrs = ['Group', 'Name', 'GroupName', 'group', 'name']
                                    
                                    for attr in name_attrs:
                                        try:
                                            if hasattr(group, attr):
                                                value = getattr(group, attr)
                                                if isinstance(value, str) and value:
                                                    group_name = value
                                                    break
                                        except Exception:
                                            continue
                                    
                                    # If we found a group name, add it
                                    if group_name:
                                        mt5_groups.append(group_name)
                                        logger.debug(f"Retrieved MT5 group: {group_name}")
                                        
                            except Exception as e:
                                logger.error(f"Error getting group at index {i}: {str(e)}")
                                continue
                    else:
                        logger.warning("Total groups is 0 or negative")
                    
                    # Add real MT5 groups to the response
                    # For groups that exist in both database and MT5, prefer the database version
                    # but add additional MT5-specific information
                    existing_names = {g['name'] for g in group_data}
                    
                    for i, group_name in enumerate(mt5_groups):
                        if group_name not in existing_names:
                            # This is a pure MT5 group not in database
                            group_data.append({
                                'id': group_name,  # Use actual group name as ID instead of virtual mt5_X
                                'name': group_name,
                                'description': f'MT5 Group: {group_name}',
                                'type': 'demo' if 'demo' in group_name.lower() else 'real',
                                'is_active': True,
                                'enabled': True,
                                'is_default': False,  # MT5-only groups can't be default
                                'is_demo_default': False,  # MT5-only groups can't be demo default
                                'source': 'mt5',
                                'group_type': 'MT5'
                            })
                        else:
                            # Mark existing database groups as MT5-synced
                            for existing_group in group_data:
                                if existing_group['name'] == group_name:
                                    existing_group['group_type'] = 'MT5-Synced'
                                    existing_group['source'] = 'database_mt5_synced'
                                    break
                    
                    pure_mt5_count = len([g for g in group_data if g['source'] == 'mt5'])
                    synced_count = len([g for g in group_data if g.get('group_type') == 'MT5-Synced'])
                    logger.info(f"Added {pure_mt5_count} pure MT5 groups, marked {synced_count} as MT5-synced")
                else:
                    logger.warning("MT5 manager instance not available or doesn't have manager attribute")
            except Exception as mt5_error:
                logger.error(f"Error fetching MT5 groups: {str(mt5_error)}")
                # Continue without MT5 groups if there's an error
        
        logger.info(f"Returning {len(group_data)} total trading groups")
        return Response({'success': True, 'groups': group_data})
    except Exception as e:
        logger.error(f"Error fetching trading groups: {str(e)}", exc_info=True)
        return Response(
            {'success': False, 'message': f'Error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdmin])
def update_trading_group(request):
    """Update a trading group's status, alias, or type"""
    try:
        data = request.data
        logger.info(f"Trading group update request for group: {data.get('group_id')}")
        
        if 'group_id' not in data:
            return Response(
                {'success': False, 'message': 'Missing group_id parameter'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        group_id = data['group_id']
        
        # Handle MT5 groups (which have string IDs starting with 'mt5_')
        if isinstance(group_id, str) and group_id.startswith('mt5_'):
            logger.info(f"Processing MT5 group: {group_id}")
            
            # Extract the index from the MT5 group ID (e.g., 'mt5_1' -> 1)
            try:
                mt5_index = int(group_id.replace('mt5_', ''))
                
                # Get the actual MT5 group name by fetching it again
                mt5_manager_instance = get_manager_instance() if get_manager_instance else None
                if mt5_manager_instance and hasattr(mt5_manager_instance, 'manager') and mt5_manager_instance.manager:
                    total_groups = mt5_manager_instance.manager.GroupTotal()
                    
                    if mt5_index < total_groups:
                        group_info = mt5_manager_instance.manager.GroupNext(mt5_index)
                        if group_info:
                            # group_info is likely a struct, try to access the Group field directly
                            mt5_group_name = group_info.Group if hasattr(group_info, 'Group') else f'MT5_Group_{mt5_index}'
                        else:
                            mt5_group_name = f'MT5_Group_{mt5_index}'
                    else:
                        logger.error(f"MT5 index {mt5_index} out of range (total: {total_groups})")
                        mt5_group_name = f'MT5_Group_{mt5_index}'
                else:
                    logger.warning("Could not connect to MT5 manager, using fallback name")
                    mt5_group_name = f'MT5_Group_{mt5_index}'
                    
            except (ValueError, Exception) as e:
                logger.error(f"Error processing MT5 group ID {group_id}: {e}")
                mt5_group_name = f'MT5_Group_{group_id}'
            
            logger.info(f"MT5 group name resolved to: {mt5_group_name}")
            
            # Find or create a TradeGroup for this MT5 group
            group, created = TradeGroup.objects.get_or_create(
                name=mt5_group_name,
                defaults={
                    'description': f'MT5 Group: {mt5_group_name}',
                    'type': 'real',
                    'is_active': False
                }
            )
            
            if created:
                logger.info(f"Created new TradeGroup for MT5 group: {mt5_group_name}")
        else:
            # Handle actual MT5 group names (like demo\KRSNA, real\KRSNA-1, etc.)
            group = TradeGroup.objects.filter(name=group_id).first()
            if not group:
                # Create a new TradeGroup for this MT5 group if it doesn't exist
                logger.info(f"Creating new TradeGroup for MT5 group: {group_id}")
                group = TradeGroup.objects.create(
                    name=group_id,
                    description=f'MT5 Group: {group_id}',
                    type='demo' if 'demo' in group_id.lower() else 'real',
                    is_active=False
                )
        
        # Update status if provided (handle both 'enabled' and 'is_active')
        if 'enabled' in data:
            group.is_active = bool(data['enabled'])
        elif 'is_active' in data:
            group.is_active = bool(data['is_active'])
        
        # Update alias if provided
        if 'alias' in data:
            group.alias = data['alias']
        
        # Update role/type if provided
        if 'role' in data:
            role = data['role']
            if role in ['default', 'demo']:
                # Map role to type
                group.type = 'demo' if role == 'demo' else 'real'
        
        # Handle default/demo flags - ensure only one can be set
        if 'default' in data:
            if data['default']:
                group.is_default = True
                group.type = 'real'
                # Ensure only one group is default
                TradeGroup.objects.filter(is_default=True).exclude(pk=group.pk).update(is_default=False)
                logger.info(f"Group {group.name} set as default")
            else:
                group.is_default = False
        
        if 'demo' in data:
            if data['demo']:
                group.is_demo_default = True
                group.type = 'demo'
                # Ensure only one group is demo default
                TradeGroup.objects.filter(is_demo_default=True).exclude(pk=group.pk).update(is_demo_default=False)
                logger.info(f"Group {group.name} set as demo default")
            else:
                group.is_demo_default = False
        
        # Update type if provided directly
        if 'type' in data and data['type'] in ['real', 'demo']:
            group.type = data['type']
        
        group.save()
        logger.info(f"Successfully updated group: {group.name}")
        
        return Response({
            'success': True,
            'message': 'Trading group updated successfully'
        })
    except Exception as e:
        logger.error(f"Error updating trading group: {str(e)}", exc_info=True)
        return Response(
            {'success': False, 'message': f'Error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSuperuser])
def save_group_configuration(request):
    """Save group configuration with default, demo, and visibility settings"""
    try:
        data = request.data
        logger.info(f"Received group configuration save request: {data}")
        
        if 'groups' not in data:
            return Response(
                {'success': False, 'message': 'Missing groups data'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        groups_config = data['groups']
        
        # Validate that we have exactly one default group
        default_groups = [g for g in groups_config if g.get('default', False)]
        demo_groups = [g for g in groups_config if g.get('demo', False)]
        
        if len(default_groups) != 1:
            return Response(
                {'success': False, 'message': 'Exactly one default group must be selected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Demo default is optional — it is managed separately from the Demo Trading Group page.
        # No longer require exactly one demo group here.
        
        # First reset real groups only — do NOT touch demo groups (managed from Demo Trading Group page)
        TradeGroup.objects.exclude(type='demo').update(is_default=False, is_active=False)
        logger.info("🔄 Reset non-demo groups: is_default=False, is_active=False (demo groups left intact)")
        
        # Process each group configuration
        updated_count = 0
        for group_config in groups_config:
            group_id = group_config.get('id')
            logger.info(f"🔍 Processing group config: {group_config}")
            
            # Skip MT5 groups (they can't be modified)
            if isinstance(group_id, str) and group_id.startswith('mt5_'):
                logger.info(f"Skipping MT5 group: {group_id}")
                continue
            
            # Find the group in database using either name or group_id
            group = TradeGroup.objects.filter(name=group_id).first() or TradeGroup.objects.filter(group_id=group_id).first()
            
            if not group:
                # Create the group if it doesn't exist (this handles MT5 groups that aren't in DB)
                logger.info(f"Group not found in database, creating new group: {group_id}")
                group = TradeGroup.objects.create(
                    name=group_id,
                    group_id=group_id,  # Ensure group_id is also set
                    description=f'Trading Group: {group_id}',
                    type='demo' if 'demo' in group_id.lower() else 'real',
                    is_active=False,  # Will be set below based on config
                    is_default=False,
                    is_demo_default=False
                )
            
            # Ensure both name and group_id are synchronized
            if group.name != group_id:
                group.name = group_id
            if group.group_id != group_id:
                group.group_id = group_id
                
            logger.info(f"Processing group {group_id} - Current state: default={group.is_default}, demo_default={group.is_demo_default}, type={group.type}")
            # Log current state
            logger.info(f"Before update - Group {group_id} current state: alias='{group.alias}', active={group.is_active}, type={group.type}")
            
            # Update group settings
            group.is_active = group_config.get('enabled', False)
            
            # Handle alias update explicitly
            alias_value = group_config.get('alias', '')
            logger.info(f"Attempting to set alias for group {group_id} - Current: '{group.alias}', New: '{alias_value}'")
            
            # Update alias and ensure it's saved
            logger.info(f"Setting alias for {group_id} - Old: '{group.alias}', New: '{alias_value}'")
            group.alias = alias_value
            group.save()  # Save immediately after alias update
            group.refresh_from_db()  # Verify the save
            logger.info(f"Alias update verified - New value: '{group.alias}'")
            
            # Log the group object state before save of other fields
            logger.info(f"Before save - Group {group_id} pending state: alias='{group.alias}', active={group.is_active}, type={group.type}")
            # Update default/demo status and set type accordingly
            if group_config.get('default', False):
                logger.info(f"Setting {group_id} as default real group")
                group.is_default = True
                group.is_demo_default = False
                group.type = 'real'  # Default groups are always real
                logger.info(f"✅ Set {group_id} as DEFAULT REAL: type={group.type}, is_default={group.is_default}")
            elif group_config.get('demo', False):
                logger.info(f"Setting {group_id} as default demo group")
                group.is_demo_default = True
                group.is_default = False
                group.type = 'demo'  # Demo default groups are always demo
                logger.info(f"✅ Set {group_id} as DEMO DEFAULT: type={group.type}, is_demo_default={group.is_demo_default}")
            else:
                # For enabled but non-default groups on the real page, always mark as real
                group.is_default = False
                group.is_demo_default = False
                group.type = 'real'  # Real page always processes real server groups
                logger.info(f"✅ Set {group_id} as REGULAR REAL: type={group.type}, enabled={group.is_active}")
            
            group.save()
            
            # Verify the save worked
            group.refresh_from_db()
            logger.info(f"🔍 VERIFICATION - Group {group_id} saved with: type={group.type}, is_default={group.is_default}, is_demo_default={group.is_demo_default}, is_active={group.is_active}")
            logger.info(f"Updated group {group_id} - New state: default={group.is_default}, demo_default={group.is_demo_default}, type={group.type}, alias={group.alias}")
            updated_count += 1
        
        logger.info(f"Successfully updated {updated_count} group configurations")
        
        # Verify final configuration state
        default_group = TradeGroup.objects.filter(is_default=True).first()
        demo_group = TradeGroup.objects.filter(is_demo_default=True).first()
        all_real_groups = TradeGroup.objects.filter(type='real', is_active=True).count()
        all_demo_groups = TradeGroup.objects.filter(type='demo', is_active=True).count()
        
        logger.info(f"Final configuration state - Default Real: {default_group.name if default_group else 'None'} (type: {default_group.type if default_group else 'N/A'})")
        logger.info(f"Final configuration state - Default Demo: {demo_group.name if demo_group else 'None'} (type: {demo_group.type if demo_group else 'N/A'})")
        logger.info(f"Final count - Active Real Groups: {all_real_groups}, Active Demo Groups: {all_demo_groups}")
        
        # Debug: Show all active groups and their types
        all_active = TradeGroup.objects.filter(is_active=True)
        for group in all_active:
            logger.info(f"📊 Active Group: {group.name} -> type={group.type}, default={group.is_default}, demo_default={group.is_demo_default}")
        
        # Include the final state in the response
        # Get final group states for response
        all_groups = TradeGroup.objects.all()
        groups_info = [{
            'id': g.name,
            'alias': g.alias,
            'is_default': g.is_default,
            'is_demo': g.is_demo_default,
            'type': g.type
        } for g in all_groups]

        return Response({
            'success': True,
            'message': f'Group configuration saved successfully. Updated {updated_count} groups.',
            'configuration': {
                'default_group': {
                    'id': default_group.name if default_group else None,
                    'alias': default_group.alias if default_group else None
                },
                'demo_group': {
                    'id': demo_group.name if demo_group else None,
                    'alias': demo_group.alias if demo_group else None
                },
                'updated_count': updated_count,
                'all_groups': groups_info
            }
        })
        
    except Exception as e:
        logger.error(f"Error saving group configuration: {str(e)}", exc_info=True)
        return Response(
            {'success': False, 'message': f'Error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSuperuser])
def current_group_config(request):
    """Get the current group configuration including default and demo groups"""
    try:
        from adminPanel.models import TradeGroup
        
        # Get default real group
        default_real = TradeGroup.objects.filter(is_default=True).first()
        # Get default demo group
        default_demo = TradeGroup.objects.filter(is_demo_default=True).first()
        
        # Get active real groups
        active_real_groups = TradeGroup.objects.filter(type='real', is_active=True)
        # Get active demo groups  
        active_demo_groups = TradeGroup.objects.filter(type='demo', is_active=True)
        
        real_groups_list = [{
            'id': group.name,
            'name': group.name,
            'alias': group.alias or '',
            'is_default': group.is_default
        } for group in active_real_groups]
        
        demo_groups_list = [{
            'id': group.name,
            'name': group.name,
            'alias': group.alias or '',
            'is_demo_default': group.is_demo_default
        } for group in active_demo_groups]
        
        return Response({
            'success': True,
            'configuration': {
                'default_group': {
                    'id': default_real.name if default_real else None,
                    'name': default_real.name if default_real else None,
                    'alias': default_real.alias if default_real else None
                } if default_real else None,
                'demo_group': {
                    'id': default_demo.name if default_demo else None,
                    'name': default_demo.name if default_demo else None,
                    'alias': default_demo.alias if default_demo else None
                } if default_demo else None,
                'real_groups': real_groups_list,
                'demo_groups': demo_groups_list,
                'last_updated': timezone.now().isoformat()
            }
        })
    except Exception as e:
        logger.error(f"Error getting current group configuration: {str(e)}", exc_info=True)
        return Response(
            {'success': False, 'message': f'Error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([AllowAny])  # NO AUTH for testing
def debug_groups_status(request):
    """Debug endpoint to check current group status"""
    try:
        from adminPanel.models import TradeGroup
        
        # Get all groups from database
        groups = TradeGroup.objects.all()
        
        group_info = []
        for group in groups:
            group_info.append({
                'name': group.name,
                'group_id': group.group_id,
                'is_default': group.is_default,
                'is_demo_default': group.is_demo_default,
                'is_active': group.is_active,
                'type': group.type,
                'alias': group.alias or ''
            })
        
        # Also get specific counts
        real_count = TradeGroup.objects.filter(type='real', is_active=True).count()
        demo_count = TradeGroup.objects.filter(type='demo', is_active=True).count()
        default_real = TradeGroup.objects.filter(is_default=True).first()
        default_demo = TradeGroup.objects.filter(is_demo_default=True).first()
        
        return Response({
            'success': True,
            'total_groups': groups.count(),
            'active_real_groups': real_count,
            'active_demo_groups': demo_count,
            'default_real_group': default_real.name if default_real else None,
            'default_demo_group': default_demo.name if default_demo else None,
            'groups': group_info
        })
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}", exc_info=True)
        return Response(
            {'success': False, 'message': f'Error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([AllowAny])  # NO AUTH for testing
def test_available_groups(request):
    """TEMPORARY: Test endpoint to check group deduplication without auth"""
    try:
        logger.info("TEST: Fetching trading groups from database and MT5")
        
        # Get database groups
        db_groups = TradeGroup.objects.all()
        logger.info(f"Found {db_groups.count()} trading groups in database")
        
        group_data = []
        
        # Process database groups
        for group in db_groups:
            try:
                group_data.append({
                    'id': group.id,
                    'name': group.name,
                    'description': group.description,
                    'type': group.type,  # 'real' or 'demo'
                    'is_active': group.is_active,
                    'enabled': group.is_active,
                    'source': 'database',
                    'group_type': 'Database'
                })
            except Exception as group_error:
                logger.error(f"Error processing database group {group.id}: {str(group_error)}")
                continue
        
        # Get real MT5 groups
        include_mt5 = request.query_params.get('include_mt5', 'true').lower() == 'true'
        
        if include_mt5:
            try:
                # Get MT5 manager instance
                mt5_manager_instance = get_manager_instance() if get_manager_instance else None
                if mt5_manager_instance and hasattr(mt5_manager_instance, 'manager') and mt5_manager_instance.manager:
                    logger.info("MT5 manager instance obtained, fetching groups...")
                    
                    # Get total number of groups
                    total_groups = mt5_manager_instance.manager.GroupTotal()
                    logger.info(f"MT5 reports {total_groups} total groups")
                    
                    mt5_groups = []
                    if total_groups > 0:
                        logger.debug(f"Starting to iterate through {total_groups} groups...")
                        for i in range(total_groups):  # Get all groups
                            try:
                                group = mt5_manager_instance.manager.GroupNext(i)  # Use GroupNext to get group by index
                                
                                if group is not None:
                                    # Try to get the group name from common attributes
                                    group_name = None
                                    
                                    # Common attributes that might contain the group name
                                    name_attrs = ['Group', 'Name', 'GroupName', 'group', 'name']
                                    
                                    for attr in name_attrs:
                                        try:
                                            if hasattr(group, attr):
                                                value = getattr(group, attr)
                                                if isinstance(value, str) and value:
                                                    group_name = value
                                                    break
                                        except Exception:
                                            continue
                                    
                                    # If we found a group name, add it
                                    if group_name:
                                        mt5_groups.append(group_name)
                                        logger.debug(f"Retrieved MT5 group: {group_name}")
                                        
                            except Exception as e:
                                logger.error(f"Error getting group at index {i}: {str(e)}")
                                continue
                    else:
                        logger.warning("Total groups is 0 or negative")
                    
                    # Add real MT5 groups to the response
                    # For groups that exist in both database and MT5, prefer the database version
                    # but add additional MT5-specific information
                    existing_names = {g['name'] for g in group_data}
                    
                    for i, group_name in enumerate(mt5_groups):
                        if group_name not in existing_names:
                            # This is a pure MT5 group not in database
                            group_data.append({
                                'id': f'mt5_{i}',  # Virtual ID for MT5 groups
                                'name': group_name,
                                'description': f'MT5 Group: {group_name}',
                                'type': 'real' if 'real' in group_name.lower() else 'demo',
                                'is_active': True,
                                'enabled': True,
                                'source': 'mt5',
                                'group_type': 'MT5'
                            })
                        else:
                            # Update existing database group to show it's also an MT5 group
                            for db_group in group_data:
                                if db_group['name'] == group_name:
                                    db_group['group_type'] = 'MT5-Synced'
                                    db_group['mt5_index'] = i
                                    break
                    
                    pure_mt5_count = len([g for g in group_data if g['source'] == 'mt5'])
                    synced_count = len([g for g in group_data if g.get('group_type') == 'MT5-Synced'])
                    logger.info(f"Added {pure_mt5_count} pure MT5 groups, marked {synced_count} as MT5-synced")
                else:
                    logger.warning("MT5 manager instance not available or doesn't have manager attribute")
            except Exception as mt5_error:
                logger.error(f"Error fetching MT5 groups: {str(mt5_error)}")
                # Continue without MT5 groups if there's an error
        
        logger.info(f"Returning {len(group_data)} total trading groups")
        return Response({'success': True, 'groups': group_data, 'test': True})
    except Exception as e:
        logger.error(f"Error fetching trading groups: {str(e)}", exc_info=True)
        return Response(
            {'success': False, 'message': f'Error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
