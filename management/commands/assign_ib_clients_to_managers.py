#!/usr/bin/env python3
"""
Django management command to assign IB clients to their respective managers.
This is useful for retroactively fixing existing data where IB users became managers 
but their clients weren't automatically assigned.

Usage:
    python manage.py assign_ib_clients_to_managers
    python manage.py assign_ib_clients_to_managers --dry-run  # Preview changes without applying
    python manage.py assign_ib_clients_to_managers --manager-email manager@example.com  # Specific manager
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from adminPanel.models import CustomUser
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Assign IB clients to their respective managers based on referral relationships'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without applying them',
        )
        parser.add_argument(
            '--manager-email',
            type=str,
            help='Assign clients for specific manager only (by email)',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        specific_manager = options['manager_email']
        verbose = options['verbose']

        self.stdout.write(
            self.style.SUCCESS('🎯 Starting IB client to manager assignment process...')
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING('📋 DRY RUN MODE - No changes will be made')
            )

        # Get all users who are both IB and manager
        if specific_manager:
            ib_managers = CustomUser.objects.filter(
                email=specific_manager,
                role='manager',
                IB_status=True
            )
            if not ib_managers.exists():
                self.stdout.write(
                    self.style.ERROR(f'❌ No manager found with email: {specific_manager}')
                )
                return
        else:
            ib_managers = CustomUser.objects.filter(
                role='manager',
                IB_status=True
            )

        if not ib_managers.exists():
            self.stdout.write(
                self.style.WARNING('⚠️ No IB managers found in the system')
            )
            return

        total_assigned = 0
        managers_processed = 0

        with transaction.atomic():
            for manager in ib_managers:
                assigned_count = self._assign_clients_to_manager(manager, dry_run, verbose)
                total_assigned += assigned_count
                managers_processed += 1

                if assigned_count > 0:
                    self.stdout.write(
                        f'✅ Manager: {manager.email} -> Assigned {assigned_count} clients'
                    )
                elif verbose:
                    self.stdout.write(
                        f'ℹ️ Manager: {manager.email} -> No clients to assign'
                    )

        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(f'📊 Summary:')
        )
        self.stdout.write(f'   Managers processed: {managers_processed}')
        self.stdout.write(f'   Total clients assigned: {total_assigned}')
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('   💡 Run without --dry-run to apply changes')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS('   ✨ All changes have been applied!')
            )

    def _assign_clients_to_manager(self, manager, dry_run=False, verbose=False):
        """Assign IB clients to a specific manager"""
        assigned_count = 0

        # Method 1: Assign clients who used this manager's referral code
        if manager.referral_code:
            referral_clients = CustomUser.objects.filter(
                referral_code_used=manager.referral_code,
                role='client'
            ).exclude(created_by=manager)

            for client in referral_clients:
                if verbose:
                    self.stdout.write(
                        f'  📝 {client.email} (referral) -> Manager: {manager.email}'
                    )
                
                if not dry_run:
                    client.created_by = manager
                    client.save(update_fields=['created_by'])
                
                assigned_count += 1

        # Method 2: Assign clients where this manager is parent_ib
        parent_ib_clients = CustomUser.objects.filter(
            parent_ib=manager,
            role='client'
        ).exclude(created_by=manager)

        for client in parent_ib_clients:
            if verbose:
                self.stdout.write(
                    f'  📝 {client.email} (parent_ib) -> Manager: {manager.email}'
                )
            
            if not dry_run:
                client.created_by = manager
                client.save(update_fields=['created_by'])
            
            assigned_count += 1

        return assigned_count
