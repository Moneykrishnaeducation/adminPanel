import csv
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date, parse_datetime
from datetime import datetime
from adminPanel.models import CustomUser, CommissioningProfile
from django.db import transaction, IntegrityError
from decimal import Decimal
from django.utils import timezone

CSV_FILE = 'UserData_2025-07-31_10-28-42.csv'

class Command(BaseCommand):
    help = 'Import users from CSV and map to CustomUser model.'

    def handle(self, *args, **options):
        with open(CSV_FILE, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            count = 0
            # Get the only available commissioning profile (if any)
            default_comm_profile = CommissioningProfile.objects.first()
            with transaction.atomic():
                for row in reader:
                    user_id = int(row['user_id']) if row['user_id'] else None
                    email = row['email'] or None
                    username = row['username'] or None
                    first_name = row['first_name'] or ''
                    last_name = row['last_name'] or ''
                    dob = parse_date(row['dob']) if row['dob'] else None
                    phone_number = row['phone_number'] or ''
                    address = row['address'] or ''
                    city = row['city'] or ''
                    zip_code = row['zip_code'] or ''
                    state = row['state'] or ''
                    country = row['country'] or ''
                    profile_pic = row['profile_pic'] or ''
                    id_proof = row['id_proof'] or ''
                    address_proof = row['address_proof'] or ''
                    address_proof_verified = row['address_proof_verified'].lower() == 'true' if row['address_proof_verified'] else False
                    id_proof_verified = row['id_proof_verified'].lower() == 'true' if row['id_proof_verified'] else False
                    IB_status = row['IB_status'].lower() == 'true' if row['IB_status'] else False
                    MAM_manager_status = row['MAM_manager_status'].lower() == 'true' if row['MAM_manager_status'] else False
                    created_by_user_id = int(row['created_by_user_id']) if row['created_by_user_id'] else None
                    created_by_username = row['created_by_username'] or None
                    manager_admin_status = row['manager_admin_status'] or 'None'
                    # Normalize manager_admin_status values
                    if manager_admin_status == 'Admin Level 1':
                        manager_admin_status = 'admin'
                    elif manager_admin_status in ['Manager Level 1', 'Manager Level 2', 'Manager Level 3']:
                        manager_admin_status = 'manager'
                    # Preserve original created/joined timestamp from CSV when available.
                    # Accept ISO datetime with timezone, or date-only strings.
                    date_joined_raw = row['date_joined'] or None
                    date_joined = None
                    if date_joined_raw and str(date_joined_raw).lower() != 'none':
                        # Try to parse full datetime first (handles offsets)
                        date_joined = parse_datetime(date_joined_raw)
                        if not date_joined:
                            # If parse_datetime failed, try parsing as a date and convert to midnight
                            parsed_date = parse_date(date_joined_raw)
                            if parsed_date:
                                date_joined = datetime.combine(parsed_date, datetime.min.time())
                                # Make timezone-aware using project timezone
                                try:
                                    date_joined = timezone.make_aware(date_joined)
                                except Exception:
                                    # If already aware or timezone not configured, leave as-is
                                    pass
                    is_active = row['is_active'].lower() == 'true' if row['is_active'] else True
                    is_staff = row['is_staff'].lower() == 'true' if row['is_staff'] else False
                    parent_ib_user_id = int(row['parent_ib_user_id']) if row['parent_ib_user_id'] else None
                    parent_ib_username = row['parent_ib_username'] or None
                    commissioning_profile_name = row['commissioning_profile_name'] or None
                    direct_client_count = int(row['direct_client_count']) if row['direct_client_count'] else 0
                    # Find parent_ib and commissioning_profile if possible
                    parent_ib = None
                    if parent_ib_user_id:
                        parent_ib = CustomUser.objects.filter(user_id=parent_ib_user_id).first()
                    commissioning_profile = None
                    if commissioning_profile_name:
                        commissioning_profile = CommissioningProfile.objects.filter(name=commissioning_profile_name).first()
                    # If IB user and commissioning_profile is missing, assign default
                    if IB_status and not commissioning_profile:
                        commissioning_profile = default_comm_profile
                        if commissioning_profile:
                            self.stdout.write(self.style.WARNING(f'Assigned default commissioning profile to IB user {email or username or user_id}'))
                        else:
                            self.stdout.write(self.style.ERROR(f'No commissioning profile found for IB user {email or username or user_id}, skipping user.'))
                            continue
                    # Prepare defaults for update/create
                    defaults = {
                        'email': email,
                        'username': username,
                        'first_name': first_name,
                        'last_name': last_name,
                        'dob': dob,
                        'phone_number': phone_number,
                        'address': address,
                        'city': city,
                        'zip_code': zip_code,
                        'state': state,
                        'country': country,
                        'profile_pic': profile_pic,
                        'address_proof_verified': address_proof_verified,
                        'id_proof_verified': id_proof_verified,
                        'IB_status': IB_status,
                        'MAM_manager_status': MAM_manager_status,
                        'manager_admin_status': manager_admin_status,
                        'date_joined': date_joined or timezone.now(),
                        'is_active': is_active,
                        'is_staff': is_staff,
                        'parent_ib': parent_ib,
                        'commissioning_profile': commissioning_profile,
                    }

                    # Try to find an existing user by user_id first, then by email to avoid unique constraint errors.
                    user = None
                    if user_id:
                        user = CustomUser.objects.filter(user_id=user_id).first()
                    if not user and email:
                        user = CustomUser.objects.filter(email=email).first()

                    created = False
                    if user:
                        # Update existing user instance
                        for k, v in defaults.items():
                            setattr(user, k, v)
                        # Ensure user_id is set when available
                        if getattr(user, 'user_id', None) is None and user_id:
                            user.user_id = user_id
                        try:
                            user.save()
                        except IntegrityError:
                            # If save fails due to race/unique constraint, try to recover by re-loading by email
                            existing = CustomUser.objects.filter(email=email).first() if email else None
                            if existing and existing.id != user.id:
                                for k, v in defaults.items():
                                    setattr(existing, k, v)
                                if getattr(existing, 'user_id', None) is None and user_id:
                                    existing.user_id = user_id
                                existing.save()
                                user = existing
                            else:
                                raise
                    else:
                        # No existing user found — create a new one
                        try:
                            create_data = dict(defaults)
                            if user_id:
                                create_data['user_id'] = user_id
                            user = CustomUser.objects.create(**create_data)
                            created = True
                        except IntegrityError:
                            # Likely a unique collision (email) — try to find the existing user by email and update it
                            existing = CustomUser.objects.filter(email=email).first() if email else None
                            if existing:
                                for k, v in defaults.items():
                                    setattr(existing, k, v)
                                if getattr(existing, 'user_id', None) is None and user_id:
                                    existing.user_id = user_id
                                existing.save()
                                user = existing
                                created = False
                            else:
                                # Re-raise if we cannot resolve
                                raise
                    count += 1
            self.stdout.write(self.style.SUCCESS(f'Successfully imported/updated {count} users.'))

            # --- Post-import: Fix parent_ib mapping for all users ---
            self.stdout.write('Fixing parent_ib mapping for all users...')
            with open(CSV_FILE, newline='', encoding='utf-8') as csvfile2:
                reader2 = csv.DictReader(csvfile2)
                fix_count = 0
                for row in reader2:
                    user_id = int(row['user_id']) if row['user_id'] else None
                    parent_ib_user_id = int(row['parent_ib_user_id']) if row['parent_ib_user_id'] else None
                    if user_id and parent_ib_user_id:
                        user = CustomUser.objects.filter(user_id=user_id).first()
                        parent_ib = CustomUser.objects.filter(user_id=parent_ib_user_id).first()
                        if user and parent_ib and user.parent_ib_id != parent_ib.id:
                            user.parent_ib = parent_ib
                            user.save(update_fields=['parent_ib'])
                            fix_count += 1
                self.stdout.write(self.style.SUCCESS(f'Fixed parent_ib for {fix_count} users.'))
