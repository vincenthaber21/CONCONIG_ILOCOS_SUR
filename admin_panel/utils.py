"""
Utility functions for admin panel, including email security features
"""
import re
from django.conf import settings
from django.contrib.auth.models import User
from members.models import Member


def mask_email_address(email_string):
    """
    Mask email addresses by hiding the username part for security.
    
    This function masks email usernames that are in the MASKED_EMAIL_USERNAMES setting.
    It handles both plain email addresses and formatted addresses like "Name <email@domain.com>"
    
    Args:
        email_string: Email address string, can be:
            - Plain email: "user@domain.com"
            - Formatted: "Display Name <user@domain.com>"
    
    Returns:
        str: Masked email address with username completely hidden (e.g., "************@gmail.com")
             or original email if username is not in the masked list
    """
    if not email_string:
        return email_string
    
    # Get list of usernames to mask from settings
    masked_usernames = getattr(settings, 'MASKED_EMAIL_USERNAMES', [])
    
    if not masked_usernames:
        return email_string
    
    # Pattern to match formatted email: "Display Name <email@domain.com>"
    formatted_pattern = r'^(.+?)\s*<([^<>@]+)@([^<>@]+)>$'
    formatted_match = re.match(formatted_pattern, email_string.strip())
    
    if formatted_match:
        # Handle formatted email: "Name <email@domain.com>"
        display_name = formatted_match.group(1).strip()
        username = formatted_match.group(2)
        domain = formatted_match.group(3)
        
        # Check if this username should be masked
        if username.lower() in [u.lower() for u in masked_usernames]:
            # Completely mask the username for security
            masked_username = '*' * len(username)
            
            masked_email = f"{masked_username}@{domain}"
            return f"{display_name} <{masked_email}>"
        
        # Return original if not in masked list
        return email_string
    
    # Pattern to match plain email: "email@domain.com"
    plain_pattern = r'^([^<>@]+)@([^<>@]+)$'
    plain_match = re.match(plain_pattern, email_string.strip())
    
    if plain_match:
        username = plain_match.group(1)
        domain = plain_match.group(2)
        
        # Check if this username should be masked
        if username.lower() in [u.lower() for u in masked_usernames]:
            # Completely mask the username for security
            masked_username = '*' * len(username)
            
            return f"{masked_username}@{domain}"
        
        # Return original if not in masked list
        return email_string
    
    # If pattern doesn't match, return original
    return email_string


def get_masked_from_email():
    """
    Get the masked version of DEFAULT_FROM_EMAIL from settings.
    
    Returns:
        str: Masked email address for use in from_email field
    """
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    return mask_email_address(from_email)


def get_admin_email():
    """
    Get admin email from database - checks superusers, staff users, and Member admins.
    
    Returns:
        str: Admin email address for notifications
    """
    # First, try to get superuser email
    superuser = User.objects.filter(is_superuser=True, is_active=True).exclude(email='').first()
    if superuser and superuser.email:
        return superuser.email
    
    # Then try to get staff user email
    staff_user = User.objects.filter(is_staff=True, is_active=True).exclude(email='').first()
    if staff_user and staff_user.email:
        return staff_user.email
    
    # Finally, try to get Member with admin role
    admin_member = Member.objects.filter(member_role__slug='admin', is_active=True).exclude(email__isnull=True).exclude(email='').first()
    if admin_member and admin_member.email:
        return admin_member.email
    
    # Fall back to settings
    return getattr(settings, 'DAILY_REPORT_EMAIL', getattr(settings, 'ADMIN_EMAIL', 'habervincent21@gmail.com'))

