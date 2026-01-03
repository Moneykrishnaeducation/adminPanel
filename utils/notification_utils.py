"""
Notification Utility Functions
Helper functions to create notifications for various system events
"""

from adminPanel.models_notification import Notification
import logging

logger = logging.getLogger(__name__)


def create_ib_request_notification(user, status='pending'):
    """
    Create notification for IB (Introducing Broker) request
    
    Args:
        user: User who made the IB request
        status: Status of the request (pending, approved, rejected)
    """
    title_map = {
        'pending': 'IB Request Submitted',
        'approved': 'IB Request Approved',
        'rejected': 'IB Request Rejected',
    }
    
    message_map = {
        'pending': 'Your IB (Introducing Broker) request has been submitted and is under review.',
        'approved': 'Congratulations! Your IB request has been approved. You can now access partnership features.',
        'rejected': 'Your IB request has been rejected. Please contact support for more information.',
    }
    
    try:
        return Notification.create_notification(
            user=user,
            notification_type='IB',
            status=status,
            title=title_map.get(status, 'IB Request Update'),
            message=message_map.get(status, 'Your IB request status has been updated.'),
            action_url='/partnership',
            related_object_type='ib_request',
            metadata={'request_type': 'ib'}
        )
    except Exception as e:
        logger.error(f"Error creating IB notification: {e}")
        return None


def create_bank_transaction_notification(user, transaction_type, amount, status='pending'):
    """
    Create notification for bank transactions (deposit/withdrawal)
    
    Args:
        user: User who initiated the transaction
        transaction_type: Type of transaction (deposit, withdrawal, internal_transfer)
        amount: Transaction amount
        status: Status of the transaction
    """
    title_map = {
        'pending': f'Bank {transaction_type.title()} Pending',
        'approved': f'Bank {transaction_type.title()} Approved',
        'completed': f'Bank {transaction_type.title()} Completed',
        'rejected': f'Bank {transaction_type.title()} Rejected',
    }
    
    message_map = {
        'pending': f'Your bank {transaction_type} of ${amount} is being processed.',
        'approved': f'Your bank {transaction_type} of ${amount} has been approved.',
        'completed': f'Your bank {transaction_type} of ${amount} has been completed successfully.',
        'rejected': f'Your bank {transaction_type} of ${amount} has been rejected.',
    }
    
    try:
        return Notification.create_notification(
            user=user,
            notification_type='BANK',
            status=status,
            title=title_map.get(status, 'Bank Transaction Update'),
            message=message_map.get(status, f'Your bank {transaction_type} status has been updated.'),
            action_url='/transactions',
            related_object_type='bank_transaction',
            metadata={
                'transaction_type': transaction_type,
                'amount': str(amount)
            }
        )
    except Exception as e:
        logger.error(f"Error creating bank transaction notification: {e}")
        return None


def create_bank_details_notification(user, status='approved'):
    """
    Create notification for bank details approval/rejection
    
    Args:
        user: User whose bank details were reviewed
        status: Status of the bank details (approved, rejected, pending)
    """
    title_map = {
        'pending': 'Bank Details Under Review',
        'approved': 'Bank Details Approved',
        'rejected': 'Bank Details Rejected',
    }
    
    message_map = {
        'pending': 'Your bank details are being reviewed by our team.',
        'approved': 'Your bank details have been approved and verified.',
        'rejected': 'Your bank details have been rejected. Please update and resubmit.',
    }
    
    try:
        return Notification.create_notification(
            user=user,
            notification_type='BANK',
            status=status,
            title=title_map.get(status, 'Bank Details Update'),
            message=message_map.get(status, 'Your bank details status has been updated.'),
            action_url='/profile',
            related_object_type='bank_details',
            metadata={'detail_type': 'bank_details'}
        )
    except Exception as e:
        logger.error(f"Error creating bank details notification: {e}")
        return None


def create_crypto_transaction_notification(user, transaction_type, amount, currency, status='pending'):
    """
    Create notification for crypto transactions
    
    Args:
        user: User who initiated the transaction
        transaction_type: Type of transaction (deposit, withdrawal)
        amount: Transaction amount
        currency: Cryptocurrency type (BTC, ETH, USDT, etc.)
        status: Status of the transaction
    """
    title_map = {
        'pending': f'Crypto {transaction_type.title()} Pending',
        'approved': f'Crypto {transaction_type.title()} Approved',
        'completed': f'Crypto {transaction_type.title()} Completed',
        'rejected': f'Crypto {transaction_type.title()} Rejected',
    }
    
    message_map = {
        'pending': f'Your crypto {transaction_type} of {amount} {currency} is being processed.',
        'approved': f'Your crypto {transaction_type} of {amount} {currency} has been approved.',
        'completed': f'Your crypto {transaction_type} of {amount} {currency} has been completed successfully.',
        'rejected': f'Your crypto {transaction_type} of {amount} {currency} has been rejected.',
    }
    
    try:
        return Notification.create_notification(
            user=user,
            notification_type='CRYPTO',
            status=status,
            title=title_map.get(status, 'Crypto Transaction Update'),
            message=message_map.get(status, f'Your crypto {transaction_type} status has been updated.'),
            action_url='/transactions',
            related_object_type='crypto_transaction',
            metadata={
                'transaction_type': transaction_type,
                'amount': str(amount),
                'currency': currency
            }
        )
    except Exception as e:
        logger.error(f"Error creating crypto transaction notification: {e}")
        return None


