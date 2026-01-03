import MT5Manager
from MT5Manager import InitializeManagerAPIPath
import time
import threading
crights = MT5Manager.MTUser.EnUsersRights
import requests
import os

account_create_rights   =   crights.USER_RIGHT_ENABLED | \
                            crights.USER_RIGHT_PASSWORD | \
                            crights.USER_RIGHT_CONFIRMED | \
                            crights.USER_RIGHT_TRAILING | \
                            crights.USER_RIGHT_EXPERT 

algo_disable_rights     =   crights.USER_RIGHT_ENABLED | \
                            crights.USER_RIGHT_PASSWORD | \
                            crights.USER_RIGHT_CONFIRMED | \
                            crights.USER_RIGHT_TRAILING 

algo_enable_rights      =   crights.USER_RIGHT_ENABLED | \
                            crights.USER_RIGHT_PASSWORD | \
                            crights.USER_RIGHT_CONFIRMED | \
                            crights.USER_RIGHT_TRAILING | \
                            crights.USER_RIGHT_EXPERT 

disable_account_rights   =  crights.USER_RIGHT_PASSWORD | \
                            crights.USER_RIGHT_CONFIRMED | \
                            crights.USER_RIGHT_TRAILING | \
                            crights.USER_RIGHT_EXPERT 
                            
disable_trading_rights  =   crights.USER_RIGHT_ENABLED | \
                            crights.USER_RIGHT_PASSWORD | \
                            crights.USER_RIGHT_CONFIRMED | \
                            crights.USER_RIGHT_TRAILING | \
                            crights.USER_RIGHT_EXPERT | \
                            crights.USER_RIGHT_TRADE_DISABLED

enable_trading_rights  =    crights.USER_RIGHT_ENABLED | \
                            crights.USER_RIGHT_PASSWORD | \
                            crights.USER_RIGHT_CONFIRMED | \
                            crights.USER_RIGHT_TRAILING | \
                            crights.USER_RIGHT_EXPERT 


def ensure_connected(func):
    """
    Decorator to ensure the MT5 Manager is connected before executing a function.
    """
    def wrapper(self, *args, **kwargs):
        if not self.manager :
            raise Exception("MT5 Manager is not connected. Please reconnect.")
        return func(self, *args, **kwargs)
    return wrapper

_manager_instance = None
_current_server_setting = None
_manager_lock = threading.Lock()  

class MT5ManagerAPI:
    def __init__(self):
        unique_id = str(os.getpid())
        
        try:
            base_directory = os.path.join(os.getcwd(), 'mt5_instances')
            os.makedirs(base_directory, exist_ok=True)
            instance_directory = os.path.join(base_directory, unique_id)
            os.makedirs(instance_directory, exist_ok=True)
            InitializeManagerAPIPath(module_path=instance_directory, work_path=instance_directory)
        except Exception as e:
            print(e)
            
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


def latest_server_details():
    global access_token    
    from adminPanel.models import ServerSetting
    try:
        latest_server = ServerSetting.objects.order_by('-created_at').first()
        if latest_server:
            return {
                "ip_address": latest_server.server_ip,
                "real_login": latest_server.real_account_login,
                "password": latest_server.real_account_password,
            }
        else:
            print("No server settings found.")
            return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None
    
def get_manager_instance():
    """
    Returns the global MT5ManagerAPI instance. If no instance exists or the server settings
    have changed, it initializes a new instance with the latest settings.
    """
    global _manager_instance, _current_server_setting
    
    with _manager_lock:  
        try:
            latest_setting = latest_server_details()
            print(latest_setting)
        except:
            raise Exception("No ServerSetting found. Please configure your server settings.")

        
        if _manager_instance is None or _current_server_setting != latest_setting:
            _manager_instance = MT5ManagerAPI()
            print(latest_setting)
            _manager_instance.connect(
                address=latest_setting["ip_address"],
                login=int(latest_setting["real_login"]),
                password=latest_setting["password"],
                mode=MT5Manager.ManagerAPI.EnPumpModes.PUMP_MODE_FULL,
                timeout=120000,
            )
            print("Connected")
            _current_server_setting = latest_setting
        return _manager_instance


