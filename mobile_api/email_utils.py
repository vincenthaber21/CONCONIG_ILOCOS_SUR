"""
Email utility module for asynchronous email sending.
This module provides functions to send emails in the background without blocking the API response.
Uses threading for async execution and includes retry logic for reliability.
"""
import threading
import logging
import time
from django.core.mail import EmailMessage, get_connection
from django.core.mail import EmailMultiAlternatives
from django.conf import settings

logger = logging.getLogger(__name__)

# Email sending configuration
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds between retries


def send_email_async(subject, body, recipient_email, from_email=None, max_retries=MAX_RETRIES, html_body=None):
    """
    Send an email asynchronously in a background thread.
    This function returns immediately without waiting for the email to be sent.
    Includes retry logic for better reliability.
    
    Args:
        subject: Email subject
        body: Email body (plain text)
        recipient_email: Recipient email address (string or list)
        from_email: Sender email (defaults to DEFAULT_FROM_EMAIL from settings)
        max_retries: Maximum number of retry attempts (default: 3)
        html_body: Optional HTML version of the email body
    
    Returns:
        threading.Thread: The thread object (can be used to check status if needed)
    """
    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL
    
    def _send_email_with_retry():
        """Internal function that runs in the background thread with retry logic"""
        recipients = [recipient_email] if isinstance(recipient_email, str) else recipient_email
        
        for attempt in range(1, max_retries + 1):
            try:
                # Use get_connection() with optimized settings for faster delivery
                # Connection timeout is set in settings.EMAIL_TIMEOUT
                connection = get_connection(
                    fail_silently=False,
                    use_tls=settings.EMAIL_USE_TLS,
                    timeout=getattr(settings, 'EMAIL_TIMEOUT', 10),
                )
                
                if html_body:
                    email = EmailMultiAlternatives(
                        subject=subject,
                        body=body,
                        from_email=from_email,
                        to=recipients,
                        connection=connection,
                    )
                    email.attach_alternative(html_body, "text/html")
                else:
                    email = EmailMessage(
                        subject=subject,
                        body=body,
                        from_email=from_email,
                        to=recipients,
                        connection=connection,
                    )
                
                # Send email (non-blocking in background thread)
                email.send()
                
                # Close connection immediately after sending
                connection.close()
                
                logger.info(f"Email sent successfully to {recipient_email} (attempt {attempt})")
                return  # Success - exit function
                
            except Exception as e:
                error_msg = str(e)
                logger.warning(
                    f"Email send attempt {attempt}/{max_retries} failed for {recipient_email}: {error_msg}"
                )
                
                # If this is not the last attempt, wait before retrying
                if attempt < max_retries:
                    time.sleep(RETRY_DELAY * attempt)  # Exponential backoff
                else:
                    # Last attempt failed - log error
                    logger.error(
                        f"Failed to send email to {recipient_email} after {max_retries} attempts: {error_msg}",
                        exc_info=True
                    )
                    # Don't raise exception - email failures shouldn't crash the app
    
    # Start email sending in a background thread
    thread = threading.Thread(target=_send_email_with_retry, daemon=True)
    thread.start()
    return thread


