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
        # Always use the REAL server (server_type=True) – never accidentally pick
        # the demo row just because it was saved more recently.
        real_setting = ServerSetting.objects.filter(server_type=True).order_by('-created_at').first()
        if real_setting is None:
            # Fallback to any setting (oldest first = original real server)
            real_setting = ServerSetting.objects.order_by('created_at').first()
        if real_setting is None:
            raise Exception("No ServerSetting found. Please configure your server settings.")

        if _manager_instance is None or _current_server_setting_id != real_setting.id:
            _manager_instance = MT5ManagerAPI()
            _manager_instance.connect(
                address=real_setting.get_decrypted_server_ip(),
                login=int(real_setting.real_account_login),
                password=real_setting.get_decrypted_real_account_password(),
                mode=MT5Manager.ManagerAPI.EnPumpModes.PUMP_MODE_FULL,
                timeout=120000,
            )
            _current_server_setting_id = real_setting.id
        return _manager_instance


# ── Demo server singleton ──────────────────────────────────────────────────

_demo_manager_instance = None
_demo_server_setting_id = None
_demo_manager_lock = threading.Lock()


def reset_demo_manager_instance():
    """
    Force-reset the demo MT5 manager instance.
    Call this after updating demo server settings.
    """
    global _demo_manager_instance, _demo_server_setting_id
    with _demo_manager_lock:
        if _demo_manager_instance:
            try:
                if hasattr(_demo_manager_instance, 'connected') and _demo_manager_instance.connected:
                    _demo_manager_instance.connected = False
            except Exception as e:
                print(f"Error while resetting demo manager instance: {e}")
        _demo_manager_instance = None
        _demo_server_setting_id = None
        print("Demo MT5 Manager connection has been reset")


def get_demo_manager_instance():
    """
    Returns a MT5ManagerAPI instance connected to the **demo** server
    (ServerSetting where server_type=False).
    Raises an exception if no demo server setting exists.
    """
    # Route through sync helper same way the real instance does
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(_get_demo_manager_instance_sync)
            return future.result()
    except RuntimeError:
        return _get_demo_manager_instance_sync()


def _get_demo_manager_instance_sync():
    global _demo_manager_instance, _demo_server_setting_id

    with _demo_manager_lock:
        try:
            demo_setting = ServerSetting.objects.filter(server_type=False).latest("created_at")
        except ObjectDoesNotExist:
            raise Exception("No demo ServerSetting found. Please configure demo server settings.")

        if demo_setting and (_demo_manager_instance is None or _demo_server_setting_id != demo_setting.id):
            _demo_manager_instance = MT5ManagerAPI()
            _demo_manager_instance.connect(
                address=demo_setting.get_decrypted_server_ip(),
                login=int(demo_setting.real_account_login),
                password=demo_setting.get_decrypted_real_account_password(),
                mode=MT5Manager.ManagerAPI.EnPumpModes.PUMP_MODE_FULL,
                timeout=120000,
            )
            _demo_server_setting_id = demo_setting.id
        return _demo_manager_instance
