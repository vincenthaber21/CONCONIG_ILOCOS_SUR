# Daily Report Setup Guide

This guide explains how to set up and use the automatic daily sales and stock report feature.

## Overview

The daily report feature automatically generates a comprehensive PDF report containing:
- Daily sales summary (total transactions, revenue, VAT, patronage)
- Payment method breakdown
- Top products sold
- Stock levels and low stock alerts
- Stock by category
- Recent transactions list

## Email Configuration

The email credentials are configured in the `coop_kiosk/settings.py` file. They can be set via environment variables:

```bash
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_DEFAULT_SENDER=your-email@gmail.com
DAILY_REPORT_EMAIL=recipient@email.com
```

**Note:** For Gmail, you need to use an "App Password" instead of your regular password. Enable 2-factor authentication and generate an app password from your Google Account settings.

## Manual Execution

You can manually run the daily report command:

```bash
# Generate report for yesterday (default)
python manage.py send_daily_report

# Generate report for a specific date
python manage.py send_daily_report --date 2025-12-10

# Send to a different email address
python manage.py send_daily_report --to custom@email.com
```

## Automatic Scheduling

To automatically send the report every day at the end of the day, you need to schedule the command:

### Option 1: Windows Task Scheduler (Recommended for Windows)

1. Open Task Scheduler (search "Task Scheduler" in Windows)
2. Click "Create Basic Task"
3. Name it "Daily Sales Report" and set trigger to "Daily"
4. Set the time (e.g., 11:00 PM or 11:59 PM)
5. Set action to "Start a program"
6. Program: `C:\Users\PC\Desktop\self_checkout\venv\Scripts\python.exe`
7. Arguments: `manage.py send_daily_report`
8. Start in: `C:\Users\PC\Desktop\self_checkout`

Alternatively, create a batch file:

**create_report.bat:**
```batch
cd C:\Users\PC\Desktop\self_checkout
call venv\Scripts\activate.bat
python manage.py send_daily_report
```

Then schedule this batch file to run daily.

### Option 2: Linux/Mac Cron Job

Add this to your crontab (`crontab -e`):

```bash
# Send daily report at 11:59 PM every day
59 23 * * * cd /path/to/self_checkout && /path/to/venv/bin/python manage.py send_daily_report
```

### Option 3: Using Django-Q or Celery (For production)

For production environments, consider using Django-Q or Celery with periodic tasks:

```python
# In your tasks.py or similar
from django_q.tasks import schedule
from django.utils import timezone

schedule(
    'admin_panel.management.commands.send_daily_report',
    schedule_type='D',  # Daily
    repeats=-1,  # Repeat forever
    next_run=timezone.now().replace(hour=23, minute=59, second=0)
)
```

## Testing

Before setting up automatic scheduling, test the command manually:

```bash
# Test with today's date
python manage.py send_daily_report --date 2025-12-10

# Check your email inbox for the PDF attachment
```

## Troubleshooting

1. **Email not sending:**
   - Check email credentials in settings.py
   - Verify SMTP settings (port, TLS, etc.)
   - For Gmail: Use App Password, not regular password
   - Check firewall/network settings

2. **PDF generation fails:**
   - Ensure reportlab is installed: `pip install reportlab`
   - Check file permissions in the project directory

3. **Scheduled task not running:**
   - Verify the path to Python executable is correct
   - Check Task Scheduler logs
   - Ensure the command works when run manually

## Report Contents

The PDF report includes:

1. **Sales Summary**
   - Total transactions count
   - Total revenue
   - Subtotal, VAT amount, Vatable sales
   - Total patronage

2. **Payment Method Breakdown**
   - Cash transactions
   - Debit (Member Account) transactions
   - Debit transactions

3. **Top Products Sold** (Top 10)
   - Product name, barcode, quantity sold, revenue

4. **Stock Summary**
   - Total active products
   - Low stock items count
   - Out of stock items count

5. **Low Stock & Out of Stock Products**
   - Detailed list of products needing restocking

6. **Stock by Category**
   - Product count and stock levels per category

7. **Recent Transactions** (Last 50)
   - Transaction numbers, members, payment methods, amounts

## Customization

To customize the report, edit:
- `admin_panel/management/commands/send_daily_report.py`
- Modify the `generate_pdf()` method to add or remove sections
- Adjust styling in the ReportLab code