def send_otp_email(member, recipient, otp_code, amount, notes=''):
    """
    Send OTP email for fund transfer verification.
    This is a convenience wrapper around send_email_async.
    Optimized for fast delivery with async execution.
    
    Args:
        member: Member object (sender)
        recipient: Member object (recipient)
        otp_code: 6-digit OTP code
        amount: Transfer amount (Decimal)
        notes: Optional transfer notes
    
    Returns:
        threading.Thread: The thread object
    """
    subject = 'Fund Transfer Verification Code'

    # Plain-text fallback
    plain_body = f"""Dear {member.full_name},

Fund Transfer Verification

Recipient: {recipient.full_name} ({recipient.rfid_card_number})
Amount: ₱{amount:,.2f}
{('Notes: ' + notes) if notes else ''}

Your verification code: {otp_code}

Valid for 10 minutes. Do not share this code.

If you didn't request this, please contact support immediately.

Best regards,
BAGNOS MPC""".strip()

    # ── App color palette (mirrors mobile_app/constants/colors.js) ──
    # brand:        #ED1C24  (Bagnos logo red)
    # accent:       #E6C200  (Bagnos logo yellow)
    # background:   #f1f5f9  (light gray background)
    # panel:        #ffffff  (white panels)
    # muted:        #94a3b8
    # textPrimary:  #333333
    # textSecondary:#666666
    # borderLight:  #f0f0f0
    # success:      #16a34a
    # error:        #ef4444
    # warning:      #f97316

    notes_row = f"""
            <tr>
              <td style="padding:6px 0;color:#666666;font-size:14px;">Notes</td>
              <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{notes}</td>
            </tr>""" if notes else ''

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Fund Transfer Verification</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f1f5f9;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

          <!-- Header — brand green gradient matching app header -->
          <tr>
            <td style="background:linear-gradient(135deg,#C4121A 0%,#ED1C24 60%,#8B0E14 100%);padding:36px 40px;text-align:center;">
              <div style="display:inline-block;background:rgba(255,255,255,0.15);border-radius:50%;width:56px;height:56px;line-height:56px;font-size:28px;margin-bottom:14px;">🔐</div>
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:-0.3px;">Fund Transfer Verification</h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px;">BAGNOS MPC</p>
            </td>
          </tr>

          <!-- Greeting -->
          <tr>
            <td style="padding:32px 40px 0;">
              <p style="margin:0;font-size:15px;color:#666666;">Hello, <strong style="color:#333333;">{member.full_name}</strong></p>
              <p style="margin:10px 0 0;font-size:14px;color:#666666;line-height:1.6;">
                We received a request to transfer funds from your account. Please use the verification code below to confirm the transaction.
              </p>
            </td>
          </tr>

          <!-- Transfer Details Card — mirrors app card style (#f8fdf9 bg, #e8f5e9 accent) -->
          <tr>
            <td style="padding:24px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fdf9;border:1px solid #e8f5e9;border-radius:12px;padding:20px 24px;">
                <tr>
                  <td colspan="2" style="padding-bottom:12px;">
                    <span style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8;">Transfer Details</span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Recipient</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{recipient.full_name} <span style="color:#94a3b8;font-weight:400;">({recipient.rfid_card_number})</span></td>
                </tr>
                <tr>
                  <td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Amount</td>
                  <td style="padding:6px 0;color:#ED1C24;font-size:16px;font-weight:700;text-align:right;">₱{amount:,.2f}</td>
                </tr>{notes_row}
              </table>
            </td>
          </tr>

          <!-- OTP Code — brand green badge -->
          <tr>
            <td style="padding:28px 40px 0;text-align:center;">
              <p style="margin:0 0 14px;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8;">Your Verification Code</p>
              <div style="display:inline-block;background:linear-gradient(135deg,#C4121A,#ED1C24);border-radius:14px;padding:18px 48px;">
                <span style="font-size:38px;font-weight:800;letter-spacing:10px;color:#ffffff;font-family:'Courier New',monospace;">{otp_code}</span>
              </div>
              <p style="margin:14px 0 0;font-size:13px;color:#94a3b8;">
                ⏱ &nbsp;This code expires in <strong style="color:#ef4444;">10 minutes</strong>
              </p>
            </td>
          </tr>

          <!-- Warning — matches app warning/amber style -->
          <tr>
            <td style="padding:24px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#FEF7D5;border:1px solid #fed7aa;border-radius:10px;padding:14px 18px;">
                <tr>
                  <td style="font-size:13px;color:#9a3412;line-height:1.6;">
                    ⚠️ &nbsp;<strong>Security Notice:</strong> Never share this code with anyone. BAGNOS MPC will never ask for your OTP. If you did not initiate this transfer, please contact support immediately.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:32px 40px;text-align:center;border-top:1px solid #f0f0f0;margin-top:28px;">
              <p style="margin:0;font-size:13px;color:#94a3b8;">This is an automated message from</p>
              <p style="margin:4px 0 0;font-size:14px;font-weight:700;color:#333333;">BAGNOS MPC</p>
              <p style="margin:12px 0 0;font-size:12px;color:#94a3b8;">© 2026 BAGNOS MPC. All rights reserved.</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    logger.info(f"Initiating OTP email send to {member.email} for transfer of ₱{amount:,.2f}")
    return send_email_async(subject, plain_body, member.email, html_body=html_body)


def send_transfer_completion_emails(sender, recipient, amount, sender_balance_after, recipient_balance_after, notes='', transaction_date=None):
    """
    Send transfer completion emails to both sender and receiver.
    This function sends two emails asynchronously - one to sender and one to recipient.
    
    Args:
        sender: Member object (sender)
        recipient: Member object (recipient)
        amount: Transfer amount (Decimal)
        sender_balance_after: Sender's balance after transfer
        recipient_balance_after: Recipient's balance after transfer
        notes: Optional transfer notes
        transaction_date: Transaction date/time (optional)
    
    Returns:
        tuple: (sender_thread, recipient_thread) - Thread objects for both emails
    """
    from django.utils import timezone
    from datetime import datetime
    
    if transaction_date is None:
        transaction_date = timezone.now()
    
    # Format transaction date
    if isinstance(transaction_date, str):
        try:
            transaction_date = datetime.fromisoformat(transaction_date.replace('Z', '+00:00'))
        except:
            transaction_date = timezone.now()
    
    # Convert to Asia/Manila local time before formatting
    local_transaction_date = timezone.localtime(transaction_date)
    date_str = local_transaction_date.strftime('%B %d, %Y at %I:%M %p')
    
    # ── Shared helper: notes row for HTML tables ──
    def _notes_row(label='Notes'):
        if not notes:
            return ''
        return f"""
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">{label}</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{notes}</td>
                </tr>"""

    # ════════════════════════════════════════════════
    # SENDER email — "Money Sent"
    # ════════════════════════════════════════════════
    sender_subject = 'Fund Transfer Completed - Money Sent'

    sender_plain = f"""Dear {sender.full_name},

Your fund transfer has been completed successfully.

Transfer Details:
Amount Sent:      ₱{amount:,.2f}
Recipient:        {recipient.full_name}
Recipient RFID:   {recipient.rfid_card_number}
{('Notes: ' + notes) if notes else ''}Transaction Date:  {date_str}

Your Account Balance: ₱{sender_balance_after:,.2f}

This transaction has been recorded in your account history.
If you did not authorize this transfer, please contact support immediately.

Best regards,
BAGNOS MPC""".strip()

    sender_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Fund Transfer Completed</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f1f5f9;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#C4121A 0%,#ED1C24 60%,#8B0E14 100%);padding:36px 40px;text-align:center;">
              <div style="display:inline-block;background:rgba(255,255,255,0.15);border-radius:50%;width:56px;height:56px;line-height:56px;font-size:28px;margin-bottom:14px;">✅</div>
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:-0.3px;">Transfer Completed</h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px;">BAGNOS MPC</p>
            </td>
          </tr>

          <!-- Greeting -->
          <tr>
            <td style="padding:32px 40px 0;">
              <p style="margin:0;font-size:15px;color:#666666;">Hello, <strong style="color:#333333;">{sender.full_name}</strong></p>
              <p style="margin:10px 0 0;font-size:14px;color:#666666;line-height:1.6;">
                Your fund transfer has been completed successfully. Here are the details of your transaction.
              </p>
            </td>
          </tr>

          <!-- Transfer Details Card -->
          <tr>
            <td style="padding:24px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fdf9;border:1px solid #e8f5e9;border-radius:12px;padding:20px 24px;">
                <tr>
                  <td colspan="2" style="padding-bottom:12px;">
                    <span style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8;">Transfer Details</span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Amount Sent</td>
                  <td style="padding:6px 0;color:#ED1C24;font-size:16px;font-weight:700;text-align:right;">₱{amount:,.2f}</td>
                </tr>
                <tr>
                  <td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Recipient</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{recipient.full_name}</td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Recipient RFID</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{recipient.rfid_card_number}</td>
                </tr>{_notes_row()}
                <tr>
                  <td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Transaction Date</td>
                  <td style="padding:6px 0;color:#333333;font-size:13px;font-weight:600;text-align:right;">{date_str}</td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Balance Banner -->
          <tr>
            <td style="padding:20px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#C4121A,#ED1C24);border-radius:12px;padding:16px 24px;">
                <tr>
                  <td>
                    <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.75);text-transform:uppercase;letter-spacing:0.8px;">Your Account Balance</p>
                    <p style="margin:4px 0 0;font-size:28px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;">₱{sender_balance_after:,.2f}</p>
                  </td>
                  <td style="text-align:right;font-size:30px;">💳</td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Security Notice -->
          <tr>
            <td style="padding:20px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#FEF7D5;border:1px solid #fed7aa;border-radius:10px;padding:14px 18px;">
                <tr>
                  <td style="font-size:13px;color:#9a3412;line-height:1.6;">
                    ⚠️ &nbsp;If you did not authorize this transfer, please contact support immediately.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:32px 40px;text-align:center;border-top:1px solid #f0f0f0;margin-top:8px;">
              <p style="margin:0;font-size:13px;color:#94a3b8;">This transaction has been recorded in your account history.</p>
              <p style="margin:8px 0 0;font-size:14px;font-weight:700;color:#333333;">BAGNOS MPC</p>
              <p style="margin:8px 0 0;font-size:12px;color:#94a3b8;">© 2026 BAGNOS MPC. All rights reserved.</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    # ════════════════════════════════════════════════
    # RECIPIENT email — "Money Received"
    # ════════════════════════════════════════════════
    recipient_subject = 'Fund Transfer Received - Money Received'

    recipient_plain = f"""Dear {recipient.full_name},

You have received a fund transfer.

Transfer Details:
Amount Received:  ₱{amount:,.2f}
Sender:           {sender.full_name}
Sender RFID:      {sender.rfid_card_number}
{('Notes: ' + notes) if notes else ''}Transaction Date:  {date_str}

Your Account Balance: ₱{recipient_balance_after:,.2f}

The funds have been added to your account and are available for use.

Best regards,
BAGNOS MPC""".strip()

    recipient_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Fund Transfer Received</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f1f5f9;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#C4121A 0%,#ED1C24 60%,#8B0E14 100%);padding:36px 40px;text-align:center;">
              <div style="display:inline-block;background:rgba(255,255,255,0.15);border-radius:50%;width:56px;height:56px;line-height:56px;font-size:28px;margin-bottom:14px;">💰</div>
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:-0.3px;">Money Received</h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px;">BAGNOS MPC</p>
            </td>
          </tr>

          <!-- Greeting -->
          <tr>
            <td style="padding:32px 40px 0;">
              <p style="margin:0;font-size:15px;color:#666666;">Hello, <strong style="color:#333333;">{recipient.full_name}</strong></p>
              <p style="margin:10px 0 0;font-size:14px;color:#666666;line-height:1.6;">
                Great news! You have received a fund transfer. The funds are now available in your account.
              </p>
            </td>
          </tr>

          <!-- Transfer Details Card -->
          <tr>
            <td style="padding:24px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fdf9;border:1px solid #e8f5e9;border-radius:12px;padding:20px 24px;">
                <tr>
                  <td colspan="2" style="padding-bottom:12px;">
                    <span style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8;">Transfer Details</span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Amount Received</td>
                  <td style="padding:6px 0;color:#ED1C24;font-size:16px;font-weight:700;text-align:right;">₱{amount:,.2f}</td>
                </tr>
                <tr>
                  <td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Sender</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{sender.full_name}</td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Sender RFID</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{sender.rfid_card_number}</td>
                </tr>{_notes_row()}
                <tr>
                  <td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Transaction Date</td>
                  <td style="padding:6px 0;color:#333333;font-size:13px;font-weight:600;text-align:right;">{date_str}</td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Balance Banner -->
          <tr>
            <td style="padding:20px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#C4121A,#ED1C24);border-radius:12px;padding:16px 24px;">
                <tr>
                  <td>
                    <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.75);text-transform:uppercase;letter-spacing:0.8px;">Your Account Balance</p>
                    <p style="margin:4px 0 0;font-size:28px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;">₱{recipient_balance_after:,.2f}</p>
                  </td>
                  <td style="text-align:right;font-size:30px;">💳</td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:32px 40px;text-align:center;border-top:1px solid #f0f0f0;margin-top:8px;">
              <p style="margin:0;font-size:13px;color:#94a3b8;">The funds have been added to your account and are available for use.</p>
              <p style="margin:8px 0 0;font-size:14px;font-weight:700;color:#333333;">BAGNOS MPC</p>
              <p style="margin:8px 0 0;font-size:12px;color:#94a3b8;">© 2026 BAGNOS MPC. All rights reserved.</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    # Send both emails asynchronously
    sender_thread = None
    recipient_thread = None

    if sender.email:
        logger.info(f"Sending transfer completion email to sender: {sender.email}")
        sender_thread = send_email_async(sender_subject, sender_plain, sender.email, html_body=sender_html)

    if recipient.email:
        logger.info(f"Sending transfer completion email to recipient: {recipient.email}")
        recipient_thread = send_email_async(recipient_subject, recipient_plain, recipient.email, html_body=recipient_html)

    return sender_thread, recipient_thread



