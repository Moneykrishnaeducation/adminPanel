from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Create or reset admin user for testing'

    def add_arguments(self, parser):
        parser.add_argument('--email', type=str, default='admin@test.com',
                           help='Admin user email')
        parser.add_argument('--password', type=str, default='admin123',
                           help='Admin user password')

    def handle(self, *args, **options):
        User = get_user_model()
        email = options['email']
        password = options['password']
        
        # Check if user exists
        try:
            user = User.objects.get(email=email)
            self.stdout.write(f"User {email} already exists, updating...")
            user.set_password(password)
            user.manager_admin_status = 'Admin'
            user.is_superuser = True
            user.is_staff = True
            user.save()
            self.stdout.write(
                self.style.SUCCESS(f'Updated admin user: {email} / {password}')
            )
        except User.DoesNotExist:
            # Create new user
            user = User.objects.create_user(
                email=email,
                username=email,
                password=password,
                manager_admin_status='Admin',
                is_superuser=True,
                is_staff=True
            )
            self.stdout.write(
                self.style.SUCCESS(f'Created admin user: {email} / {password}')
            )
        
        # Test token generation
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        try:
            refresh['aud'] = 'admin.vtindex'
            refresh['scope'] = 'admin:*'
        except Exception:
            pass
        access_token = str(refresh.access_token)
        
        self.stdout.write(
            self.style.SUCCESS(f'JWT token (first 50 chars): {access_token[:50]}...')
        )
        
        self.stdout.write(
            self.style.SUCCESS('You can now test login at: http://127.0.0.1:8000/static/admin/index.html')
        )
