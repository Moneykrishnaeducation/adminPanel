from django.core.management.base import BaseCommand
from django.db import transaction
from adminPanel.models import CustomUser, ActivityLog

class Command(BaseCommand):
    help = "Safely delete a user and all dependent records by email"

    def add_arguments(self, parser):
        parser.add_argument("email", type=str)

    @transaction.atomic
    def handle(self, *args, **kwargs):
        email = kwargs["email"].strip().lower()

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            self.stdout.write(self.style.ERROR("User not found"))
            return

        uid = user.id

        self.stdout.write(self.style.WARNING(f"Deleting user {email} (ID {uid})"))

        # 1. Delete logs
        ActivityLog.objects.filter(user_id=uid).delete()

        # 2. Remove parent relations
        CustomUser.objects.filter(parent_ib=user).update(parent_ib=None)
        CustomUser.objects.filter(created_by=user).update(created_by=None)

        # 3. Finally delete user
        user.delete()

        self.stdout.write(self.style.SUCCESS("User deleted safely"))