def send_biometric_otp_email(member, otp_code):
    """
    Send OTP email for biometric (fingerprint) login enrollment verification.
    """
    from admin_panel.models import KioskConfig

    brand = KioskConfig.get().brand_title_short()
    subject = 'Fingerprint Login Verification Code'

    plain_body = f"""Dear {member.full_name},

Fingerprint Login Enrollment

You requested to enable Fingerprint Login on your {brand} account.

Your verification code: {otp_code}

Valid for 10 minutes. Do not share this code.

If you did not request this, please contact support immediately.

Best regards,
BAGNOS MPC""".strip()

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Fingerprint Login Verification</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f1f5f9;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
          <tr>
            <td style="background:linear-gradient(135deg,#C4121A 0%,#ED1C24 60%,#8B0E14 100%);padding:36px 40px;text-align:center;">
              <div style="display:inline-block;background:rgba(255,255,255,0.15);border-radius:50%;width:56px;height:56px;line-height:56px;font-size:28px;margin-bottom:14px;">&#128400;</div>
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:-0.3px;">Fingerprint Login Verification</h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px;">BAGNOS MPC</p>
            </td>
          </tr>
          <tr>
            <td style="padding:32px 40px 0;">
              <p style="margin:0;font-size:15px;color:#666666;">Hello, <strong style="color:#333333;">{member.full_name}</strong></p>
              <p style="margin:10px 0 0;font-size:14px;color:#666666;line-height:1.6;">
                We received a request to enable <strong>Fingerprint Login</strong> on your account. Use the verification code below to confirm.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:28px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fdf9;border:1px solid #e8f5e9;border-radius:12px;padding:24px;">
                <tr>
                  <td style="text-align:center;">
                    <p style="margin:0 0 8px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8;">Your Verification Code</p>
                    <p style="margin:0;font-size:40px;font-weight:900;letter-spacing:10px;color:#ED1C24;">{otp_code}</p>
                    <p style="margin:12px 0 0;font-size:12px;color:#94a3b8;">Expires in 10 minutes</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 40px 32px;">
              <p style="margin:0;font-size:13px;color:#94a3b8;line-height:1.6;text-align:center;">
                If you did not request this, please ignore this email or contact support immediately.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return send_email_async(subject, plain_body, member.email, html_body=html_body)