def create_profile_change_notification(user, change_type, status='pending'):
    """
    Create notification for profile changes
    
    Args:
        user: User whose profile changed
        change_type: Type of change (email, phone, address, kyc, etc.)
        status: Status of the change
    """
    title_map = {
        'pending': f'{change_type.title()} Update Pending',
        'approved': f'{change_type.title()} Update Approved',
        'completed': f'{change_type.title()} Updated Successfully',
        'rejected': f'{change_type.title()} Update Rejected',
    }
    
    message_map = {
        'pending': f'Your {change_type} update is under review.',
        'approved': f'Your {change_type} update has been approved.',
        'completed': f'Your {change_type} has been updated successfully.',
        'rejected': f'Your {change_type} update has been rejected.',
    }
    
    try:
        return Notification.create_notification(
            user=user,
            notification_type='PROFILE',
            status=status,
            title=title_map.get(status, 'Profile Update'),
            message=message_map.get(status, 'Your profile has been updated.'),
            action_url='/profile',
            related_object_type='profile_change',
            metadata={'change_type': change_type}
        )
    except Exception as e:
        logger.error(f"Error creating profile change notification: {e}")
        return None


def create_document_upload_notification(user, document_type, status='pending'):
    """
    Create notification for document uploads
    
    Args:
        user: User who uploaded the document
        document_type: Type of document (passport, id, proof_of_address, etc.)
        status: Status of the document
    """
    title_map = {
        'pending': f'{document_type.title()} Under Review',
        'approved': f'{document_type.title()} Approved',
        'rejected': f'{document_type.title()} Rejected',
    }
    
    message_map = {
        'pending': f'Your {document_type} document is under review.',
        'approved': f'Your {document_type} document has been approved.',
        'rejected': f'Your {document_type} document has been rejected. Please upload a valid document.',
    }
    
    try:
        return Notification.create_notification(
            user=user,
            notification_type='DOCUMENT',
            status=status,
            title=title_map.get(status, 'Document Update'),
            message=message_map.get(status, 'Your document status has been updated.'),
            action_url='/profile',
            related_object_type='document',
            metadata={'document_type': document_type}
        )
    except Exception as e:
        logger.error(f"Error creating document upload notification: {e}")
        return None


def create_account_creation_notification(user, account_type, account_number, status='created'):
    """
    Create notification for trading account creation
    
    Args:
        user: User who owns the account
        account_type: Type of account (standard, demo, mam_manager, mam_investor, prop)
        account_number: Trading account number
        status: Status of the account creation
    """
    account_type_names = {
        'standard': 'Standard Trading Account',
        'demo': 'Demo Trading Account',
        'mam_manager': 'MAM Manager Account',
        'mam_investor': 'MAM Investor Account',
        'prop': 'Proprietary Trading Account',
    }
    
    title = f'{account_type_names.get(account_type, "Trading Account")} Created'
    message = f'Your {account_type_names.get(account_type, "trading account")} #{account_number} has been created successfully.'
    
    if status == 'approved':
        title = f'{account_type_names.get(account_type, "Trading Account")} Approved'
        message = f'Your {account_type_names.get(account_type, "trading account")} #{account_number} has been approved and is ready to use.'
    
    try:
        return Notification.create_notification(
            user=user,
            notification_type='ACCOUNT',
            status=status,
            title=title,
            message=message,
            action_url='/trading',
            related_object_type='trading_account',
            metadata={
                'account_type': account_type,
                'account_number': str(account_number)
            }
        )
    except Exception as e:
        logger.error(f"Error creating account creation notification: {e}")
        return None


def create_custom_notification(user, notification_type, status, title, message, action_url=None, metadata=None):
    """
    Create a custom notification
    
    Args:
        user: User to receive the notification
        notification_type: Type of notification (IB, BANK, CRYPTO, PROFILE, DOCUMENT, ACCOUNT)
        status: Status (pending, approved, rejected, created, completed)
        title: Notification title
        message: Notification message
        action_url: Optional URL for action
        metadata: Optional metadata dict
    """
    try:
        return Notification.create_notification(
            user=user,
            notification_type=notification_type,
            status=status,
            title=title,
            message=message,
            action_url=action_url,
            metadata=metadata or {}
        )
    except Exception as e:
        logger.error(f"Error creating custom notification: {e}")
        return None
