#!/usr/bin/env python
"""
Fix invalid datetime values in DeletedMember records
Run this from manage.py shell: python manage.py shell < fix_deleted_member_dates.py
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'coop_kiosk.settings')
django.setup()

from members.models import DeletedMember
from django.utils import timezone

# Find and fix records with NULL or problematic deleted_at values
problematic = DeletedMember.objects.filter(deleted_at__isnull=True)
print(f"Found {problematic.count()} records with NULL deleted_at")

for record in problematic:
    # Use the restored_at as fallback, or use current time
    if record.restored_at:
        record.deleted_at = record.restored_at
    else:
        record.deleted_at = timezone.now()
    record.save()
    print(f"  Fixed: {record.first_name} {record.last_name}")

print("✓ All datetime values have been corrected!")