def send_refund_request_notification(transaction, member, reason_type='other', reason_display=None):
    """
    Notify the admin/cashier via email when a member submits a refund request.

    Args:
        transaction: Transaction model instance
        member: Member model instance (the requester)
        reason_type: reason key from RefundReason.REASON_CHOICES
        reason_display: Human-readable reason label (optional)
    """
    from admin_panel.utils import get_admin_email
    from django.utils import timezone

    admin_email = get_admin_email()
    if not admin_email:
        logger.warning('send_refund_request_notification: no admin email configured, skipping.')
        return

    if not reason_display:
        reason_display = reason_type.replace('_', ' ').title()

    local_now = timezone.localtime(timezone.now())
    date_str = local_now.strftime('%B %d, %Y at %I:%M %p')

    subject = f'[Refund Request] {transaction.transaction_number} — {member.full_name}'

    plain_body = f"""Refund Request Notification
{'=' * 50}

A member has submitted a refund request and requires your review.

Transaction Details:
  Transaction No : {transaction.transaction_number}
  Member Name    : {member.full_name}
  RFID Card      : {member.rfid_card_number}
  Amount         : ₱{transaction.total_amount:,.2f}
  Payment Method : {transaction.get_payment_method_display()}
  Refund Reason  : {reason_display}

Requested On: {date_str}

{'=' * 50}
Please log in to the admin panel to review and process this refund:
http://127.0.0.1:8000/dashboard/transactions/

This notification was sent automatically by BAGNOS MPC.
"""

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Refund Request Notification</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f1f5f9;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#b91c1c 0%,#dc2626 60%,#ef4444 100%);padding:36px 40px;text-align:center;">
              <div style="display:inline-block;background:rgba(255,255,255,0.15);border-radius:50%;width:56px;height:56px;line-height:56px;font-size:28px;margin-bottom:14px;">&#8617;</div>
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:-0.3px;">Refund Request</h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:14px;">BAGNOS MPC — Action Required</p>
            </td>
          </tr>

          <!-- Intro -->
          <tr>
            <td style="padding:32px 40px 0;">
              <p style="margin:0;font-size:15px;color:#666666;">A member has submitted a refund request.</p>
              <p style="margin:10px 0 0;font-size:14px;color:#666666;line-height:1.6;">
                Please review the details below and approve or decline via the admin panel.
              </p>
            </td>
          </tr>

          <!-- Details card -->
          <tr>
            <td style="padding:24px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#fff5f5;border:1px solid #fecaca;border-radius:12px;padding:20px 24px;">
                <tr>
                  <td colspan="2" style="padding-bottom:12px;">
                    <span style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8;">Refund Details</span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Transaction No</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{transaction.transaction_number}</td>
                </tr>
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f5f5f5;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Member</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{member.full_name}</td>
                </tr>
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f5f5f5;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">RFID Card</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;text-align:right;">{member.rfid_card_number}</td>
                </tr>
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f5f5f5;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Amount</td>
                  <td style="padding:6px 0;color:#dc2626;font-size:16px;font-weight:700;text-align:right;">&#8369;{transaction.total_amount:,.2f}</td>
                </tr>
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f5f5f5;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Payment Method</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;text-align:right;">{transaction.get_payment_method_display()}</td>
                </tr>
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f5f5f5;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Reason</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{reason_display}</td>
                </tr>
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f5f5f5;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Requested On</td>
                  <td style="padding:6px 0;color:#666666;font-size:14px;text-align:right;">{date_str}</td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- CTA -->
          <tr>
            <td style="padding:28px 40px 0;text-align:center;">
              <a href="http://127.0.0.1:8000/dashboard/transactions/"
                 style="display:inline-block;background:linear-gradient(135deg,#b91c1c,#dc2626);color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;padding:14px 36px;border-radius:10px;letter-spacing:0.3px;">
                Review Refund Request
              </a>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:32px 40px;text-align:center;border-top:1px solid #f0f0f0;margin-top:28px;">
              <p style="margin:0;font-size:13px;color:#94a3b8;">This is an automated message from</p>
              <p style="margin:4px 0 0;font-size:14px;font-weight:700;color:#333333;">BAGNOS MPC</p>
              <p style="margin:12px 0 0;font-size:12px;color:#94a3b8;">&#169; 2026 BAGNOS MPC. All rights reserved.</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    logger.info(f'Sending refund request notification to admin ({admin_email}) for transaction {transaction.transaction_number}')
    return send_email_async(subject, plain_body.strip(), admin_email, html_body=html_body)


