import threading
import MT5Manager
from adminPanel.models import ServerSetting
from django.core.exceptions import ObjectDoesNotExist
from asgiref.sync import sync_to_async
import asyncio


_manager_instance = None
_current_server_setting_id = None
_manager_lock = threading.Lock()  

def reset_manager_instance():
    """
    Force reset the MT5 manager instance to reload new credentials.
    Call this function after updating server settings to ensure new credentials are used.
    """
    global _manager_instance, _current_server_setting_id
    with _manager_lock:
        if _manager_instance:
            try:
                # Disconnect the current manager if connected
                if hasattr(_manager_instance, 'connected') and _manager_instance.connected:
                    _manager_instance.connected = False
                print("MT5 Manager instance reset successfully (manager.py)")
            except Exception as e:
                print(f"Error while resetting manager instance: {e}")
        
        _manager_instance = None
        _current_server_setting_id = None
        print("MT5 Manager connection has been reset and will reconnect with new credentials")  

class MT5ManagerAPI:
    def __init__(self):
        
        self.manager = MT5Manager.ManagerAPI()
        self.connected = False

    def connect(self, address, login, password, mode, timeout):
        if self.manager.Connect(address, login, password, mode, timeout):
            self.connected = True
            return self.manager
        else:
            error_message = f"Failed to connect to MT5 Manager: {MT5Manager.LastError()}"
            print(error_message)
            self.connected = False
            raise Exception(error_message)

def get_manager_instance():
    """
    Returns the global MT5ManagerAPI instance. If no instance exists or the server settings
    have changed, it initializes a new instance with the latest settings.
    """
    global _manager_instance, _current_server_setting_id

    # Check if we're in an async context
    try:
        loop = asyncio.get_running_loop()
        # We're in an async context, run sync code in a thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(_get_manager_instance_sync)
            return future.result()
    except RuntimeError:
        # No running loop, we're in sync context
        return _get_manager_instance_sync()

def _get_manager_instance_sync():
    """
    Synchronous version of get_manager_instance
    """
    global _manager_instance, _current_server_setting_id

    with _manager_lock:  
        try:
            latest_setting = ServerSetting.objects.latest("created_at")
        except ObjectDoesNotExist:
            raise Exception("No ServerSetting found. Please configure your server settings.")

        if latest_setting and (_manager_instance is None or _current_server_setting_id != latest_setting.id):
            _manager_instance = MT5ManagerAPI()
            _manager_instance.connect(
                address=latest_setting.server_ip,
                login=int(latest_setting.real_account_login),
                password=latest_setting.real_account_password,
                mode=MT5Manager.ManagerAPI.EnPumpModes.PUMP_MODE_FULL,
                timeout=120000,
            )
            _current_server_setting_id = latest_setting.id  
        return _manager_instance
