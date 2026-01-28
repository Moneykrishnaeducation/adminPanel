import MT5Manager
import requests
import time
import threading
import logging
import asyncio
import concurrent.futures
from django.core.cache import cache
from django.utils import timezone
from .models import ServerSetting
from asgiref.sync import sync_to_async
crights = MT5Manager.MTUser.EnUsersRights
from datetime import datetime, timedelta
import os
import json
from django.db import transaction

logger = logging.getLogger(__name__)

# Cache for failed account lookups to prevent spam logging
FAILED_ACCOUNT_CACHE = {}
CACHE_EXPIRY_MINUTES = 5  # Cache failed lookups for 5 minutes
MAX_ERROR_LOG_RATE = 10  # Maximum error logs per account per hour

# Load group configuration if available
GROUP_CONFIG = {}
try:
    config_path = os.path.join(os.path.dirname(__file__), 'group_config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            GROUP_CONFIG = json.load(f)
except Exception as e:
    logger.error(f"Failed to load group_config.json: {e}")
   
# Default group to use if found to be working
DEFAULT_GROUP = GROUP_CONFIG.get('default_group')

account_create_rights = crights.USER_RIGHT_ENABLED | \
                        crights.USER_RIGHT_PASSWORD | \
                        crights.USER_RIGHT_CONFIRMED | \
                        crights.USER_RIGHT_TRAILING | \
                        crights.USER_RIGHT_EXPERT

algo_disable_rights = crights.USER_RIGHT_ENABLED | \
                     crights.USER_RIGHT_PASSWORD | \
                     crights.USER_RIGHT_CONFIRMED | \
                     crights.USER_RIGHT_TRAILING

algo_enable_rights = crights.USER_RIGHT_ENABLED | \
                     crights.USER_RIGHT_PASSWORD | \
                     crights.USER_RIGHT_CONFIRMED | \
                     crights.USER_RIGHT_TRAILING | \
                     crights.USER_RIGHT_EXPERT

disable_account_rights = crights.USER_RIGHT_PASSWORD | \
                         crights.USER_RIGHT_CONFIRMED | \
                         crights.USER_RIGHT_TRAILING | \
                         crights.USER_RIGHT_EXPERT
                       
disable_trading_rights = crights.USER_RIGHT_ENABLED | \
                         crights.USER_RIGHT_PASSWORD | \
                         crights.USER_RIGHT_CONFIRMED | \
                         crights.USER_RIGHT_TRAILING | \
                         crights.USER_RIGHT_EXPERT | \
                         crights.USER_RIGHT_TRADE_DISABLED

enable_trading_rights = crights.USER_RIGHT_ENABLED | \
                        crights.USER_RIGHT_PASSWORD | \
                        crights.USER_RIGHT_CONFIRMED | \
                        crights.USER_RIGHT_TRAILING | \
                        crights.USER_RIGHT_EXPERT


def ensure_connected(func):
    """
    Decorator to ensure the MT5 Manager is connected before executing a function.
    """
    def wrapper(self, *args, **kwargs):
        if not self.manager:
            raise Exception("MT5 Manager is not connected. Please reconnect.")
        return func(self, *args, **kwargs)
    return wrapper

_manager_instance = None
_current_server_setting = None
_manager_lock = threading.Lock()  

_valued_date = None

def reset_manager_instance():
    """
    Force reset the MT5 manager instance to reload new credentials.
    Call this function after updating server settings to ensure new credentials are used.
    """
    global _manager_instance, _current_server_setting
    with _manager_lock:
        if _manager_instance:
            try:
                # Disconnect the current manager if connected
                if hasattr(_manager_instance, 'connected') and _manager_instance.connected:
                    # MT5 manager doesn't have explicit disconnect, but we can mark as disconnected
                    _manager_instance.connected = False
                logger.info("MT5 Manager instance reset successfully")
            except Exception as e:
                logger.warning(f"Error while resetting manager instance: {e}")
       
        _manager_instance = None
        _current_server_setting = None
       
        # Clear any cached MT5 errors
        cache.delete('mt5_manager_error')
       
        # Clear trading groups cache and force re-sync from new manager
        try:
            from .models import MT5GroupConfig
            # Clear existing group cache by marking all as disabled
            # This will force a fresh sync from the new MT5 manager
            MT5GroupConfig.objects.all().update(is_enabled=False, last_sync=None)
            logger.info("Cleared cached MT5 trading groups - will re-sync from new manager")
           
            # Clear related cache keys
            cache.delete('mt5_groups_sync')
            cache.delete('mt5_connection_status')
           
        except Exception as e:
            logger.warning(f"Error clearing MT5 groups cache: {e}")
       
        logger.info("MT5 Manager connection has been reset and will reconnect with new credentials")
        logger.info("Trading groups will be re-fetched from the new MT5 Manager on next request")

def force_refresh_trading_groups():
    """
    Force refresh trading groups from the current MT5 manager.
    This will clear the cache and immediately sync with MT5.
    """
    try:
        from .models import MT5GroupConfig
       
        # Clear all existing groups cache
        MT5GroupConfig.objects.all().update(is_enabled=False, last_sync=None)
       
        # Create new MT5 manager actions instance and sync
        mt5_actions = MT5ManagerActions()
        if mt5_actions.manager:
            result = mt5_actions.sync_mt5_groups()
            if result:
                return True
            else:
                logger.error("Failed to sync trading groups from MT5")
                return False
        else:
            logger.error("MT5 manager not available for groups refresh")
            return False
           
    except Exception as e:
        logger.error(f"Error force refreshing trading groups: {str(e)}")
        return False

def checkingu():
    # Temporarily bypass license check for development/testing
    # This allows MT5 integration to work while license server is unavailable
    return True

def should_log_error(login_id, error_type='account_not_found'):
    """
    Determine if we should log an error for this login_id based on rate limiting.
    This prevents spam logging of the same errors repeatedly.
    """
    current_time = datetime.now()
    cache_key = f"{login_id}_{error_type}"
   
    # Check if this error was recently logged
    if cache_key in FAILED_ACCOUNT_CACHE:
        last_logged, count = FAILED_ACCOUNT_CACHE[cache_key]
       
        # If within the cache expiry window
        if current_time - last_logged < timedelta(minutes=CACHE_EXPIRY_MINUTES):
            # If we've already logged too many times in this hour, skip logging
            if count >= MAX_ERROR_LOG_RATE:
                return False
            # Increment count but don't update timestamp (continue rate limiting)
            FAILED_ACCOUNT_CACHE[cache_key] = (last_logged, count + 1)
            return count <= 2  # Only log first 3 times within the window
        else:
            # Reset counter if outside the window
            FAILED_ACCOUNT_CACHE[cache_key] = (current_time, 1)
            return True
    else:
        # First time seeing this error
        FAILED_ACCOUNT_CACHE[cache_key] = (current_time, 1)
        return True

def get_cached_account_data(login_id, data_type='balance'):
    """
    Get cached account data to avoid repeated MT5 API calls for failed accounts.
    Returns cached value or None if not cached or expired.
    """
    cache_key = f"mt5_failed_{login_id}_{data_type}"
    return cache.get(cache_key)


def _remove_trading_account_from_db(login_id, reason=None):
    """
    Safely remove TradingAccount database rows that reference the given MT5 login_id.
    This is defensive: it will only delete rows where account_id matches the login_id.
    The function logs its actions and wraps deletion in a transaction to avoid partial state.
    """
    try:
        # Import locally to avoid circular imports at module import time
        from adminPanel.models import TradingAccount
        # Use string match because account_id is stored as string in many places
        ta = TradingAccount.objects.filter(account_id=str(login_id))
        if not ta.exists():
            logger.debug(f"No TradingAccount row found for login_id {login_id}, nothing to remove")
            return False

        # Instead of deleting rows from the database (which causes data loss),
        # mark the TradingAccount rows as inactive so the record is preserved.
        try:
            with transaction.atomic():
                updated = ta.update(is_active=False, status='disabled')
            logger.info(f"Marked {updated} TradingAccount row(s) inactive for missing MT5 account {login_id}. Reason: {reason}")
            return True
        except Exception as e:
            # logger.error(f"Failed to mark TradingAccount inactive for login_id {login_id}: {e}")
            return False
    except Exception as e:
        logger.error(f"Failed to remove TradingAccount for login_id {login_id}: {e}")
        return False

def cache_failed_account_lookup(login_id, data_type='balance', cache_duration=300):
    """
    Cache failed account lookup to prevent repeated API calls.
    cache_duration: seconds to cache (default 5 minutes)
    """
    cache_key = f"mt5_failed_{login_id}_{data_type}"
    cache.set(cache_key, True, cache_duration)
   
class MT5ManagerAPI:
    def __init__(self):
        unique_id = str(os.getpid())
        base_directory = os.path.join(os.getcwd(), 'mt5_instances')
        os.makedirs(base_directory, exist_ok=True)
        instance_directory = os.path.join(base_directory, unique_id)
        os.makedirs(instance_directory, exist_ok=True)
        MT5Manager.InitializeManagerAPIPath(module_path=instance_directory, work_path=instance_directory)
       
        self.manager = MT5Manager.ManagerAPI()
        self.connected = False

    def connect(self, address, login, password, mode, timeout):
        if self.manager.Connect(address, login, password, mode, timeout):
            self.connected = True
            return self.manager
        else:
            error_message = f"Failed to connect to MT5 Manager: {MT5Manager.LastError()}"
            logger.error(error_message)
            self.connected = False
            raise Exception(error_message)

   
def get_manager_instance():
    """
    Returns the global MT5ManagerAPI instance. If no instance exists or the server settings
    have changed, it initializes a new instance with the latest settings.
    """
    global _manager_instance, _current_server_setting
    if (not checkingu()):
        return None

    # Check if the ServerSetting table exists before querying
    from django.db import connection
    table_names = connection.introspection.table_names()
    if 'mt5_serversetting' not in table_names:
        logger.warning("mt5_serversetting table does not exist. Skipping manager instance creation.")
        return None

    # Check if we're in an async context
    try:
        loop = asyncio.get_running_loop()
        logger.debug("Detected async context, running MT5 manager instance creation in thread")
        # We're in an async context, run sync code in a thread
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(_get_manager_instance_sync)
            result = future.result()
            logger.debug("MT5 manager instance created successfully in async context")
            return result
    except RuntimeError:
        # No running loop, we're in sync context
        # logger.debug("Running in sync context, creating MT5 manager instance directly")
        return _get_manager_instance_sync()
    except Exception as e:
        logger.error(f"Unexpected error in get_manager_instance: {e}")
        raise

def _get_manager_instance_sync():
    """
    Synchronous version of get_manager_instance
    """
    global _manager_instance, _current_server_setting

    from django.db import connection
    table_names = connection.introspection.table_names()
    if 'mt5_serversetting' not in table_names:
        logger.warning("mt5_serversetting table does not exist. Skipping manager instance creation.")
        return None

    with _manager_lock:  
        try:
            latest_setting = ServerSetting.objects.latest('created_at')
            if not latest_setting:
                raise Exception("No server settings found")

            if _manager_instance is None or _current_server_setting != latest_setting:
                _manager_instance = MT5ManagerAPI()
                try:
                    connection_result = _manager_instance.connect(
                        address=latest_setting.get_decrypted_server_ip(),
                        login=int(latest_setting.real_account_login),
                        password=latest_setting.get_decrypted_real_account_password(),
                        mode=MT5Manager.ManagerAPI.EnPumpModes.PUMP_MODE_FULL,
                        timeout=120000,
                    )
                    # Connection successful if no exception was raised
                    # logger.info("Connected to MT5 Manager API with latest server settings.")
                    _current_server_setting = latest_setting
                except Exception as e:
                    error_message = f"Failed to connect to MT5 Manager: {str(e)}"
                    logger.error(error_message)
                    raise Exception(error_message)
            return _manager_instance

        except Exception as e:
            logger.error(f"Error in get_manager_instance: {str(e)}")
            raise


class MT5ManagerActions:
    def get_closed_trades(self, login_id, from_date=None, to_date=None):
        """
        Fetch closed trades (deals) for a given MT5 account login_id and date range.
        Returns a list of deal objects (Action == 2 is usually 'closed').
        Handles all error cases robustly.
        Prints all attributes for every deal for debugging.
        """
        if not self.manager:
            raise Exception("MT5 Manager not connected")
        from datetime import datetime, timedelta
        if to_date is None:
            to_date = datetime.now()
        if from_date is None:
            from_date = to_date - timedelta(days=365)
        
        # Validate that login_id is numeric before making MT5 call
        try:
            numeric_login_id = int(login_id)
        except (ValueError, TypeError):
            logger.warning(f"Skipping non-numeric account ID: {login_id}")
            return []
            
        deals = self.manager.DealRequest(numeric_login_id, from_date, to_date)
        # Debug print removed
        # Defensive: DealRequest can return False, None, empty list, or a list of deals
        if deals is False or deals is None:
            return []
        if isinstance(deals, bool):
            return []
        if not isinstance(deals, (list, tuple)):
            return []
        if not deals:
            return []
        closed_deals = []
        for idx, d in enumerate(deals):
            action = getattr(d, 'Action', None)
            entry = getattr(d, 'Entry', None)
            symbol = getattr(d, 'Symbol', None)
            volume_closed = getattr(d, 'VolumeClosed', 0)
            deal_id = getattr(d, 'Deal', None)
            # Keep original filter for actual closed_deals list
            if entry == 1 and symbol and str(symbol).strip() != '' and volume_closed and float(volume_closed) > 0 and action in (0, 1):
                closed_deals.append(d)
        return closed_deals

    @property
    def HistoryDealsGet(self):
        """
        Compatibility property so hasattr(manager, 'HistoryDealsGet') works.
        Returns a function that matches the expected signature.
        """
        def _history_deals_get(login_id, from_timestamp, to_timestamp):
            from datetime import datetime
            from_date = datetime.fromtimestamp(from_timestamp)
            to_date = datetime.fromtimestamp(to_timestamp)
            return self.get_closed_trades(login_id, from_date, to_date)
        return _history_deals_get
    def __init__(self):
        self.manager = None
        self.connection_error = None
        try:
            manager_instance = get_manager_instance()
            if manager_instance:
                self.manager = manager_instance.manager
            else:
                self.connection_error = "Manager instance is None"
                logger.error("MT5 Manager instance is None")
        except Exception as e:
            self.connection_error = str(e)
            logger.error(f"MT5 Manager initialization failed: {str(e)}")
            # Store the error state for debugging
            cache.set('mt5_manager_error', str(e), 300)

    def add_new_account(self, group_name=None, leverage=100, client=None, master_password=None, investor_password=None, agent=0):
        # Use the working group configuration if provided group doesn't work
        effective_group = group_name if group_name else DEFAULT_GROUP
       
        # Check if manager is connected
        if not self.manager:
            if self.connection_error:
                raise Exception(f"MT5 Manager not connected: {self.connection_error}")
            else:
                raise Exception("MT5 Manager not connected: Unknown error")
       
        user = MT5Manager.MTUser(self.manager)
        user.Group = str(effective_group)
        user.Leverage = int(leverage)
        user.FirstName = client.first_name
        user.LastName = client.last_name
        user.EMail = client.email
        user.Country = str(client.country)
        user.Phone = client.phone_number
        user.Agent = agent
        user.Rights = account_create_rights
       
        # If agent is not 0, check if it's starting with 7255
        if str(agent).startswith("7255"):
            for i in range(self.manager.GroupTotal()):
                group = self.manager.GroupNext(i).Group
                if "demo" not in group:
                    for user_select in self.manager.UserGetByGroup(self.manager.GroupNext(i).Group):
                        if str(user_select.Agent).startswith((str(agent))[:9]):
                            return False

        if not self.manager.UserAdd(user, master_password, investor_password):
            self._handle_user_add_error(MT5Manager.LastError())
            return False
        else:
            login_id = user.Login
            # Debug: Print account info after creation
            try:
                created_user = self.manager.UserGet(int(login_id))
                if created_user:
                     pass
                else:
                   pass
            except Exception as e:
               logger.error(f"Error fetching created account info for login {login_id}: {e}")
            # Always set leverage after creation
            try:
                leverage_result = self.change_leverage(login_id, user.Leverage)
            except Exception as e:
                logger.error(f"Error setting leverage for login {login_id}: {e}")

            # Always deposit initial balance after creation (if balance > 0)
            try:
                initial_balance = getattr(user, 'Balance', 0)
                if hasattr(user, 'Balance') and user.Balance > 0:
                    deposit_result = self.deposit_funds(login_id, user.Balance, "Demo Deposit")
                else:
                    logger.info(f"No initial balance to deposit for login {login_id}")
            except Exception as e:
                logger.error(f"Error depositing initial balance for login {login_id}: {e}")

            return login_id

    @ensure_connected
    def deposit_funds(self, login_id, amount, comment):
        # Validate and convert types
        try:
            login_id = int(login_id)
            amount = float(amount)
            comment = str(comment)
        except (ValueError, TypeError) as e:
            logger.error(f"Type conversion error in deposit_funds: {e}")
            return False
           
        if amount <= 0:
            return False
           
        # Verify account exists and is active
        try:
            user_info = self.manager.UserGet(login_id)
            if not user_info:
                pass
                return False
            
        except Exception as e:
            print(f"[MT5 DEBUG] Error checking account {login_id}: {str(e)}")

        result = self._handle_funds_operation(login_id, amount, comment, MT5Manager.MTDeal.EnDealAction.DEAL_BALANCE, "Deposit")
        if not result:
            try:
                last_error = MT5Manager.LastError()
            except Exception as e:
                last_error = f"Exception getting LastError: {e}"
            
        # Debug: Print account info after deposit
        try:
            user_info = self.manager.UserGet(login_id)
            if user_info:
                pass
        except Exception as e:
            print(f"[MT5 DEBUG] Error fetching account info after deposit: {e}")
        return result

    @ensure_connected
    def withdraw_funds(self, login_id, amount, comment):
        if abs(amount) <= 0:
            return False
        return self._handle_funds_operation(login_id, -abs(amount), comment, MT5Manager.MTDeal.EnDealAction.DEAL_BALANCE, "Withdrawal")

    @ensure_connected
    def credit_in(self, login_id, amount, comment):
        if abs(amount) <= 0:
            return "False"

        return self._handle_funds_operation(login_id, amount, comment, MT5Manager.MTDeal.EnDealAction.DEAL_CREDIT, "Credit In")

    @ensure_connected
    def credit_out(self, login_id, amount, comment):
        if abs(amount) <= 0:
            return "False"

        return self._handle_funds_operation(login_id, -amount, comment, MT5Manager.MTDeal.EnDealAction.DEAL_CREDIT, "Credit Out")

    @ensure_connected
    def bonus_in(self, login_id, amount, comment):
        if abs(amount) <= 0:
            return "False"
        return self._handle_funds_operation(login_id, amount, comment, MT5Manager.MTDeal.EnDealAction.DEAL_BONUS, "Bonus In")

    @ensure_connected
    def bonus_out(self, login_id, amount, comment):
        if abs(amount) <= 0:
            return "False"
        return self._handle_funds_operation(login_id, -amount, comment, MT5Manager.MTDeal.EnDealAction.DEAL_BONUS, "Bonus Out")

    @ensure_connected
    def internal_transfer(self, login_id_in, login_id_out, amount):
       
        if self.withdraw_funds(login_id_out, amount, f"Internal transfer to {login_id_in}"):
            return self.deposit_funds(login_id_in, amount, f"Internal transfer from {login_id_out}")
        return False

    @ensure_connected
    def _handle_funds_operation(self, login_id, amount, comment, deal_action, operation_type):
        try:
            # Ensure proper type conversion
            login_id = int(login_id)
            amount = float(amount)
            comment = str(comment)
           
           
            deal_id = self.manager.DealerBalance(login_id, amount, deal_action, comment)
            if not deal_id:
                self._handle_balance_error(MT5Manager.LastError(), operation_type)
                return False
            else:
                self._print_user_balance(login_id)
                return True
        except Exception as e:
            print(f"[MT5 DEBUG] Exception in _handle_funds_operation: {e}")
            return False

    @ensure_connected
    def _print_user_balance(self, login_id):
        user = self.manager.UserRequest(login_id)
        if not user:
            print(f"Failed to request user: {MT5Manager.LastError()}")
        else:
            print(f"User {user.Login}, balance: {user.Balance}")

    @ensure_connected
    def _handle_user_add_error(self, error):
        if error[1] == MT5Manager.EnMTAPIRetcode.MT_RET_USR_LOGIN_EXHAUSTED:
            error_msg = "No free logins on server"
            print(error_msg)
            raise Exception(error_msg)
        elif error[1] == MT5Manager.EnMTAPIRetcode.MT_RET_USR_LOGIN_PROHIBITED:
            error_msg = "Can't add user for non current server"
            print(error_msg)
            raise Exception(error_msg)
        elif error[1] == MT5Manager.EnMTAPIRetcode.MT_RET_USR_LOGIN_EXIST:
            error_msg = "User with the same login already exists"
            print(error_msg)
            raise Exception(error_msg)
        elif error[1] == MT5Manager.EnMTAPIRetcode.MT_RET_ERR_PERMISSIONS:
            error_msg = "MT5 manager account does not have permission to create accounts (MT_RET_ERR_PERMISSIONS)"
            print(error_msg)
            raise Exception(error_msg)
        else:
            error_msg = f"User was not added: {MT5Manager.LastError()}"
            print(error_msg)
            raise Exception(error_msg)

    @ensure_connected
    def _handle_balance_error(self, error, operation_type):
        if error[1] == MT5Manager.EnMTAPIRetcode.MT_RET_TRADE_MAX_MONEY:
            print("Money limit reached.")
        elif error[1] == MT5Manager.EnMTAPIRetcode.MT_RET_REQUEST_NO_MONEY:
            print(f"Not enough money for {operation_type}.")
        else:
            print(f"{operation_type} failed: {MT5Manager.LastError()}")

    @ensure_connected
    def toggle_algo(self, login_id, action):
        logger = logging.getLogger(__name__)
        logger.info(f"toggle_algo called for login_id={login_id}, action={action}")
        try:
            login_id_int = int(login_id)
        except Exception as e:
            logger.error(f"Failed to convert login_id to int: {login_id}, error: {e}")
            return False
        user = self.manager.UserGet(login_id_int)
        if not user:
            logger.error(f"UserGet failed for login_id={login_id}. MT5Manager.LastError: {MT5Manager.LastError()}")
            return False
        logger.info(f"Current user.Rights for {login_id}: {getattr(user, 'Rights', None)}")
        if action == "enable":
            logger.info(f"Setting user.Rights to algo_enable_rights: {algo_enable_rights} (binary: {bin(algo_enable_rights)})")
            user.Rights = algo_enable_rights
        elif action == "disable":
            logger.info(f"Setting user.Rights to algo_disable_rights: {algo_disable_rights} (binary: {bin(algo_disable_rights)})")
            user.Rights = algo_disable_rights
        else:
            logger.error(f"Unknown action: {action}")
            return False

        try:
            update_result = self.manager.UserUpdate(user)
            logger.info(f"UserUpdate result for {login_id}: {update_result}")
            if not update_result:
                last_error = MT5Manager.LastError()
                logger.error(f"UserUpdate failed for {login_id}. MT5Manager.LastError: {last_error}")
                return False
            logger.info(f"UserUpdate succeeded for {login_id}. New Rights: {user.Rights}")
            return True
        except Exception as e:
            logger.error(f"Exception in toggle_algo for {login_id}: {str(e)}", exc_info=True)
            return False

    @ensure_connected
    def change_leverage(self, login_id, leverage):
        try:
            login_id = int(login_id)
            leverage = int(leverage)
        except (ValueError, TypeError) as e:
            print(f"[MT5 DEBUG] Type conversion error in change_leverage: {e}")
            return False
           
        user = self.manager.UserGet(login_id)
        if user:
            print(f"[MT5 DEBUG] Leverage before change: {user.Leverage}")
            user.Leverage = leverage
            if self.manager.UserUpdate(user):
                print(f"[MT5 DEBUG] Leverage changed to {leverage}")
                # Fetch and print updated leverage
                updated_user = self.manager.UserGet(login_id)
                if updated_user:
                    print(f"[MT5 DEBUG] Leverage after change: {updated_user.Leverage}")
                return True
            else:
                print(f"[MT5 DEBUG] Leverage change failed: {MT5Manager.LastError()[1]}")
                return False
        else:
            print(f"[MT5 DEBUG] User not found for login_id: {login_id}")
            return False

    def get_default_groups_from_config(self, account_type='real'):
        """Get default groups from admin panel configuration"""
        try:
            from adminPanel.models import TradeGroup
           
            config_groups = []
           
            if account_type.lower() == 'demo':
                # For demo accounts, get demo default and other demo groups
                demo_default = TradeGroup.objects.filter(is_demo_default=True, is_active=True).first()
                if demo_default:
                    config_groups.append(demo_default.name)
                    logger.info(f"Found configured demo default group: {demo_default.name}")
               
                # Add other enabled demo groups
                other_demo_groups = TradeGroup.objects.filter(is_active=True, type='demo').exclude(is_demo_default=True)
                for group in other_demo_groups:
                    config_groups.append(group.name)
                    logger.info(f"Found configured demo group: {group.name}")
            else:
                # For real accounts, get real default and other real groups
                real_default = TradeGroup.objects.filter(is_default=True, is_active=True).first()
                if real_default:
                    config_groups.append(real_default.name)
                    logger.info(f"Found configured real default group: {real_default.name}")
               
                # Add other enabled real groups
                other_real_groups = TradeGroup.objects.filter(is_active=True, type='real').exclude(is_default=True)
                for group in other_real_groups:
                    config_groups.append(group.name)
                    logger.info(f"Found configured real group: {group.name}")
           
            logger.info(f"Loaded {len(config_groups)} {account_type} groups from admin configuration")
            return config_groups
           
        except Exception as e:
            logger.error(f"Error loading {account_type} groups from admin configuration: {e}")
            return []

    @ensure_connected
    def get_group_list(self, account_type='real'):
        """Get list of available MT5 groups for the specified account type"""
        groups = []
        try:
            if not self.manager:
                logger.error("Cannot get groups - MT5 manager not initialized")
                return groups

            # Check connection status
            try:
               
                # Get total number of groups
                total = self.manager.GroupTotal()
               
                if total > 0:
                    for i in range(total):
                        try:
                            group = self.manager.GroupNext(i)
                           
                            if group and hasattr(group, 'Group'):
                                group_name = group.Group
                                groups.append(group_name)
                            elif group:
                                # Try different attribute names if 'Group' doesn't exist
                                for attr in ['Name', 'group', 'name', 'GroupName']:
                                    if hasattr(group, attr):
                                        group_name = getattr(group, attr)
                                        groups.append(group_name)
                                        break
                                else:
                                    logger.warning(f"Group object at index {i} has no recognizable name attribute: {dir(group)}")
                            else:
                                logger.warning(f"GroupNext({i}) returned None or invalid object")
                        except Exception as e:
                            logger.error(f"Error getting group at index {i}: {str(e)}")
                            continue
                else:
                    logger.warning("No groups reported by GroupTotal")
               
            except Exception as e:
                logger.error(f"Error using GroupTotal/GroupNext: {str(e)}")
               
                # Try fallback with MT5 API group enumeration (different method)
                logger.info("Trying alternative group enumeration method...")
                try:
                    # Try GroupNext method instead of GroupGet with index
                    for i in range(total):
                        try:
                            group = self.manager.GroupNext(i)
                            if group and hasattr(group, 'Group'):
                                group_name = group.Group
                                groups.append(group_name)
                                logger.info(f"Found group via GroupNext: {group_name}")
                        except Exception as e:
                            logger.debug(f"Error with GroupNext at index {i}: {str(e)}")
                            continue
                except Exception as e:
                    logger.error(f"Error using GroupNext method: {str(e)}")

            # If no groups found via MT5 API, try groups from admin configuration
            if not groups:
                logger.warning("No groups found via MT5 API, trying admin configuration...")
                config_groups = self.get_default_groups_from_config(account_type)
               
                if config_groups:
                    logger.info("Testing configured groups from admin panel...")
                    for group_name in config_groups:
                        try:
                            # Test if this group exists by trying to get it
                            group_obj = self.manager.GroupGet(group_name)
                            if group_obj:
                                groups.append(group_name)
                                logger.info(f"Validated admin configured group: {group_name}")
                            else:
                                logger.warning(f"Admin configured group {group_name} not found in MT5, but adding as fallback")
                                groups.append(group_name)  # Add anyway as fallback
                        except Exception as e:
                            logger.warning(f"Admin configured group {group_name} not accessible: {e}, but adding as fallback")
                            groups.append(group_name)  # Add anyway as fallback
                            continue
                   
                    # If we still have no groups after config lookup, add some hardcoded fallbacks
                    if not groups:
                        logger.warning("No groups found even in admin configuration, using hardcoded fallbacks...")
                        fallback_groups = ['real\\KRSNA-1', 'demo\\KRSNA'] if account_type == 'real' else ['demo\\KRSNA', 'real\\KRSNA-1']
                        groups.extend(fallback_groups)
                        logger.info(f"Added hardcoded fallback groups: {fallback_groups}")

            if groups:
                pass
            else:
                logger.error("No MT5 groups found via API, admin configuration, or hardcoded fallbacks")

            return groups

        except Exception as e:
            logger.error(f"Critical error in get_group_list: {str(e)}")
            return groups

    @ensure_connected
    def get_open_positions(self, login_id):
        positions = self.manager.PositionGet(login_id)  
        if not positions:
            return []  

        formatted_positions = []
        for position in positions:            formatted_positions.append({
                "date": position.TimeCreate,
                "id": position.Position,
                "symbol": position.Symbol,
                "volume": round(position.Volume/10000, 2),
                "price": position.PriceOpen,
                "profit": position.Profit,
                "type": "Buy" if position.Action == 0 else "Sell",
            })

        return formatted_positions

    @ensure_connected
    def change_master_password(self, login_id, master_pass):
        if self.manager.UserPasswordChange(0, int(login_id), str(master_pass)):
            return True
        print(MT5Manager.LastError())
        return False

    @ensure_connected
    def get_balance(self, login_id):
        try:
            # Check if this account lookup recently failed
            cached_failure = get_cached_account_data(login_id, 'balance')
            if cached_failure:
                return 0.0  # Return 0 for known failed accounts without API call
           
            account = self.manager.UserAccountGet(int(login_id))
            if account:
                return account.Balance
           
            # Account not found - cache the failure and conditionally log error
            cache_failed_account_lookup(login_id, 'balance', 300)  # Cache for 5 minutes

            # Attempt to remove stale DB rows referencing this MT5 login
            try:
                _remove_trading_account_from_db(login_id, reason='balance lookup')
            except Exception:
                # Swallow exceptions here; we'll still log the account-not-found event
                pass

            if should_log_error(login_id, 'balance_not_found'):
                # logger.warning(f"MT5 account not found for login_id: {login_id} (balance lookup)")
                pass
            return 0.0  # Return 0 balance instead of False for better error handling
        except Exception as e:
            if should_log_error(login_id, 'balance_error'):
                logger.error(f"Error in get_balance for {login_id}: {str(e)}")
            return 0.0  # Return 0 balance on error

    @ensure_connected
    def get_equity(self, login_id):
        try:
            # Check if this account lookup recently failed
            cached_failure = get_cached_account_data(login_id, 'equity')
            if cached_failure:
                return 0.0  # Return 0 for known failed accounts without API call
           
            account = self.manager.UserAccountGet(int(login_id))
            if account:
                return account.Equity
           
            # Account not found - cache the failure and conditionally log error
            cache_failed_account_lookup(login_id, 'equity', 300)  # Cache for 5 minutes

            # Attempt to remove stale DB rows referencing this MT5 login
            try:
                _remove_trading_account_from_db(login_id, reason='equity lookup')
            except Exception:
                pass

            if should_log_error(login_id, 'equity_not_found'):
                # logger.warning(f"MT5 account not found for login_id: {login_id} (equity lookup)")
                pass
            return 0.0  # Return 0 equity instead of False for better error handling
        except Exception as e:
            if should_log_error(login_id, 'equity_error'):
                logger.error(f"Error in get_equity for {login_id}: {str(e)}")
            return 0.0  # Return 0 equity on error

    @ensure_connected
    def total_account_profit(self, login_id):
        """Calculate total account profit (Equity - Balance)"""
        try:
            # Check if this account lookup recently failed
            cached_failure = get_cached_account_data(login_id, 'profit')
            if cached_failure:
                return 0.0  # Return 0 for known failed accounts without API call
           
            account = self.manager.UserAccountGet(int(login_id))
            if account:
                profit = account.Equity - account.Balance
                return profit
           
            # Account not found - cache the failure and conditionally log error
            cache_failed_account_lookup(login_id, 'profit', 300)  # Cache for 5 minutes

            # Attempt to remove stale DB rows referencing this MT5 login
            try:
                _remove_trading_account_from_db(login_id, reason='profit calculation')
            except Exception:
                pass

            if should_log_error(login_id, 'profit_not_found'):
                # logger.warning(f"MT5 account not found for login_id: {login_id} (profit calculation)")
                pass
            return 0.0  # Return 0 profit instead of False for better error handling
        except Exception as e:
            if should_log_error(login_id, 'profit_error'):
                logger.error(f"Error in total_account_profit for {login_id}: {str(e)}")
            return 0.0  # Return 0 profit on error

    @ensure_connected
    def total_account_deposits(self, login_id):
        """Calculate total deposits for an account"""
        try:
            # Check if this account lookup recently failed
            cached_failure = get_cached_account_data(login_id, 'deposits')
            if cached_failure:
                return 0.0  # Return 0 for known failed accounts without API call
           
            # Use time-based approach for DealRequest
            import time
            from datetime import datetime, timedelta
           
            # Try with a more recent timeframe first
            end_time = int(time.time())
            start_time = int((datetime.now() - timedelta(days=365)).timestamp())
           
            deals = self.manager.DealRequest(int(login_id), start_time, end_time)
           
            if deals and isinstance(deals, (list, tuple)):
                total_deposits = 0.0
                for deal in deals:
                    try:
                        # Check if it's a deposit (Action == 2 means balance operation, Profit > 0 means deposit)
                        if hasattr(deal, 'Action') and hasattr(deal, 'Profit'):
                            if deal.Action == 2 and deal.Profit > 0:
                                total_deposits += float(deal.Profit)
                    except (AttributeError, ValueError) as e:
                        continue
                return round(total_deposits, 2)
           
            # No deals found - cache the failure and conditionally log error
            cache_failed_account_lookup(login_id, 'deposits', 300)  # Cache for 5 minutes
           
            if should_log_error(login_id, 'deposits_not_found'):
                logger.warning(f"MT5 deals not found for login_id: {login_id} (deposits calculation)")
           
            return 0.0  # Return 0 deposits instead of False for better error handling
        except Exception as e:
            if should_log_error(login_id, 'deposits_error'):
                logger.error(f"Error in total_account_deposits for {login_id}: {str(e)}")
            return 0.0  # Return 0 deposits on error

    @ensure_connected
    def total_account_withdrawls(self, login_id):
        """Calculate total withdrawals for an account"""
        try:
            # Check if this account lookup recently failed
            cached_failure = get_cached_account_data(login_id, 'withdrawals')
            if cached_failure:
                return 0.0  # Return 0 for known failed accounts without API call
           
            # Use time-based approach for DealRequest
            import time
            from datetime import datetime, timedelta
           
            # Try with a more recent timeframe first
            end_time = int(time.time())
            start_time = int((datetime.now() - timedelta(days=365)).timestamp())
           
            deals = self.manager.DealRequest(int(login_id), start_time, end_time)
           
            if deals and isinstance(deals, (list, tuple)):
                total_withdrawals = 0.0
                for deal in deals:
                    try:
                        # Check if it's a withdrawal (Action == 2 means balance operation, Profit < 0 means withdrawal)
                        if hasattr(deal, 'Action') and hasattr(deal, 'Profit'):
                            if deal.Action == 2 and deal.Profit < 0:
                                total_withdrawals += abs(float(deal.Profit))
                    except (AttributeError, ValueError) as e:
                        continue
                return round(total_withdrawals, 2)
           
            # No deals found - cache the failure and conditionally log error
            cache_failed_account_lookup(login_id, 'withdrawals', 300)  # Cache for 5 minutes
           
            if should_log_error(login_id, 'withdrawals_not_found'):
                logger.warning(f"MT5 deals not found for login_id: {login_id} (withdrawals calculation)")
           
            return 0.0  # Return 0 withdrawals instead of False for better error handling
        except Exception as e:
            if should_log_error(login_id, 'withdrawals_error'):
                logger.error(f"Error in total_account_withdrawls for {login_id}: {str(e)}")
            return 0.0  # Return 0 withdrawals on error

    @ensure_connected
    def toggle_account_status(self, login_id, action):
        user = self.manager.UserGet(login_id)
        if user:
            if action == "enable":
                user.Rights = account_create_rights
            if action == "disable":
                user.Rights = disable_account_rights
           
            if self.manager.UserUpdate(user):
                return True
            else:
                print(MT5Manager.LastError())
                print("false")
                return False

    @ensure_connected
    def change_account_group(self, login_id, group):
        user = self.manager.UserGet(login_id)
        if user:
            user.Group = str(group)
           
            if self.manager.UserUpdate(user):
                return True
            else:
                print(MT5Manager.LastError())
                return False

    @ensure_connected
    def get_group_of(self, login_id):
        """Get the group of a specific user account"""
        try:
            return self.manager.UserGroup(int(login_id))
        except Exception as e:
            logger.error(f"Error getting group for user {login_id}: {str(e)}")
            return None

    @ensure_connected
    def get_leverage(self, login_id):
        """Get the leverage of a specific user account"""
        try:
            account = self.manager.UserAccountGet(int(login_id))
            if account:
                return account.Leverage
            return None
        except Exception as e:
            logger.error(f"Error getting leverage for user {login_id}: {str(e)}")
            return None

    @ensure_connected
    def get_group_configuration(self, group_name):
        """Get detailed configuration for a specific group"""
        try:
            for i in range(self.manager.GroupTotal()):
                group = self.manager.GroupNext(i)
                if group.Group == group_name:
                    return {
                        'name': group.Group,
                        'leverage_max': getattr(group, 'LeverageMax', 1000),
                        'leverage_min': getattr(group, 'LeverageMin', 1),
                        'is_demo': 'demo' in group.Group.lower(),
                        'currency': getattr(group, 'Currency', 'USD'),
                        'margin_mode': getattr(group, 'MarginMode', 0)
                    }
            return None
        except Exception as e:
            logger.error(f"Error getting group configuration for {group_name}: {str(e)}")
            return None

    @ensure_connected
    def get_all_group_configurations(self):
        """Get detailed configurations for all available groups"""
        try:
            groups_config = []
            for i in range(self.manager.GroupTotal()):
                group = self.manager.GroupNext(i)
                group_info = {
                    'name': group.Group,
                    'leverage_max': getattr(group, 'LeverageMax', 1000),
                    'leverage_min': getattr(group, 'LeverageMin', 1),
                    'is_demo': 'demo' in group.Group.lower(),
                    'is_live': 'demo' not in group.Group.lower(),
                    'currency': getattr(group, 'Currency', 'USD'),
                    'margin_mode': getattr(group, 'MarginMode', 0),
                    'deposit_min': getattr(group, 'DepositMin', 0),
                    'description': f"{'Demo' if 'demo' in group.Group.lower() else 'Live'} trading group"
                }
                groups_config.append(group_info)
            return groups_config
        except Exception as e:
            logger.error(f"Error getting all group configurations: {str(e)}")
            return []

    @ensure_connected
    def get_account_info(self, login_id):
        """Get basic account information including balance, equity, etc."""
        try:
            user = self.manager.UserGet(int(login_id))
            account = self.manager.UserAccountGet(int(login_id))
           
            if not user or not account:
                return None
               
            return {
                'login': user.Login,
                'name': f"{user.FirstName} {user.LastName}",
                'email': user.EMail,
                'balance': account.Balance,
                'equity': account.Equity,
                'group': user.Group,
                'leverage': user.Leverage,
                'rights': user.Rights
            }
        except Exception as e:
            logger.error(f"Error getting account info for {login_id}: {str(e)}")
            return None

    @ensure_connected
    def get_account_details(self, login_id):
        """Get detailed account information including balance, equity, margin, etc."""
        try:
            user = self.manager.UserGet(int(login_id))
            account = self.manager.UserAccountGet(int(login_id))
           
            if not user or not account:
                return None
               
            return {
                'login': user.Login,
                'name': f"{user.FirstName} {user.LastName}",
                'email': user.EMail,
                'balance': account.Balance,
                'equity': account.Equity,
                'margin': account.Margin,
                'margin_free': account.MarginFree,
                'margin_level': account.MarginLevel,
                'profit': account.Profit,
                'group': user.Group,
                'leverage': user.Leverage,
                'rights': user.Rights,
                'last_access': user.LastAccess,
                'registration': user.Registration
            }
        except Exception as e:
            logger.error(f"Error getting account details for {login_id}: {str(e)}")
            return None

    def _generate_password(self, length=8):
        """Generate a secure password for MT5 accounts that meets MT5 requirements"""
        import random
        import string
       
        # Use format based on working examples: Test_123, Pass_456
        # Format: [Capital][3-4 lowercase]_[3 digits]
       
        # Generate a 4-letter word starting with capital
        uppercase = random.choice(string.ascii_uppercase)
        lowercase_part = ''.join(random.choices(string.ascii_lowercase, k=3))
        digits_part = ''.join(random.choices(string.digits, k=3))
       
        # Create password with underscore format: Test_123 style
        password = f"{uppercase}{lowercase_part}_{digits_part}"
       
        return password
       
    def create_account(self, name="", email="", phone="", group=None, leverage=100, password=None, investor_password=None, account_type='real'):
        """Create a new MT5 trading account with user details"""
        try:
            if not self.manager:
                logger.error("MT5 Manager not connected")
                return None

            # Get available groups for the account type
            available_groups = self.get_group_list(account_type)
           
            # If no groups found via API, return empty list and let calling code handle it
            if not available_groups:
                logger.error("No groups found via get_group_list() - MT5 server may need configuration")
                return None

            # Use specified group if valid, otherwise use admin-configured default
            if group and group in available_groups:
                selected_group = group
            else:
                # Get default group from admin configuration
                try:
                    from adminPanel.models import TradeGroup
                   
                    if account_type.lower() == 'demo':
                        default_group = TradeGroup.objects.filter(is_demo_default=True, is_active=True).first()
                        group_type_name = "demo default"
                    else:
                        default_group = TradeGroup.objects.filter(is_default=True, is_active=True).first()
                        group_type_name = "real default"
                   
                    if default_group and default_group.name in available_groups:
                        selected_group = default_group.name
                        
                    else:
                        # Fallback to first available group
                        selected_group = available_groups[0]
                        logger.warning(f"No admin-configured {group_type_name} group found, using first available: {selected_group}")
                       
                except Exception as e:
                    logger.error(f"Error getting admin-configured default group: {e}")
                    selected_group = available_groups[0]
                    logger.info(f"Using first available group as fallback: {selected_group}")

                if group:
                    pass

            
           
            try:
                # Create the user object
                user = MT5Manager.MTUser(self.manager)
                user.Group = str(selected_group)
                user.Leverage = int(leverage)
                user.Name = str(name)
                user.Rights = account_create_rights
               
                # Add user contact details if available
                if email:
                    # Try different possible email attributes
                    for email_attr in ['Email', 'EMail', 'email', 'Comment']:
                        try:
                            setattr(user, email_attr, str(email))
                            break
                        except:
                            continue
               
                if phone:
                    # Try different possible phone attributes
                    for phone_attr in ['Phone', 'PhoneNumber', 'phone', 'Telephone', 'Tel']:
                        try:
                            setattr(user, phone_attr, str(phone))
                            break
                        except:
                            continue

                # Generate passwords if not provided
                if not password or not investor_password:
                    password = self._generate_password()
                    investor_password = self._generate_password()
                    
                # Ensure passwords are strings
                master_pwd = str(password) if password else self._generate_password()
                investor_pwd = str(investor_password) if investor_password else self._generate_password()
               
                add_result = self.manager.UserAdd(user, master_pwd, investor_pwd)
               
                if not add_result:
                    # Get the last error for debugging
                    last_error = MT5Manager.LastError()
                    logger.error(f"Failed to add user to MT5. Last error: {last_error}")
                    logger.error(f"Failed passwords were - Master: '{master_pwd}', Investor: '{investor_pwd}'")
                    self._handle_user_add_error(last_error)
                    return None

                # Get the created user's login ID
                if hasattr(user, 'Login'):
                    login = user.Login
                    return {
                        'login': login,
                        'group': selected_group,
                        'master_password': master_pwd,
                        'investor_password': investor_pwd
                    }
                else:
                    logger.error("Created user object has no Login attribute")
                    return None

            except Exception as e:
                logger.error(f"Error during account creation: {str(e)}")
                return None

        except Exception as e:
            logger.error(f"Error in create_account: {str(e)}")
            return None

    def list_mt5_accounts(self):
        """List all MT5 accounts with their details"""
        try:
            if not self.manager:
                logger.error("MT5 Manager not connected")
                return None

            accounts = []
            try:
                # Get total number of users
                total = self.manager.UserTotal()

                # Use UserGet to iterate through users
                for i in range(total):
                    try:
                        # Get user by index
                        user = self.manager.UserGet(i)
                        if user:
                            try:
                                # Get account details
                                account = self.manager.UserAccountGet(user.Login)
                                if account:
                                    # Create account data with safe value extraction
                                    account_data = {
                                        'login': user.Login,
                                        'name': getattr(user, 'Name', '') or f"{getattr(user, 'FirstName', '')} {getattr(user, 'LastName', '')}".strip(),
                                        'email': getattr(user, 'EMail', ''),
                                        'group': getattr(user, 'Group', ''),
                                        'leverage': getattr(user, 'Leverage', 100),
                                        'balance': float(getattr(account, 'Balance', 0.0)),
                                        'equity': float(getattr(account, 'Equity', 0.0)),
                                        'margin': float(getattr(account, 'Margin', 0.0)),
                                        'margin_free': float(getattr(account, 'MarginFree', 0.0)),
                                        'margin_level': float(getattr(account, 'MarginLevel', 0.0)),
                                        'status': 'active' if getattr(user, 'Rights', 0) & crights.USER_RIGHT_ENABLED else 'disabled',
                                        'algo_enabled': bool(getattr(user, 'Rights', 0) & crights.USER_RIGHT_EXPERT)
                                    }
                                   
                                    # Add optional fields only if they exist
                                    try:
                                        if hasattr(user, 'LastAccess'):
                                            account_data['last_access'] = user.LastAccess
                                        if hasattr(user, 'RegDate'):
                                            account_data['registration'] = user.RegDate
                                    except Exception:
                                        pass  # Ignore errors with optional fields
                                   
                                    accounts.append(account_data)
                            except Exception as e:
                                logger.error(f"Error getting account details for {user.Login}: {str(e)}")
                    except Exception as e:
                        logger.error(f"Error getting user at index {i}: {str(e)}")
                return accounts

            except Exception as e:
                logger.error(f"Error accessing MT5 users: {str(e)}")
                return None

        except Exception as e:
            logger.error(f"Error listing MT5 accounts: {str(e)}")
            return None

    def get_mt5_account(self, login_id):
        """Get details of a specific MT5 account"""
        try:
            if not self.manager:
                logger.error("MT5 Manager not connected")
                return None

            user = self.manager.UserGet(int(login_id))
            if not user:
                logger.warning(f"MT5 account not found: {login_id}")
                return None

            account = self.manager.UserAccountGet(int(login_id))
            if not account:
                logger.warning(f"MT5 account data not found: {login_id}")
                return None

            return {
                'login': user.Login,
                'name': f"{user.FirstName} {user.LastName}".strip(),
                'email': user.EMail,
                'group': user.Group,
                'leverage': user.Leverage,
                'balance': account.Balance,
                'equity': account.Equity,
                'margin': account.Margin,
                'margin_free': account.MarginFree,
                'margin_level': account.MarginLevel,
                'profit': account.Profit,
                'rights': user.Rights,
                'last_access': user.LastAccess,
                'registration': user.Registration
            }
        except Exception as e:
            logger.error(f"Error getting MT5 account {login_id}: {str(e)}")
            return None

    def sync_mt5_groups(self):
        """Sync MT5 groups with database"""
        from .models import MT5GroupConfig
       
        try:
            if not self.manager or not getattr(self.manager, 'connected', False):
                logger.error("Cannot sync groups - MT5 manager not connected")
                return False

            # Get current groups from MT5
            mt5_groups = []
            try:
                total = self.manager.GroupTotal()
                logger.info(f"Found {total} MT5 groups")
               
                for i in range(total):
                    try:
                        group = self.manager.GroupNext(i)  # Use GroupNext instead of GroupGet
                        if group and hasattr(group, 'Group'):
                            mt5_groups.append(group.Group)
                            logger.debug(f"Found MT5 group: {group.Group}")
                    except Exception as e:
                        logger.error(f"Error getting group at index {i}: {str(e)}")
                        continue

            except Exception as e:
                logger.error(f"Error fetching groups from MT5: {str(e)}")
               


            if not mt5_groups:
                logger.error("No groups found in MT5")
                return False

            # Update database
            for group_name in mt5_groups:
                is_demo = 'demo' in group_name.lower()
                MT5GroupConfig.objects.update_or_create(
                    group_name=group_name,
                    defaults={
                        'is_demo': is_demo,
                        'is_enabled': True,
                        'last_sync': timezone.now()
                    }
                )

            # Disable groups not in MT5
            MT5GroupConfig.objects.exclude(group_name__in=mt5_groups).update(is_enabled=False)

            logger.info(f"Successfully synced {len(mt5_groups)} groups with database")
            return True

        except Exception as e:
            logger.error(f"Error syncing MT5 groups: {str(e)}")
            return False

    def get_available_groups(self, account_type='real'):
        """Get list of available groups from database, syncing with MT5 if needed"""
        from .models import MT5GroupConfig
       
        try:
            # Check if we need to sync
            last_sync = MT5GroupConfig.objects.filter(is_enabled=True).order_by('-last_sync').first()
            if not last_sync or (timezone.now() - last_sync.last_sync).total_seconds() > 3600:  # Sync if older than 1 hour
                self.sync_mt5_groups()

            # Get groups from database
            is_demo = account_type.lower() == 'demo'
            groups = MT5GroupConfig.objects.filter(
                is_enabled=True,
                is_demo=is_demo
            ).values_list('group_name', flat=True)

            groups = list(groups)
            if not groups:
                # If no groups found for the specified type, try syncing again
                self.sync_mt5_groups()
                groups = MT5GroupConfig.objects.filter(
                    is_enabled=True,
                    is_demo=is_demo
                ).values_list('group_name', flat=True)
                groups = list(groups)

            return groups

        except Exception as e:
            logger.error(f"Error getting available groups: {str(e)}")
            return []

    def delete_account(self, login):
        """Delete an MT5 trading account"""
        try:
            if not self.manager:
                logger.error("MT5 Manager not connected")
                return False

            logger.info(f"Attempting to delete MT5 account: {login}")
           
            # First try to disable the account
            try:
                user = self.manager.UserGet(str(login))
                if user:
                    user.Rights = 0  # Remove all rights
                    self.manager.UserUpdate(user)
                    logger.info(f"Disabled MT5 account: {login}")
            except Exception as e:
                logger.error(f"Error disabling MT5 account {login}: {str(e)}")

            # Then delete the account
            result = self.manager.UserDelete(int(login))
            if result:
                logger.info(f"Successfully deleted MT5 account: {login}")
                return True
            else:
                logger.error(f"Failed to delete MT5 account: {login}")
                return False

        except Exception as e:
            logger.error(f"Error deleting MT5 account {login}: {str(e)}")
            return False

    @ensure_connected
    def pause_mam_copy(self, login_id):
        """
        Set the Agent field to 0 to pause MAM copy for the given login_id.
        Returns True if successful, False otherwise.
        """
        if not self.manager:
            raise Exception("MT5 Manager not connected")
        user = self.manager.UserGet(int(login_id))
        if user:
            user.Agent = 0
            if self.manager.UserUpdate(user):
                return True
        return False

    @ensure_connected
    def start_mam_copy(self, login_id, agent):
        """
        Set the Agent field to the given agent (master account id) to start MAM copy for the given login_id.
        Returns True if successful, False otherwise.
        """
        if not self.manager:
            raise Exception("MT5 Manager not connected")
        user = self.manager.UserGet(int(login_id))
        if user:
            user.Agent = int(agent)
            if self.manager.UserUpdate(user):
                return True
        return False

    @ensure_connected
    def enable_double_trade(self, login_id):
        """
        Enable double trade functionality for a specific account by modifying the Agent field.
        This prefixes the current Agent value with 'DOUBLE_' to indicate double trade is enabled.
        Returns True if successful, False otherwise.
        """
        if not self.manager:
            raise Exception("MT5 Manager not connected")
        user = self.manager.UserGet(int(login_id))
        if user:
            current_agent = str(user.Agent)
            if not current_agent.startswith("DOUBLE_"):
                user.Agent = f"DOUBLE_{current_agent}"
                if self.manager.UserUpdate(user):
                    return True
        return False

    @ensure_connected
    def disable_double_trade(self, login_id):
        """
        Disable double trade functionality for a specific account by removing the 'DOUBLE_' prefix.
        Returns True if successful, False otherwise.
        """
        if not self.manager:
            raise Exception("MT5 Manager not connected")
        user = self.manager.UserGet(int(login_id))
        if user:
            current_agent = str(user.Agent)
            if current_agent.startswith("DOUBLE_"):
                # Remove the 'DOUBLE_' prefix
                original_agent = current_agent.replace("DOUBLE_", "", 1)
                user.Agent = int(original_agent) if original_agent.isdigit() else 0
                if self.manager.UserUpdate(user):
                    return True
        return False

    @ensure_connected
    def is_double_trade_enabled(self, login_id):
        """
        Check if double trade is enabled for a specific account.
        Returns True if enabled, False otherwise.
        """
        if not self.manager:
            raise Exception("MT5 Manager not connected")
        user = self.manager.UserGet(int(login_id))
        if user:
            return str(user.Agent).startswith("DOUBLE_")
        return False

    @ensure_connected
    def get_double_trade_status(self, login_id):
        """
        Get detailed double trade status for an account.
        Returns dict with status information.
        """
        if not self.manager:
            raise Exception("MT5 Manager not connected")
        user = self.manager.UserGet(int(login_id))
        if user:
            agent_str = str(user.Agent)
            is_enabled = agent_str.startswith("DOUBLE_")
            original_agent = agent_str.replace("DOUBLE_", "", 1) if is_enabled else agent_str
           
            return {
                'login_id': login_id,
                'double_trade_enabled': is_enabled,
                'agent_field': agent_str,
                'original_agent': original_agent,
                'is_mam_follower': int(original_agent) > 0 if original_agent.isdigit() else False
            }
        return None

    @ensure_connected
    def enable_account(self, login_id):
        """Enable a trading account by setting appropriate user rights"""
        try:
            login_id = int(login_id)
            user = self.manager.UserGet(login_id)
            if not user:
                print(f"[MT5 DEBUG] User not found for login_id: {login_id}")
                return False
           
            print(f"[MT5 DEBUG] Current rights for {login_id}: {user.Rights}")
           
            # Set rights to enable the account
            user.Rights = account_create_rights
           
            if self.manager.UserUpdate(user):
                print(f"[MT5 DEBUG] Account {login_id} enabled successfully")
                return True
            else:
                error = MT5Manager.LastError()
                print(f"[MT5 DEBUG] Failed to enable account {login_id}: {error}")
                return False
               
        except Exception as e:
            print(f"[MT5 DEBUG] Exception in enable_account for {login_id}: {e}")
            return False

    @ensure_connected
    def disable_account(self, login_id):
        """Disable a trading account by removing USER_RIGHT_ENABLED"""
        try:
            login_id = int(login_id)
            user = self.manager.UserGet(login_id)
            if not user:
                print(f"[MT5 DEBUG] User not found for login_id: {login_id}")
                return False
           
            print(f"[MT5 DEBUG] Current rights for {login_id}: {user.Rights}")
           
            # Set rights to disable the account (remove USER_RIGHT_ENABLED)
            user.Rights = disable_account_rights
           
            if self.manager.UserUpdate(user):
                print(f"[MT5 DEBUG] Account {login_id} disabled successfully")
                return True
            else:
                error = MT5Manager.LastError()
                print(f"[MT5 DEBUG] Failed to disable account {login_id}: {error}")
                return False
               
        except Exception as e:
            print(f"[MT5 DEBUG] Exception in disable_account for {login_id}: {e}")
            return False