def send_refund_approval_email(transaction, member, refund_amount, balance_after, reason_display=None, is_partial=False, items_refunded=None):
    """
    Notify the member via email when their refund request has been approved.

    Args:
        transaction: Transaction model instance
        member: Member model instance (the requester)
        refund_amount: Decimal — amount credited back to the member's balance
        balance_after: Decimal — member's balance after the refund
        reason_display: Human-readable refund reason (optional)
        is_partial: bool — True if only some items were refunded
        items_refunded: list of TransactionItem objects that were refunded (optional)
    """
    from django.utils import timezone

    if not member or not getattr(member, 'email', None):
        logger.warning('send_refund_approval_email: member has no email, skipping.')
        return

    local_now = timezone.localtime(timezone.now())
    date_str = local_now.strftime('%B %d, %Y at %I:%M %p')

    refund_label = 'Partial Refund' if is_partial else 'Refund'
    subject = f'[{refund_label} Approved] Transaction {transaction.transaction_number}'

    # Build items block for plain text
    items_text = ''
    if items_refunded:
        lines = [f'  - {i.product_name} x{i.quantity} @ ₱{i.unit_price:,.2f} = ₱{i.total_price:,.2f}' for i in items_refunded]
        items_text = '\nItems Refunded:\n' + '\n'.join(lines) + '\n'

    reason_text = f'\n  Reason        : {reason_display}' if reason_display else ''

    plain_body = f"""Refund Approved
{'=' * 50}

Dear {member.full_name},

Your refund request has been approved and ₱{refund_amount:,.2f} has been credited to your card balance.

Transaction Details:
  Transaction No : {transaction.transaction_number}
  Refund Amount  : ₱{refund_amount:,.2f}{reason_text}
  New Balance    : ₱{balance_after:,.2f}
  Processed On   : {date_str}
{items_text}
{'=' * 50}
You can view your transaction history and updated balance in BAGNOS MPC.

Thank you for your patience.

Best regards,
BAGNOS MPC"""

    # Build items rows for HTML
    items_html = ''
    if items_refunded:
        rows = ''
        for item in items_refunded:
            rows += f"""
                <tr>
                  <td style="padding:5px 0;color:#333333;font-size:13px;">{item.product_name}</td>
                  <td style="padding:5px 0;color:#666666;font-size:13px;text-align:center;">x{item.quantity}</td>
                  <td style="padding:5px 0;color:#ED1C24;font-size:13px;font-weight:600;text-align:right;">&#8369;{item.total_price:,.2f}</td>
                </tr>"""
        items_html = f"""
          <tr>
            <td style="padding:20px 40px 0;">
              <p style="margin:0 0 10px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8;">Items Refunded</p>
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fdf9;border:1px solid #e8f5e9;border-radius:10px;padding:12px 16px;">
                <tr>
                  <th style="text-align:left;padding:4px 0;font-size:11px;color:#94a3b8;text-transform:uppercase;">Product</th>
                  <th style="text-align:center;padding:4px 0;font-size:11px;color:#94a3b8;text-transform:uppercase;">Qty</th>
                  <th style="text-align:right;padding:4px 0;font-size:11px;color:#94a3b8;text-transform:uppercase;">Total</th>
                </tr>{rows}
              </table>
            </td>
          </tr>"""

    reason_row = f"""
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Reason</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{reason_display}</td>
                </tr>""" if reason_display else ''

    partial_badge = ' <span style="background:#FEF7D5;color:#c2410c;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;vertical-align:middle;">PARTIAL</span>' if is_partial else ''

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Refund Approved</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f1f5f9;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#C4121A 0%,#ED1C24 60%,#8B0E14 100%);padding:36px 40px;text-align:center;">
              <div style="display:inline-block;background:rgba(255,255,255,0.15);border-radius:50%;width:56px;height:56px;line-height:56px;font-size:28px;margin-bottom:14px;">&#10003;</div>
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:-0.3px;">Refund Approved{partial_badge}</h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px;">BAGNOS MPC</p>
            </td>
          </tr>

          <!-- Greeting -->
          <tr>
            <td style="padding:32px 40px 0;">
              <p style="margin:0;font-size:15px;color:#666666;">Hello, <strong style="color:#333333;">{member.full_name}</strong></p>
              <p style="margin:10px 0 0;font-size:14px;color:#666666;line-height:1.6;">
                Great news! Your refund request has been <strong style="color:#ED1C24;">approved</strong>.
                The refund amount has been credited directly to your card balance.
              </p>
            </td>
          </tr>

          <!-- Details Card -->
          <tr>
            <td style="padding:24px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fdf9;border:1px solid #e8f5e9;border-radius:12px;padding:20px 24px;">
                <tr>
                  <td colspan="2" style="padding-bottom:12px;">
                    <span style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8;">Refund Details</span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Transaction No</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{transaction.transaction_number}</td>
                </tr>
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Refund Amount</td>
                  <td style="padding:6px 0;color:#ED1C24;font-size:16px;font-weight:700;text-align:right;">&#8369;{refund_amount:,.2f}</td>
                </tr>
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">New Card Balance</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">&#8369;{balance_after:,.2f}</td>
                </tr>{reason_row}
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Processed On</td>
                  <td style="padding:6px 0;color:#666666;font-size:14px;text-align:right;">{date_str}</td>
                </tr>
              </table>
            </td>
          </tr>
{items_html}
          <!-- Footer note -->
          <tr>
            <td style="padding:24px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:14px 18px;">
                <tr>
                  <td style="font-size:13px;color:#166534;line-height:1.6;">
                    &#128179; &nbsp;Your card balance has been updated. You can use your balance for your next purchase at any BAGNOS MPC terminal.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:32px 40px;text-align:center;border-top:1px solid #f0f0f0;margin-top:28px;">
              <p style="margin:0;font-size:13px;color:#94a3b8;">This is an automated message from</p>
              <p style="margin:4px 0 0;font-size:14px;font-weight:700;color:#333333;">BAGNOS MPC</p>
              <p style="margin:12px 0 0;font-size:12px;color:#94a3b8;">&#169; 2026 BAGNOS MPC. All rights reserved.</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    logger.info(f'Sending refund approval email to {member.email} for transaction {transaction.transaction_number}, amount ₱{refund_amount}')
    return send_email_async(subject, plain_body.strip(), member.email, html_body=html_body)


