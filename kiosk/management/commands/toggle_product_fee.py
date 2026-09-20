from django.core.management.base import BaseCommand
from django.conf import settings
import os
import re


class Command(BaseCommand):
    help = 'Enable or disable the product fee feature (₱0.50 per product)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--enable',
            action='store_true',
            help='Enable the product fee feature',
        )
        parser.add_argument(
            '--disable',
            action='store_true',
            help='Disable the product fee feature',
        )
        parser.add_argument(
            '--status',
            action='store_true',
            help='Show current status of the product fee feature',
        )

    def handle(self, *args, **options):
        settings_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'coop_kiosk', 'settings.py')
        
        # If status is requested, just show current status
        if options['status']:
            current_status = getattr(settings, 'PRODUCT_FEE_ENABLED', True)
            status_text = 'ENABLED' if current_status else 'DISABLED'
            self.stdout.write(self.style.SUCCESS(f'Product Fee Feature: {status_text}'))
            return
        
        # Determine the action
        if options['enable'] and options['disable']:
            self.stdout.write(self.style.ERROR('Cannot use both --enable and --disable at the same time'))
            return
        
        if not options['enable'] and not options['disable']:
            self.stdout.write(self.style.ERROR('Please specify either --enable or --disable'))
            self.stdout.write(self.style.WARNING('Use --status to check current status'))
            return
        
        enable = options['enable']
        
        # Read the settings file
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'Settings file not found: {settings_file}'))
            return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error reading settings file: {str(e)}'))
            return
        
        # Find and replace the PRODUCT_FEE_ENABLED line
        # Pattern to match: PRODUCT_FEE_ENABLED = os.environ.get('PRODUCT_FEE_ENABLED', 'True').lower() == 'true'
        # or: PRODUCT_FEE_ENABLED = True/False
        pattern = r"PRODUCT_FEE_ENABLED\s*=\s*(?:os\.environ\.get\(['\"]PRODUCT_FEE_ENABLED['\"],\s*['\"](True|False)['\"]\)\.lower\(\)\s*==\s*['\"]true['\"]|True|False)"
        
        new_value = 'True' if enable else 'False'
        new_line = f"PRODUCT_FEE_ENABLED = os.environ.get('PRODUCT_FEE_ENABLED', '{new_value}').lower() == 'true'"
        
        if re.search(pattern, content):
            # Replace the existing line
            content = re.sub(pattern, new_line, content)
        else:
            # Add the setting if it doesn't exist (shouldn't happen, but handle it)
            # Find the location after VAT_FIXED
            vat_fixed_pattern = r"(VAT_FIXED\s*=\s*[\d.]+)"
            if re.search(vat_fixed_pattern, content):
                content = re.sub(
                    vat_fixed_pattern,
                    f"\\1\n\n# Product Fee Configuration\n# Enable/disable product fee feature (₱0.50 per product)\n# Can be toggled via: python manage.py toggle_product_fee --enable/--disable\n{new_line}",
                    content
                )
            else:
                # Fallback: add at the end of the file
                content += f"\n\n# Product Fee Configuration\n{new_line}\n"
        
        # Write the updated content back
        try:
            with open(settings_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            action = 'enabled' if enable else 'disabled'
            self.stdout.write(self.style.SUCCESS(f'Product Fee Feature has been {action}'))
            self.stdout.write(self.style.WARNING('Note: You may need to restart the Django server for changes to take effect'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error writing settings file: {str(e)}'))
            return