class MT5ManagerActions:
    def __init__(self):
        self.manager = get_manager_instance().manager

    @ensure_connected
    def add_new_account(self, group_name, leverage, client, master_password, investor_password, agent=0,):
        user = MT5Manager.MTUser(self.manager)
        user.Group = str(group_name)
        user.Leverage = int(leverage)
        user.FirstName = client["first_name"]
        user.LastName = client["last_name"]
        user.EMail = client["email"]
        user.Country = str(client["country"])
        user.Phone = client["phone_number"]
        user.Agent = agent
        user.Rights = account_create_rights
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
            return user.Login

    @ensure_connected
    def deposit_funds(self, login_id, amount, comment):
        if abs(amount) <= 0:
            return "False"
        return self._handle_funds_operation(login_id, amount, comment, MT5Manager.MTDeal.EnDealAction.DEAL_BALANCE, "Deposit")

    @ensure_connected
    def withdraw_funds(self, login_id, amount, comment):
        if -abs(amount) >= 0:
            return "False"
        return self._handle_funds_operation(login_id, -amount, comment, MT5Manager.MTDeal.EnDealAction.DEAL_BALANCE, "Withdrawal")

    @ensure_connected
    def credit_in(self, login_id, amount, comment):
        if abs(amount) <= 0:
            return "False"

        return self._handle_funds_operation(login_id, amount, comment, MT5Manager.MTDeal.EnDealAction.DEAL_CREDIT, "Credit In")

    @ensure_connected
    def credit_out(self, login_id, amount, comment):
        if -abs(amount) >= 0:
            return "False"

        return self._handle_funds_operation(login_id, -amount, comment, MT5Manager.MTDeal.EnDealAction.DEAL_CREDIT, "Credit Out")

    @ensure_connected
    def bonus_in(self, login_id, amount, comment):
        if abs(amount) <= 0:
            return "False"

        return self._handle_funds_operation(login_id, amount, comment, MT5Manager.MTDeal.EnDealAction.DEAL_BONUS, "Bonus In")

    @ensure_connected
    def bonus_out(self, login_id, amount, comment):
        if -abs(amount) >= 0:
            return "False"

        return self._handle_funds_operation(login_id, -amount, comment, MT5Manager.MTDeal.EnDealAction.DEAL_BONUS, "Bonus Out")

    @ensure_connected
    def internal_transfer(self, login_id_in, login_id_out, amount):
        if self.withdraw_funds(login_id_out, -amount, f"Internal transfer to {login_id_in}"):
            return self.deposit_funds(login_id_in, amount, f"Internal transfer from {login_id_out}")
        return False

    @ensure_connected
    def _handle_funds_operation(self, login_id, amount, comment, deal_action, operation_type):
        deal_id = self.manager.DealerBalance(login_id, amount, deal_action, comment)
        if not deal_id:
            self._handle_balance_error(MT5Manager.LastError(), operation_type)
            return False
        else:
            self._print_user_balance(login_id)
            return True

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
            print("No free logins on server")
        elif error[1] == MT5Manager.EnMTAPIRetcode.MT_RET_USR_LOGIN_PROHIBITED:
            print("Can't add user for non current server")
        elif error[1] == MT5Manager.EnMTAPIRetcode.MT_RET_USR_LOGIN_EXIST:
            print("User with the same login already exists")
        else:
            print(f"User was not added: {MT5Manager.LastError()}")

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
        user = self.manager.UserGet(login_id)
        if user:
            if action == "enable":
                user.Rights = algo_enable_rights
            if action == "disable":
                user.Rights = algo_disable_rights
            
            if self.manager.UserUpdate(user):
                return True
            else:
                print(MT5Manager.LastError())
                return False

    @ensure_connected
    def change_leverage(self, login_id, leverage):
        user = self.manager.UserGet(int(login_id))
        if user:
            user.Leverage = leverage
            
            if self.manager.UserUpdate(user):
                print("Leverage changed to", leverage)
                return True
            else:
                print(MT5Manager.LastError()[1])
                return False

    @ensure_connected
    def get_group_list(self):
        groups = []
        for i in range(self.manager.GroupTotal()):
            groups.append(self.manager.GroupNext(i).Group)
        return groups

    @ensure_connected
    def get_open_positions(self, login_id):
        positions = self.manager.PositionGet(login_id)  
        if not positions:
            return []  

        formatted_positions = []
        for position in positions:  
            formatted_positions.append({
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
        account = self.manager.UserAccountGet(int(login_id))
        if account:
            return account.Balance
        print(MT5Manager.LastError())
        return False
    
    @ensure_connected
    def get_equity(self, login_id):
        account = self.manager.UserAccountGet(int(login_id))
        if account:
            return account.Equity
        print(MT5Manager.LastError())
        return False


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
            user.Group = group
            if self.manager.UserUpdate(user):
                return True
        return False
    
    @ensure_connected
    def get_group_of(self, login_id):
        return self.manager.UserGroup(int(login_id))

    @ensure_connected
    def get_leverage(self, login_id):
        return self.manager.UserAccountGet(int(login_id)).Leverage

    @ensure_connected
    def pause_mam_copy(self, login_id):
        user = self.manager.UserGet(int(login_id))
        if user:
            user.Agent= 0
            if self.manager.UserUpdate(user):
                return True
        return False

    @ensure_connected
    def start_mam_copy(self, login_id, agent):
        user = self.manager.UserGet(int(login_id))
        if user:
            user.Agent= int(agent)
            if self.manager.UserUpdate(user):
                return True
        return False

    @ensure_connected
    def total_account_deposits(self, login_id):
        deals = self.manager.DealRequest(int(login_id), 0, int(time.time()))
        if deals:
            return sum([i.Profit for i in deals if i.Action == 2 and i.Profit > 0] )
        else:
            return float(0)

    @ensure_connected
    def total_account_withdrawls(self, login_id):
        deals = self.manager.DealRequest(int(login_id), 0, int(time.time()))
        if deals:
            return sum([i.Profit for i in deals if i.Action == 2 and i.Profit < 0] )
        else:
            return float(0)

    @ensure_connected
    def total_account_profit(self, login_id):
        deals = self.manager.DealRequest(int(login_id), 0, int(time.time()))
        if deals:
            return sum([i.Profit + i.Commission + i.Storage for i in deals if i.Action != 2])
        else:
            return float(0)