def send_welcome_member_email(member, store_name='BAGNOS MPC', added_by=None):
    """
    Send a welcome email to a newly registered member.

    Args:
        member: Member model instance (must have a valid email)
        store_name: Human-readable store / cooperative name (str)
        added_by: Username of the staff who created the account (str, optional)

    Returns:
        threading.Thread | None: Background thread, or None if member has no email.
    """
    from django.utils import timezone

    if not member or not getattr(member, 'email', None):
        logger.info('send_welcome_member_email: member has no email, skipping.')
        return None

    local_now = timezone.localtime(timezone.now())
    date_str = local_now.strftime('%B %d, %Y at %I:%M %p')

    subject = f'Welcome to {store_name}!'

    rfid_line = f'  RFID Card   : {member.rfid_card_number}' if member.rfid_card_number else ''
    username_line = f'  Username    : {member.username}' if member.username else ''
    added_by_line = f'  Added By    : {added_by}' if added_by else ''

    plain_body = f"""Welcome to {store_name}!
{'=' * 50}

Dear {member.full_name},

Your membership account has been successfully created. Here are your details:

  Full Name   : {member.full_name}
{username_line}
{rfid_line}
  Role        : {member.get_role_display()}
  Balance     : ₱{member.balance:,.2f}
  Member Since: {date_str}
{added_by_line}

You can now use your account at any {store_name} kiosk terminal.

If you have any questions or concerns, please contact our staff.

Thank you for joining us!

Best regards,
{store_name}
{'=' * 50}"""

    # Build optional detail rows for HTML
    rfid_row = f"""
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">RFID Card</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{member.rfid_card_number}</td>
                </tr>""" if member.rfid_card_number else ''

    username_row = f"""
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Username</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{member.username}</td>
                </tr>""" if member.username else ''

    added_by_row = f"""
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Registered By</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{added_by}</td>
                </tr>""" if added_by else ''

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Welcome to {store_name}</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f1f5f9;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#C4121A 0%,#ED1C24 60%,#8B0E14 100%);padding:36px 40px;text-align:center;">
              <div style="display:inline-block;background:rgba(255,255,255,0.15);border-radius:50%;width:64px;height:64px;line-height:64px;font-size:34px;margin-bottom:14px;">&#127881;</div>
              <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;letter-spacing:-0.3px;">Welcome to {store_name}!</h1>
              <p style="margin:8px 0 0;color:rgba(255,255,255,0.85);font-size:14px;">Your membership account is ready</p>
            </td>
          </tr>

          <!-- Greeting -->
          <tr>
            <td style="padding:32px 40px 0;">
              <p style="margin:0;font-size:15px;color:#666666;">Hello, <strong style="color:#333333;">{member.full_name}</strong>!</p>
              <p style="margin:10px 0 0;font-size:14px;color:#666666;line-height:1.7;">
                We are excited to have you as a member of <strong style="color:#ED1C24;">{store_name}</strong>.
                Your account has been successfully created and you can now enjoy the benefits of membership
                at any of our kiosk terminals.
              </p>
            </td>
          </tr>

          <!-- Membership Details Card -->
          <tr>
            <td style="padding:24px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fdf9;border:1px solid #e8f5e9;border-radius:12px;padding:20px 24px;">
                <tr>
                  <td colspan="2" style="padding-bottom:12px;">
                    <span style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8;">Your Membership Details</span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Full Name</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{member.full_name}</td>
                </tr>{username_row}{rfid_row}
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Role</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">{member.get_role_display()}</td>
                </tr>
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Card Balance</td>
                  <td style="padding:6px 0;color:#ED1C24;font-size:16px;font-weight:700;text-align:right;">&#8369;{member.balance:,.2f}</td>
                </tr>
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Member Since</td>
                  <td style="padding:6px 0;color:#666666;font-size:14px;text-align:right;">{date_str}</td>
                </tr>{added_by_row}
              </table>
            </td>
          </tr>

          <!-- Info note -->
          <tr>
            <td style="padding:24px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:14px 18px;">
                <tr>
                  <td style="font-size:13px;color:#166534;line-height:1.7;">
                    &#128179;&nbsp; You can use your <strong>RFID card</strong> or <strong>PIN</strong> at any kiosk terminal
                    to shop and manage your account. If you haven't received an RFID card yet, please visit
                    our staff at the counter.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:32px 40px;text-align:center;border-top:1px solid #f0f0f0;margin-top:28px;">
              <p style="margin:0;font-size:13px;color:#94a3b8;">This is an automated message from</p>
              <p style="margin:4px 0 0;font-size:14px;font-weight:700;color:#333333;">{store_name}</p>
              <p style="margin:12px 0 0;font-size:12px;color:#94a3b8;">&#169; 2026 {store_name}. All rights reserved.</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    logger.info(f'Sending welcome email to new member {member.full_name} <{member.email}>')
    return send_email_async(subject, plain_body.strip(), member.email, html_body=html_body)


