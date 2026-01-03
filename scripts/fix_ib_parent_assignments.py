# Script to fix parent_ib assignments for a given IB user
# Usage: Run in Django shell or as a management command

from adminPanel.models import CustomUser

def fix_ib_parent_assignments(ib_user_id):
    try:
        ib_user = CustomUser.objects.get(user_id=ib_user_id)
    except CustomUser.DoesNotExist:
        print(f"IB user with user_id {ib_user_id} does not exist.")
        return

    if not ib_user.IB_status or not ib_user.referral_code:
        print(f"User {ib_user_id} is not an IB or missing referral_code.")
        return

    # Find all clients who used this IB's referral code and have no parent_ib
    clients = CustomUser.objects.filter(referral_code_used=ib_user.referral_code, parent_ib__isnull=True)
    print(f"Found {clients.count()} clients to assign to IB {ib_user_id}.")
    for client in clients:
        client.parent_ib = ib_user
        client.save(update_fields=['parent_ib'])
        print(f"Assigned client {client.user_id} to IB {ib_user_id}.")
    print("Done.")

# Example usage:
# fix_ib_parent_assignments(7000005)

if __name__ == "__main__":
    fix_ib_parent_assignments(7000005)
