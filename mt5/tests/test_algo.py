from django.test import TestCase
from unittest.mock import patch, MagicMock
from adminPanel.mt5.services import MT5ManagerActions, crights
from adminPanel.mt5.models import ServerSetting
import logging
import os

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class MT5AlgoTest(TestCase):
    @patch('adminPanel.mt5.services.MT5Manager')
    def setUp(self, mock_mt5):
        """Set up test environment with mocked MT5Manager"""
        # Create a test server setting
        ServerSetting.objects.create(
            server_ip=os.environ.get('MT5_SERVER', 'localhost:443'),
            real_account_login=os.environ.get('MT5_LOGIN', '1234'),
            real_account_password=os.environ.get('MT5_PASSWORD', 'password'),
            server_name_client='TestServer'
        )
        
        # Mock MT5Manager
        self.mock_manager = MagicMock()
        mock_mt5.ManagerAPI.return_value = self.mock_manager
        
        # Set up test account
        self.test_account = 123456
          # Create mock user object with initial rights
        self.mock_user = MagicMock()
        # Set initial rights - will be modified in tests
        initial_rights = (crights.USER_RIGHT_ENABLED | 
                         crights.USER_RIGHT_PASSWORD | 
                         crights.USER_RIGHT_CONFIRMED |
                         crights.USER_RIGHT_TRAILING |
                         crights.USER_RIGHT_EXPERT)
        self.mock_user.Rights = initial_rights
        
        # Set up the mock to track rights changes
        def user_update_side_effect(updated_user):
            self.mock_user.Rights = updated_user.Rights
            return True
        
        def get_user_side_effect(account_id):
            if account_id == self.test_account:
                return self.mock_user
            return None
            
        self.mock_manager.UserUpdate.side_effect = user_update_side_effect
        self.mock_manager.UserGet.side_effect = get_user_side_effect
        self.mock_manager.UserUpdate.return_value = True
        
        # Initialize MT5 manager with mocked components
        self.mt5 = MT5ManagerActions()
        self.mt5.manager = self.mock_manager
        
    def test_toggle_algo(self):
        """Test enabling and disabling algo trading"""
        logger.info("Starting algo trading toggle test...")
          # Test disable first
        logger.info("Testing disable algo trading...")
        
        # Verify initial rights include EXPERT
        self.assertTrue(bool(self.mock_user.Rights & crights.USER_RIGHT_EXPERT))
        
        # Expected rights after disable (everything except EXPERT)
        expected_disable_rights = (crights.USER_RIGHT_ENABLED | 
                                 crights.USER_RIGHT_PASSWORD | 
                                 crights.USER_RIGHT_CONFIRMED |
                                 crights.USER_RIGHT_TRAILING)
        
        # Test disable
        result = self.mt5.toggle_algo(self.test_account, enable=False)
        self.assertTrue(result.get('status'), f"Failed to disable algo: {result}")
        logger.info(f"Disable result: {result}")
        
        # Verify rights were updated correctly
        self.mock_manager.UserUpdate.assert_called_once()
        actual_rights = self.mock_user.Rights
        self.assertEqual(actual_rights & ~crights.USER_RIGHT_EXPERT, expected_disable_rights)
        self.assertFalse(bool(actual_rights & crights.USER_RIGHT_EXPERT))
          # Reset mock and prepare for enable test
        self.mock_manager.reset_mock()
        
        # Test enable
        logger.info("Testing enable algo trading...")
        
        # Expected rights after enable
        expected_enable_rights = (crights.USER_RIGHT_ENABLED | 
                                crights.USER_RIGHT_PASSWORD | 
                                crights.USER_RIGHT_CONFIRMED |
                                crights.USER_RIGHT_TRAILING |
                                crights.USER_RIGHT_EXPERT)
        
        # Test enable
        result = self.mt5.toggle_algo(self.test_account, enable=True)
        self.assertTrue(result.get('status'), f"Failed to enable algo: {result}")
        logger.info(f"Enable result: {result}")
        
        # Verify rights were updated correctly
        self.mock_manager.UserUpdate.assert_called_once()
        actual_rights = self.mock_user.Rights
        self.assertEqual(actual_rights, expected_enable_rights)
        self.assertTrue(bool(actual_rights & crights.USER_RIGHT_EXPERT))