def send_credit_payment_receipt_email(
    payment,
    settled_sales,
    member,
    performed_by_user=None,
    authorizing_member=None,
    receipt_url=None,
    settled_items=None,
):
    """
    Email the member (and admin) a receipt after outstanding credit is paid at the dashboard.
    """
    from django.utils import timezone
    from admin_panel.utils import get_admin_email

    local_now = timezone.localtime(payment.created_at)
    date_str = local_now.strftime('%B %d, %Y at %I:%M %p')
    method_label = payment.get_payment_method_display()
    performed_name = ''
    if performed_by_user:
        performed_name = performed_by_user.get_full_name() or performed_by_user.username

    sales_lines = []
    sales_rows_html = ''
    payment_lines = list(
        payment.payment_lines.select_related('item__transaction').order_by(
            'item__transaction__created_at', 'item__transaction_id', 'item_id'
        )
    )
    if payment_lines:
        for pline in payment_lines:
            item = pline.item
            txn = item.transaction
            applied = pline.amount_applied
            line = (
                f"  • {txn.transaction_number} — {item.product_name} "
                f"x{item.quantity} — ₱{applied:,.2f}"
            )
            sales_lines.append(line)
            sales_rows_html += f"""
                <tr>
                  <td style="padding:5px 0;color:#333333;font-size:13px;">{txn.transaction_number}<br><small>{item.product_name} x{item.quantity}</small></td>
                  <td style="padding:5px 0;color:#666666;font-size:13px;text-align:center;">{timezone.localtime(txn.created_at).strftime('%b %d, %Y')}</td>
                  <td style="padding:5px 0;color:#5b21b6;font-size:13px;font-weight:600;text-align:right;">&#8369;{applied:,.2f}</td>
                </tr>"""
    elif settled_items:
        for item in settled_items:
            txn = item.transaction
            line = (
                f"  • {txn.transaction_number} — {item.product_name} "
                f"x{item.quantity} — ₱{item.credit_line_amount:,.2f}"
            )
            sales_lines.append(line)
            sales_rows_html += f"""
                <tr>
                  <td style="padding:5px 0;color:#333333;font-size:13px;">{txn.transaction_number}<br><small>{item.product_name} x{item.quantity}</small></td>
                  <td style="padding:5px 0;color:#666666;font-size:13px;text-align:center;">{timezone.localtime(txn.created_at).strftime('%b %d, %Y')}</td>
                  <td style="padding:5px 0;color:#5b21b6;font-size:13px;font-weight:600;text-align:right;">&#8369;{item.credit_line_amount:,.2f}</td>
                </tr>"""
    else:
        for sale in settled_sales:
            line = (
                f"  • {sale.transaction_number} — ₱{sale.total_amount:,.2f} "
                f"({timezone.localtime(sale.created_at).strftime('%b %d, %Y')})"
            )
            sales_lines.append(line)
            sales_rows_html += f"""
                <tr>
                  <td style="padding:5px 0;color:#333333;font-size:13px;">{sale.transaction_number}</td>
                  <td style="padding:5px 0;color:#666666;font-size:13px;text-align:center;">{timezone.localtime(sale.created_at).strftime('%b %d, %Y')}</td>
                  <td style="padding:5px 0;color:#5b21b6;font-size:13px;font-weight:600;text-align:right;">&#8369;{sale.total_amount:,.2f}</td>
                </tr>"""

    sales_block = '\n'.join(sales_lines) if sales_lines else '  (none)'
    balance_block = ''
    balance_html = ''
    if payment.payment_method == 'debit' and payment.balance_before is not None:
        balance_block = (
            f"\n  Balance Before : ₱{payment.balance_before:,.2f}\n"
            f"  Balance After  : ₱{payment.balance_after:,.2f}\n"
        )
        balance_html = f"""
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f0f0f0;margin:4px 0;"/></td></tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Balance before</td>
                  <td style="padding:6px 0;color:#333333;font-size:14px;font-weight:600;text-align:right;">&#8369;{payment.balance_before:,.2f}</td>
                </tr>
                <tr>
                  <td style="padding:6px 0;color:#666666;font-size:14px;">Balance after</td>
                  <td style="padding:6px 0;color:#ED1C24;font-size:14px;font-weight:700;text-align:right;">&#8369;{payment.balance_after:,.2f}</td>
                </tr>"""

    pin_block = ''
    if authorizing_member:
        pin_block = (
            f"\nPIN Authorised By: {authorizing_member.full_name} "
            f"({authorizing_member.get_role_display()})\n"
        )

    receipt_line = f"\nView receipt: {receipt_url}\n" if receipt_url else ''
    subject = f'[Credit Paid] {payment.settlement_number} — ₱{payment.amount_paid:,.2f}'

    plain_body = f"""Credit Payment Receipt
{'=' * 50}

Dear {member.full_name},

Your outstanding credit (utang) has been paid. Thank you!

Settlement Details:
  Settlement No. : {payment.settlement_number}
  Amount Paid    : ₱{payment.amount_paid:,.2f}
  Payment Method : {method_label}
  Processed On   : {date_str}
  Processed By   : {performed_name or 'Staff'}
{pin_block}{balance_block}
Credit Sales Settled:
{sales_block}
{receipt_line}
{'=' * 50}
BAGNOS MPC"""

    html_body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/><title>Credit Payment Receipt</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08);">
<tr><td style="background:linear-gradient(135deg,#5b21b6,#7c3aed);padding:28px 40px;">
  <h1 style="margin:0;color:#fff;font-size:22px;">Credit Payment Receipt</h1>
  <p style="margin:8px 0 0;color:#e9d5ff;font-size:14px;">Outstanding utang settled</p>
</td></tr>
<tr><td style="padding:28px 40px;">
  <p style="margin:0 0 16px;color:#334155;font-size:15px;">Hi <strong>{member.full_name}</strong>,</p>
  <p style="margin:0 0 20px;color:#64748b;font-size:14px;">We received your credit payment. The following credit sales are now marked as paid.</p>
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f3ff;border:1px solid #ddd6fe;border-radius:10px;padding:16px 20px;">
    <tr><td style="padding:6px 0;color:#666;font-size:14px;">Settlement #</td>
        <td style="padding:6px 0;color:#5b21b6;font-size:14px;font-weight:700;text-align:right;">{payment.settlement_number}</td></tr>
    <tr><td style="padding:6px 0;color:#666;font-size:14px;">Amount paid</td>
        <td style="padding:6px 0;color:#5b21b6;font-size:18px;font-weight:700;text-align:right;">&#8369;{payment.amount_paid:,.2f}</td></tr>
    <tr><td style="padding:6px 0;color:#666;font-size:14px;">Payment method</td>
        <td style="padding:6px 0;color:#333;font-size:14px;font-weight:600;text-align:right;">{method_label}</td></tr>
    <tr><td style="padding:6px 0;color:#666;font-size:14px;">Date</td>
        <td style="padding:6px 0;color:#333;font-size:14px;text-align:right;">{date_str}</td></tr>
    {balance_html}
  </table>
  <p style="margin:24px 0 10px;font-size:12px;font-weight:700;text-transform:uppercase;color:#94a3b8;">Settled credit sales</p>
  <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:8px;">
    <tr style="background:#f8fafc;">
      <th style="text-align:left;padding:8px 12px;font-size:11px;color:#94a3b8;">Txn #</th>
      <th style="text-align:center;padding:8px 12px;font-size:11px;color:#94a3b8;">Date</th>
      <th style="text-align:right;padding:8px 12px;font-size:11px;color:#94a3b8;">Amount</th>
    </tr>{sales_rows_html}
  </table>
  {'<p style="margin:20px 0 0;"><a href="' + receipt_url + '" style="display:inline-block;background:#5b21b6;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;">View printable receipt</a></p>' if receipt_url else ''}
</td></tr>
</table></td></tr></table></body></html>"""

    threads = []
    if member.email:
        threads.append(
            send_email_async(
                subject,
                plain_body.strip(),
                member.email,
                html_body=html_body,
            )
        )

    admin_email = get_admin_email()
    if admin_email:
        admin_subject = f'[Credit Payment] {member.full_name} — {payment.settlement_number}'
        admin_plain = f"""Credit Payment Recorded
{'=' * 45}

Member: {member.full_name}
Settlement: {payment.settlement_number}
Amount: ₱{payment.amount_paid:,.2f}
Method: {method_label}
Processed by: {performed_name or 'Staff'}
{pin_block}
Sales settled:
{sales_block}
{receipt_line}"""
        threads.append(
            send_email_async(admin_subject, admin_plain.strip(), admin_email, html_body=html_body)
        )

    return threads
