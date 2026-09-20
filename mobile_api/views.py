from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from django.contrib.auth import login
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.contrib.sessions.models import Session
from django.db.models import F
import json
import logging
from datetime import timedelta
from decimal import Decimal
import time

logger = logging.getLogger(__name__)

from members.models import Member, BalanceTransaction, SegmentProductGroupDiscount
from transactions.models import Transaction
from inventory.models import Product, Category
from inventory.pricing import discounts_by_product_ids, price_payload_for_product
from .models import FundTransferOTP, BiometricEnrollOTP, MemberQRCode, QRFeatureSettings
from .serializers import (
    MemberSerializer, TransactionSerializer, 
    BalanceTransactionSerializer, AccountSummarySerializer,
    FundTransferSerializer
)
from .email_utils import send_otp_email, send_transfer_completion_emails, send_biometric_otp_email
from helper.cookie_helper import set_secure_cookie



class MobileSessionAuthentication(SessionAuthentication):
    """
    Custom session authentication that doesn't enforce CSRF for mobile API endpoints.
    This allows mobile apps to use session-based authentication without CSRF tokens.
    """
    def enforce_csrf(self, request):
        # Don't enforce CSRF for mobile API endpoints
        return


class MobileMemberPermission(BasePermission):
    """
    Custom permission that allows both authenticated users and session-based members
    (members without username who logged in via RFID + PIN)
    """
    def has_permission(self, request, view):
        # Check if user is authenticated (has username)
        if request.user and request.user.is_authenticated:
            return True
        
        # Check if member is authenticated via session (no username)
        if request.session.get('member_id'):
            try:
                member = Member.objects.get(
                    id=request.session['member_id'],
                    is_active=True
                )
                return True
            except Member.DoesNotExist:
                return False
        
        return False


def get_member_from_request(request):
    """
    Helper function to get member from request.
    Supports both authenticated users and session-based members.
    Returns (member, error_response) tuple.
    """
    member = None
    
    # First, try to get member from authenticated user
    if request.user and request.user.is_authenticated:
        try:
            member = Member.objects.get(user=request.user, is_active=True)
        except Member.DoesNotExist:
            return None, Response(
                {'success': False, 'error': 'Member account not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Member.MultipleObjectsReturned:
            member = Member.objects.filter(user=request.user, is_active=True).first()
            if not member:
                return None, Response(
                    {'success': False, 'error': 'Member account not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
    
    # If no user, try to get member from session (for members without username)
    if not member and request.session.get('member_id'):
        try:
            member = Member.objects.get(
                id=request.session['member_id'],
                is_active=True
            )
        except Member.DoesNotExist:
            return None, Response(
                {'success': False, 'error': 'Member account not found or session expired'},
                status=status.HTTP_401_UNAUTHORIZED
            )
    
    if not member:
        return None, Response(
            {'success': False, 'error': 'Authentication required'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    return member, None


@csrf_exempt
@require_http_methods(["POST"])
def mobile_logout(request):
    """
    Logout endpoint for mobile app.
    Flushes the server-side session so the session cookie is invalidated.
    """
    try:
        request.session.flush()
    except Exception:
        pass
    return JsonResponse({'success': True, 'message': 'Logged out successfully'})


@csrf_exempt
@require_http_methods(["POST"])
def mobile_login(request):
    """
    Enhanced login endpoint for mobile app using username and PIN
    Expected JSON: {"username": "john_doe", "pin": "1234"}
    For members with role "member" without username, can use RFID + PIN: {"rfid": "123456", "pin": "1234"}
    Returns: JSON response with member info and session
    """
    try:
        # Parse JSON body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {'success': False, 'error': 'Invalid JSON format'},
                status=400
            )
        
        username = data.get('username', '').strip()
        pin = data.get('pin', '').strip()
        rfid = data.get('rfid', '').strip()  # Alternative identifier for members without username
        
        if not pin:
            return JsonResponse(
                {'success': False, 'error': 'PIN is required'},
                status=400
            )
        
        # Validate PIN format (should be 4 digits)
        if not pin.isdigit() or len(pin) != 4:
            return JsonResponse(
                {'success': False, 'error': 'PIN must be exactly 4 digits'},
                status=400
            )
        
        member = None
        
        # If username is provided, try to find member by username
        if username:
            from django.contrib.auth.models import User as DjangoUser

            # First try: look up by Django User username → linked Member
            user = None
            try:
                user = DjangoUser.objects.get(username=username, is_active=True)
            except DjangoUser.DoesNotExist:
                pass
            except DjangoUser.MultipleObjectsReturned:
                user = DjangoUser.objects.filter(username=username, is_active=True).first()

            if user:
                try:
                    member = Member.objects.get(user=user, is_active=True)
                except Member.DoesNotExist:
                    member = None
                except Member.MultipleObjectsReturned:
                    member = Member.objects.filter(user=user, is_active=True).first()

            # Second try: look up directly by Member.username field (as shown in admin)
            if member is None:
                try:
                    member = Member.objects.get(username=username, is_active=True)
                except Member.DoesNotExist:
                    member = None
                except Member.MultipleObjectsReturned:
                    member = Member.objects.filter(username=username, is_active=True).first()

            if member is None:
                return JsonResponse(
                    {'success': False, 'error': 'Invalid username or PIN. Please check your credentials and try again.'},
                    status=401
                )
        # If no username but RFID is provided, try to find member by RFID (for members without username)
        elif rfid:
            try:
                member = Member.objects.get(rfid_card_number=rfid, is_active=True)
                # Only allow this for members with role "member" who don't have a username
                if member.role != 'member':
                    return JsonResponse(
                        {'success': False, 'error': 'RFID login is only allowed for members with role "member"'},
                        status=403
                    )
                if member.user is not None and member.user.username:
                    return JsonResponse(
                        {'success': False, 'error': 'Please use username to login'},
                        status=400
                    )
            except Member.DoesNotExist:
                return JsonResponse(
                    {'success': False, 'error': 'Member not found or account is inactive'},
                    status=404
                )
        else:
            return JsonResponse(
                {'success': False, 'error': 'Username or RFID is required'},
                status=400
            )
        
        # Check if account is locked due to too many failed PIN attempts
        if member.is_pin_locked:
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Account locked due to too many failed PIN attempts. Please contact the administrator to unlock your account.',
                    'locked': True,
                },
                status=403
            )

        # Verify PIN with enhanced error handling
        try:
            if not member.check_pin(pin):
                # Increment failed attempt counter
                member.pin_attempts = (member.pin_attempts or 0) + 1
                MAX_PIN_ATTEMPTS = 5
                remaining = MAX_PIN_ATTEMPTS - member.pin_attempts
                if member.pin_attempts >= MAX_PIN_ATTEMPTS:
                    member.is_pin_locked = True
                    member.save(update_fields=['pin_attempts', 'is_pin_locked'])
                    # Notify all admin users by email
                    try:
                        from django.contrib.auth.models import User as DjangoUser
                        from django.core.mail import send_mail
                        from django.conf import settings
                        admin_emails = list(
                            DjangoUser.objects.filter(is_staff=True, is_active=True)
                            .exclude(email='')
                            .values_list('email', flat=True)
                        )
                        if admin_emails:
                            from admin_panel.models import KioskConfig

                            send_mail(
                                subject=(
                                    f'[{KioskConfig.get().brand_title_short()}] '
                                    f'Account Locked: {member.full_name}'
                                ),
                                message=(
                                    f'The account for {member.full_name} ({getattr(member.user, "username", member.rfid_card_number)}) '
                                    f'has been locked after {MAX_PIN_ATTEMPTS} failed PIN attempts.\n\n'
                                    f'Please log in to the admin panel to reset their PIN attempts and unlock the account.'
                                ),
                                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'BAGNOS MPC <noreply@bagnosmpc.local>'),
                                recipient_list=admin_emails,
                                fail_silently=True,
                            )
                    except Exception:
                        pass  # Email failure must never block the response
                    return JsonResponse(
                        {
                            'success': False,
                            'error': 'Account locked due to too many failed PIN attempts. Please contact the administrator to unlock your account.',
                            'locked': True,
                        },
                        status=403
                    )
                else:
                    member.save(update_fields=['pin_attempts'])
                    return JsonResponse(
                        {
                            'success': False,
                            'error': f'Invalid PIN. {remaining} attempt{"s" if remaining != 1 else ""} remaining before account is locked.',
                            'attempts_remaining': remaining,
                        },
                        status=401
                    )
        except AttributeError:
            # Member doesn't have PIN set
            return JsonResponse(
                {'success': False, 'error': 'PIN not set for this account. Please contact administrator.'},
                status=400
            )
        except Exception as e:
            import traceback
            print(f"PIN verification error: {str(e)}")
            print(traceback.format_exc())
            return JsonResponse(
                {'success': False, 'error': 'Error verifying PIN. Please try again later.'},
                status=500
            )

        # Reset failed attempt counter on successful PIN verification
        if member.pin_attempts > 0:
            member.pin_attempts = 0
            member.save(update_fields=['pin_attempts'])
        
        # For members without a linked Django user, allow session-based login
        if member.user is None or not getattr(member.user, 'username', None):
            # Ensure session exists and is saved
            if not request.session.session_key:
                request.session.create()
            
            # Store member info in session for members without username
            request.session['member_id'] = member.id
            request.session['member_rfid'] = member.rfid_card_number
            request.session['member_role'] = member.role
            request.session.save()  # Explicitly save session
            
            # Serialize member data
            serializer = MemberSerializer(member)
            
            # Return success response with member info
            response = JsonResponse({
                'success': True,
                'member': serializer.data,
                'message': f'Welcome back, {member.full_name}!',
                'session_id': request.session.session_key
            }, status=200)
            
            # Set session cookie in response with enhanced settings
            if request.session.session_key:
                set_secure_cookie(
                    response,
                    'sessionid',
                    request.session.session_key,
                    max_age=60 * 60 * 24 * 7,  # 7 days
                    samesite='Strict',
                    secure=True,
                    httponly=True,
                )
            
            # Add connection-friendly headers
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            
            return response
        
        # Authenticate and login the user (for members with username)
        if member.user is None:
            return JsonResponse(
                {'success': False, 'error': 'User account not found'},
                status=404
            )
        
        try:
            login(request, member.user)
            # Keep member metadata in session for downstream dashboards/telemetry.
            request.session['member_id'] = member.id
            request.session['member_rfid'] = member.rfid_card_number
            request.session['member_role'] = member.role
            # Ensure session is saved
            request.session.save()
        except Exception as e:
            import traceback
            print(f"Login error: {str(e)}")
            print(traceback.format_exc())
            return JsonResponse(
                {'success': False, 'error': 'Authentication failed. Please try again.'},
                status=500
            )
        
        # Serialize member data
        serializer = MemberSerializer(member)
        
        # Return success response with member info
        response = JsonResponse({
            'success': True,
            'member': serializer.data,
            'message': f'Welcome back, {member.full_name}!',
            'session_id': request.session.session_key
        }, status=200)
        
        # Set session cookie in response with enhanced settings
        if request.session.session_key:
            set_secure_cookie(
                response,
                'sessionid',
                request.session.session_key,
                max_age=60 * 60 * 24 * 7,  # 7 days
                samesite='Strict',
                secure=True,
                httponly=True,
            )
        
        # Add connection-friendly headers
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        
        return response
        
    except Exception as e:
        # Log the error for debugging (in production, use proper logging)
        import traceback
        print(f"Mobile login error: {str(e)}")
        print(traceback.format_exc())
        
        return JsonResponse(
            {'success': False, 'error': 'An unexpected error occurred. Please try again later.'},
            status=500
        )


@api_view(['GET'])
@permission_classes([MobileMemberPermission])
def account_info(request):
    """
    Get current member's account information
    Requires authentication (user or session-based)
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response
    
    serializer = MemberSerializer(member)
    response = Response({
        'success': True,
        'member': serializer.data
    })
    
    # Add connection-friendly headers
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    
    return response


@api_view(['GET'])
@permission_classes([MobileMemberPermission])
def account_summary(request):
    """
    Get comprehensive account summary including recent transactions
    Query params: year (default current year), month (default current month, 1-12)
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response
    
    # Get recent transactions (last 10) - optimized with select_related
    recent_transactions = Transaction.objects.filter(
        member=member,
        status='completed'
    ).select_related('member').prefetch_related('items').order_by('-created_at')[:10]
    
    # Get recent balance transactions (last 10)
    recent_balance_transactions = member.balance_transactions.all().order_by('-created_at')[:10]
    
    # Get month/year from query params or use current month/year
    now = timezone.now()
    year = int(request.query_params.get('year', now.year))
    month = int(request.query_params.get('month', now.month))
    
    # Validate month
    if month < 1 or month > 12:
        month = now.month
    
    # Calculate monthly totals for selected month
    start_of_month = timezone.datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.get_current_timezone())
    # Calculate end of month
    if month == 12:
        end_of_month = timezone.datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.get_current_timezone())
    else:
        end_of_month = timezone.datetime(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.get_current_timezone())
    
    # Optimize monthly transactions query
    monthly_transactions = Transaction.objects.filter(
        member=member,
        status='completed',
        created_at__gte=start_of_month,
        created_at__lt=end_of_month
    ).select_related('member')
    
    total_spent_this_month = sum(t.total_amount for t in monthly_transactions)
    
    data = {
        'member': MemberSerializer(member).data,
        'recent_transactions': TransactionSerializer(recent_transactions, many=True).data,
        'recent_balance_transactions': BalanceTransactionSerializer(recent_balance_transactions, many=True).data,
        'total_spent_this_month': str(total_spent_this_month),
        'selected_year': year,
        'selected_month': month
    }
    
    response = Response({
        'success': True,
        'summary': data
    })
    
    # Add connection-friendly headers
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    
    return response


@api_view(['GET'])
@permission_classes([MobileMemberPermission])
def transaction_history(request):
    """
    Get transaction history with pagination
    Query params: page (default 1), limit (default 20)
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response
    
    page = int(request.query_params.get('page', 1))
    limit = int(request.query_params.get('limit', 20))
    offset = (page - 1) * limit
    
    # Optimize query with select_related to reduce database hits
    VISIBLE_STATUSES = ['completed', 'refund_requested', 'refunded', 'return_window', 'return_expired']
    transactions = Transaction.objects.filter(
        member=member,
        status__in=VISIBLE_STATUSES
    ).select_related('member').prefetch_related('items', 'return_window').order_by('-created_at')[offset:offset + limit]
    
    total = Transaction.objects.filter(member=member, status__in=VISIBLE_STATUSES).count()
    
    from admin_panel.models import ReportScheduleConfig
    _refund_config = ReportScheduleConfig.get()

    serializer = TransactionSerializer(transactions, many=True)
    response = Response({
        'success': True,
        'transactions': serializer.data,
        'refund_window_days': _refund_config.refund_window_days,
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'has_next': offset + limit < total,
            'has_previous': page > 1
        }
    })
    
    # Add connection-friendly headers
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    
    return response


@api_view(['GET'])
@permission_classes([MobileMemberPermission])
def balance_transactions(request):
    """
    Get balance transaction history (deposits, deductions)
    Query params: page (default 1), limit (default 20)
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response
    
    page = int(request.query_params.get('page', 1))
    limit = int(request.query_params.get('limit', 20))
    offset = (page - 1) * limit
    
    balance_transactions = member.balance_transactions.all().order_by('-created_at')[offset:offset + limit]
    total = member.balance_transactions.count()
    
    serializer = BalanceTransactionSerializer(balance_transactions, many=True)
    response = Response({
        'success': True,
        'balance_transactions': serializer.data,
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'has_next': offset + limit < total,
            'has_previous': page > 1
        }
    })
    
    # Add connection-friendly headers
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    
    return response


@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """
    Health check endpoint for connection testing
    Returns server status and basic info
    """
    try:
        # Test database connection
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        
        response = JsonResponse({
            'success': True,
            'status': 'healthy',
            'timestamp': timezone.now().isoformat(),
            'server_time': int(time.time()),
            'message': 'Server is running and database is accessible'
        }, status=200)
        
        # Add connection-friendly headers
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        
        return response
    except Exception as e:
        return JsonResponse({
            'success': False,
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=503)


@api_view(['GET'])
@permission_classes([AllowAny])
def store_info(request):
    """
    Public endpoint – returns the store profile configured via Django admin.
    Used by the mobile app Settings screen to display store details.
    """
    from admin_panel.models import KioskConfig, StoreProfile
    profile = StoreProfile.get()
    kiosk = KioskConfig.get()
    logo_url = ''
    logo_path = ''
    logo_cache_key = 0
    if profile.logo:
        logo_path = profile.logo.url
        logo_url = request.build_absolute_uri(profile.logo.url)
        try:
            logo_cache_key = int(profile.updated_at.timestamp())
        except Exception:
            logo_cache_key = 0
    return JsonResponse({
        'success': True,
        'store': {
            'store_name': profile.store_name,
            'show_store_name': profile.show_store_name,
            'branch_name': profile.branch_name,
            'address_line1': profile.address_line1,
            'address_line2': profile.address_line2,
            'city': profile.city,
            'province': profile.province,
            'zip_code': profile.zip_code,
            'contact_number': profile.contact_number,
            'alt_contact_number': profile.alt_contact_number,
            'email': profile.email,
            'website': profile.website,
            'business_hours': profile.business_hours,
            'tagline': profile.tagline,
            'maps_url': profile.maps_url,
            'latitude': float(profile.latitude) if profile.latitude is not None else None,
            'longitude': float(profile.longitude) if profile.longitude is not None else None,
            'system_name': kiosk.system_name,
            'kiosk_tagline': kiosk.tagline,
            'logo_url': logo_url,
            'logo_path': logo_path,
            'logo_cache_key': logo_cache_key,
        }
    })


def _get_active_cashier_queue_snapshot(now):
    """
    Return active cashier IDs/names/phones for checkout queue context only.
    We intentionally ignore generic authenticated sessions to avoid false positives.
    """
    active_sessions = Session.objects.filter(expire_date__gte=now)
    active_cashier_ids = set()
    active_cashier_names = []
    active_cashier_phones = []

    for session in active_sessions.iterator():
        try:
            data = session.get_decoded()
        except Exception:
            continue

        # Primary signal: member_role explicitly marked as cashier in session.
        session_role = (data.get('member_role') or '').strip().lower()
        if session_role == 'cashier':
            session_member_id = data.get('member_id')
            if session_member_id:
                cashier_member = (
                    Member.objects
                    .filter(id=session_member_id, is_active=True, member_role__slug='cashier')
                    .first()
                )
            else:
                cashier_member = None

            if cashier_member and cashier_member.id not in active_cashier_ids:
                active_cashier_ids.add(cashier_member.id)
                active_cashier_names.append(cashier_member.full_name)
                active_cashier_phones.append((cashier_member.phone or '').strip() or None)
            continue

        # Secondary signal: authenticated Django user session tied to a cashier Member.
        # Linked-user logins may only store auth_user_id in session.
        auth_user_id = data.get('_auth_user_id')
        if auth_user_id:
            cashier_member = (
                Member.objects
                .filter(user_id=auth_user_id, is_active=True, member_role__slug='cashier')
                .first()
            )
            if cashier_member and cashier_member.id not in active_cashier_ids:
                active_cashier_ids.add(cashier_member.id)
                active_cashier_names.append(cashier_member.full_name)
                active_cashier_phones.append((cashier_member.phone or '').strip() or None)
                continue

        # Tertiary signal: active kiosk checkout session assigned to a cashier.
        kiosk_member_id = data.get('kiosk_member_id')
        if kiosk_member_id:
            cashier_member = (
                Member.objects
                .filter(id=kiosk_member_id, is_active=True, member_role__slug='cashier')
                .first()
            )
            if cashier_member and cashier_member.id not in active_cashier_ids:
                active_cashier_ids.add(cashier_member.id)
                active_cashier_names.append(cashier_member.full_name)
                active_cashier_phones.append((cashier_member.phone or '').strip() or None)

    return active_cashier_ids, active_cashier_names, active_cashier_phones


@api_view(['GET'])
@permission_classes([MobileMemberPermission])
def admin_checkout_queue_status(request):
    """
    Admin-only endpoint for checkout queue status in mobile dashboard.
    Builds active cashier status from non-expired Django sessions.
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response

    if member.role != 'admin':
        return JsonResponse(
            {'success': False, 'error': 'Admin access required.'},
            status=403
        )

    now = timezone.now()
    active_cashier_ids, active_cashier_names, active_cashier_phones = _get_active_cashier_queue_snapshot(now)

    active_count = len(active_cashier_ids)
    primary_cashier_name = active_cashier_names[0] if active_cashier_names else None
    primary_cashier_phone = active_cashier_phones[0] if active_cashier_phones else None

    cashier_shift_status = (
        f'{active_count} cashier active in checkout queue'
        if active_count > 0
        else 'No active cashier in checkout queue'
    )
    queue_status = (
        'Queue is being served'
        if active_count > 0
        else 'Queue waiting for cashier login'
    )

    return JsonResponse({
        'success': True,
        'checkout_queue': {
            'active_cashier_login_count': active_count,
            'active_cashier_name': primary_cashier_name,
            'assigned_mobile': primary_cashier_phone,
            'cashier_shift_status': cashier_shift_status,
            'queue_status': queue_status,
            'as_of': now.isoformat(),
        }
    })


@api_view(['GET'])
@permission_classes([MobileMemberPermission])
def admin_important_details(request):
    """
    Admin-only endpoint for the Important Details section in mobile dashboard.
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response

    if member.role != 'admin':
        return JsonResponse(
            {'success': False, 'error': 'Admin access required.'},
            status=403
        )

    now = timezone.now()
    active_cashier_ids, active_cashier_names, active_cashier_phones = _get_active_cashier_queue_snapshot(now)

    active_count = len(active_cashier_ids)
    primary_cashier_name = active_cashier_names[0] if active_cashier_names else None
    primary_cashier_phone = active_cashier_phones[0] if active_cashier_phones else None

    cashier_shift_status = (
        f'{active_count} cashier active in checkout queue'
        if active_count > 0
        else 'No active cashier in checkout queue'
    )
    queue_status = (
        'Queue is being served'
        if active_count > 0
        else 'Queue waiting for cashier login'
    )

    return JsonResponse({
        'success': True,
        'important_details': {
            'active_cashier_login_count': active_count,
            'active_cashier_name': primary_cashier_name,
            'assigned_mobile': primary_cashier_phone,
            'cashier_shift_status': cashier_shift_status,
            'queue_status': queue_status,
            'as_of': now.isoformat(),
        }
    })


@api_view(['GET'])
@permission_classes([MobileMemberPermission])
def admin_operational_watchlist(request):
    """
    Admin-only endpoint for operational watchlist cards in mobile dashboard.
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response

    if member.role != 'admin':
        return JsonResponse(
            {'success': False, 'error': 'Admin access required.'},
            status=403
        )

    pending_approvals = Transaction.objects.filter(status='refund_requested').count()
    flagged_transactions = Transaction.objects.filter(
        status__in=['return_window', 'return_expired']
    ).count()
    low_stock_items = Product.objects.filter(
        is_active=True,
        stock_quantity__lte=F('low_stock_threshold'),
        stock_quantity__gt=0
    ).count()

    return JsonResponse({
        'success': True,
        'watchlist': {
            'pending_approvals': pending_approvals,
            'flagged_transactions': flagged_transactions,
            'low_stock_items': low_stock_items,
            'as_of': timezone.now().isoformat(),
        }
    })


@api_view(['GET'])
@permission_classes([MobileMemberPermission])
def search_member(request):
    """
    Search for a member by RFID card number or by name.
    Query params:
      - rfid: exact RFID match (legacy, backward-compatible)
      - query: RFID exact match first, then first/last name search if no RFID hit
    Returns:
      { success, member }   – single result (RFID match)
      { success, members }  – list of results (name search)
    """
    from django.db.models import Q as DQ
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response

    rfid        = request.query_params.get('rfid', '').strip()
    query       = request.query_params.get('query', '').strip()
    search_term = rfid or query

    if not search_term:
        return Response(
            {'success': False, 'error': 'RFID card number or name is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ── 1. Try exact RFID match first ──────────────────────────────────────
    try:
        recipient = Member.objects.get(rfid_card_number=search_term, is_active=True)
        if recipient.id == member.id:
            return Response(
                {'success': False, 'error': 'Cannot transfer funds to yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = MemberSerializer(recipient)
        return Response({'success': True, 'member': serializer.data})
    except Member.DoesNotExist:
        pass

    # If caller used the legacy 'rfid' param, do not fall back to name search
    if rfid:
        return Response(
            {'success': False, 'error': 'Member not found with the provided RFID card number'},
            status=status.HTTP_404_NOT_FOUND
        )

    # ── 2. Name search (first_name / last_name contains query) ─────────────
    # Split query into tokens so "Vincent Haber" matches first_name=Vincent, last_name=Haber
    tokens = search_term.split()
    name_filter = DQ()
    for token in tokens:
        name_filter &= (DQ(first_name__icontains=token) | DQ(last_name__icontains=token))

    recipients = (
        Member.objects
        .filter(name_filter, is_active=True)
        .exclude(id=member.id)
        .order_by('first_name', 'last_name')[:10]
    )

    if not recipients:
        return Response(
            {'success': False, 'error': 'No member found matching your search'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = MemberSerializer(recipients, many=True)
    return Response({'success': True, 'members': serializer.data})


@csrf_exempt
@api_view(['POST'])
@authentication_classes([MobileSessionAuthentication])
@permission_classes([MobileMemberPermission])
def request_transfer_otp(request):
    """
    Request OTP for fund transfer - sends OTP via email
    Expected JSON: {"recipient_rfid": "123456", "amount": "100.00", "notes": "Optional note"}
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response
    
    # Validate request data
    serializer = FundTransferSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {'success': False, 'error': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    recipient_rfid = serializer.validated_data['recipient_rfid'].strip()
    amount = Decimal(str(serializer.validated_data['amount']))
    notes = serializer.validated_data.get('notes', '').strip()
    
    # Validate amount
    if amount <= 0:
        return Response(
            {'success': False, 'error': 'Transfer amount must be greater than zero'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Check if member has sufficient balance
    if member.balance < amount:
        return Response(
            {'success': False, 'error': 'Insufficient balance'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Check if member has email
    if not member.email:
        return Response(
            {'success': False, 'error': 'Email address is required for OTP verification. Please update your profile.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Find recipient
    try:
        recipient = Member.objects.get(rfid_card_number=recipient_rfid, is_active=True)
    except Member.DoesNotExist:
        return Response(
            {'success': False, 'error': 'Recipient member not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Don't allow transferring to self
    if recipient.id == member.id:
        return Response(
            {'success': False, 'error': 'Cannot transfer funds to yourself'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    from helper.database_helper import create_fund_transfer_otp

    result = create_fund_transfer_otp(member.id, recipient_rfid, amount, notes)
    if not result.success:
        logger.error("request_transfer_otp: %s", result.error)
        return Response(
            {'success': False, 'error': 'Failed to create OTP. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    otp = result.data['otp']

    # Send OTP via email asynchronously (non-blocking)
    send_otp_email(member, recipient, otp.otp_code, amount, notes)

    return Response({
        'success': True,
        'message': f'OTP has been sent to your email ({member.email}). Please check your inbox.',
        'expires_in': 600,  # 10 minutes in seconds
    })


@csrf_exempt
@api_view(['POST'])
@authentication_classes([MobileSessionAuthentication])
@permission_classes([MobileMemberPermission])
def verify_transfer_otp(request):
    """
    Verify OTP and complete fund transfer
    Expected JSON: {"otp_code": "123456"}
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response

    otp_code = request.data.get('otp_code', '').strip()

    if not otp_code:
        return Response(
            {'success': False, 'error': 'OTP code is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Find valid OTP
    try:
        otp = FundTransferOTP.objects.get(
            member=member,
            otp_code=otp_code,
            is_used=False
        )
    except FundTransferOTP.DoesNotExist:
        return Response(
            {'success': False, 'error': 'Invalid or expired OTP code'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Check if OTP is still valid
    if not otp.is_valid():
        return Response(
            {'success': False, 'error': 'OTP code has expired. Please request a new one.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate amount again (in case balance changed)
    amount = Decimal(str(otp.amount))
    if member.balance < amount:
        return Response(
            {'success': False, 'error': 'Insufficient balance'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Find recipient
    try:
        recipient = Member.objects.get(rfid_card_number=otp.recipient_rfid, is_active=True)
    except Member.DoesNotExist:
        return Response(
            {'success': False, 'error': 'Recipient member not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Don't allow transferring to self
    if recipient.id == member.id:
        return Response(
            {'success': False, 'error': 'Cannot transfer funds to yourself'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Perform transfer atomically via database helper
    from helper.database_helper import verify_and_consume_otp, process_fund_transfer
    from .serializers import BalanceTransactionSerializer

    # Consume OTP first (validate + mark used atomically)
    otp_result = verify_and_consume_otp(otp.pk, otp_code)
    if not otp_result.success:
        code_map = {
            'already_used': 'OTP has already been used.',
            'expired':      'OTP code has expired. Please request a new one.',
            'invalid_code': 'Invalid OTP code.',
        }
        return Response(
            {'success': False, 'error': code_map.get(otp_result.code, otp_result.error)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Execute the atomic fund transfer
    transfer_result = process_fund_transfer(member.id, otp.recipient_rfid, amount, otp.notes)
    if not transfer_result.success:
        code_map = {
            'insufficient_balance': 'Insufficient balance',
            'not_found':            'Recipient member not found',
            'self_transfer':        'Cannot transfer funds to yourself',
        }
        return Response(
            {'success': False, 'error': code_map.get(transfer_result.code, transfer_result.error)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    d = transfer_result.data
    sender_txn    = d['sender_transaction']
    recipient_txn = d['recipient_transaction']
    updated_member    = d['sender']
    recipient         = d['recipient']

    # Send completion emails to both parties (async, non-blocking)
    try:
        send_transfer_completion_emails(
            sender=updated_member,
            recipient=recipient,
            amount=amount,
            sender_balance_after=d['sender_balance_after'],
            recipient_balance_after=d['recipient_balance_after'],
            notes=otp.notes,
            transaction_date=sender_txn.created_at,
        )
    except Exception as email_error:
        logger.warning("Failed to send completion emails: %s", email_error)

    try:
        from admin_panel.audit import mark_audit_recorded, record_audit
        actor_user = getattr(member, "user", None)
        record_audit(
            "FUND_TRANSFER",
            actor=actor_user,
            description=(
                f"Fund transfer ₱{amount} from {member.full_name} "
                f"to {recipient.full_name}"
            ),
            request=request,
            object_type="FundTransfer",
            object_id=sender_txn.id,
            metadata={
                "amount": str(amount),
                "sender": member.full_name,
                "recipient": recipient.full_name,
                "notes": otp.notes or "",
            },
        )
        mark_audit_recorded(request)
    except Exception:
        pass

    return Response({
        'success': True,
        'message': f'Successfully transferred {amount} to {recipient.full_name}',
        'transfer': {
            'id': sender_txn.id,
            'recipient': {
                'id': recipient.id,
                'full_name': recipient.full_name,
                'rfid_card_number': recipient.rfid_card_number,
            },
            'amount': str(amount),
            'sender_balance_before': str(d['sender_balance_before']),
            'sender_balance_after':  str(d['sender_balance_after']),
            'notes': otp.notes,
            'created_at': sender_txn.created_at.isoformat(),
        },
        'sender_transaction':    BalanceTransactionSerializer(sender_txn).data,
        'recipient_transaction': BalanceTransactionSerializer(recipient_txn).data,
    })

@csrf_exempt
@require_http_methods(["POST"])
def reset_pin_lockout(request):
    """
    Admin-only endpoint to reset a member's PIN lockout.
    Expected JSON: {"username": "john_doe"}  OR  {"member_id": 5}
    Caller must be an authenticated admin/staff user.
    """
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'success': False, 'error': 'Admin access required'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    member = None
    username = data.get('username', '').strip()
    member_id = data.get('member_id')

    try:
        if member_id:
            member = Member.objects.get(id=member_id)
        elif username:
            from django.contrib.auth.models import User as DjangoUser
            user = DjangoUser.objects.get(username=username)
            member = Member.objects.get(user=user)
        else:
            return JsonResponse({'success': False, 'error': 'username or member_id is required'}, status=400)
    except (Member.DoesNotExist, Exception):
        return JsonResponse({'success': False, 'error': 'Member not found'}, status=404)

    member.pin_attempts = 0
    member.is_pin_locked = False
    member.save(update_fields=['pin_attempts', 'is_pin_locked'])

    return JsonResponse({
        'success': True,
        'message': f'PIN lockout reset for {member.full_name}. They can now log in again.'
    })


@api_view(['GET'])
@permission_classes([MobileMemberPermission])
def product_list(request):
    """
    Returns all active products with their name, category, price, stock quantity,
    and low-stock status. Supports optional filtering by category and search query.
    Query params:
        - category: category name (optional)
        - search: partial name/barcode match (optional)
    """
    products = (
        Product.objects.filter(is_active=True)
        .select_related('category', 'discount_group')
        .order_by('name')
    )

    search = request.query_params.get('search', '').strip()
    category = request.query_params.get('category', '').strip()

    if search:
        from django.db.models import Q
        products = products.filter(
            Q(name__icontains=search) | Q(barcode__icontains=search)
        )

    if category:
        category_list = [c.strip() for c in category.split(',') if c.strip()]
        if category_list:
            products = products.filter(category__name__in=category_list)

    product_list = list(products)
    disc_map = discounts_by_product_ids([p.id for p in product_list])

    member = None
    if request.user and request.user.is_authenticated:
        member = (
            Member.objects.select_related('member_role', 'senior_profile', 'pwd_profile')
            .filter(user=request.user, is_active=True)
            .first()
        )
    if not member and request.session.get('member_id'):
        member = (
            Member.objects.select_related('member_role', 'senior_profile', 'pwd_profile')
            .filter(id=request.session['member_id'], is_active=True)
            .first()
        )
    segment_rules = None
    if member:
        segment_rules = list(SegmentProductGroupDiscount.objects.filter(is_active=True).select_related('discount_group'))

    data = []
    for p in product_list:
        pf = price_payload_for_product(
            p,
            discount_list=disc_map.get(p.id, []),
            member=member,
            segment_rules=segment_rules,
        )
        row = {
            'id': p.id,
            'name': p.name,
            'barcode': p.barcode,
            'category': p.category.name if p.category else None,
            'price': pf['price'],
            'regular_price': pf['regular_price'],
            'discount_group': p.discount_group_code,
            'stock_quantity': p.stock_quantity,
            'low_stock_threshold': p.low_stock_threshold,
            'is_low_stock': p.is_low_stock,
            'is_out_of_stock': p.is_out_of_stock,
        }
        if 'discount_name' in pf:
            row['discount_name'] = pf['discount_name']
        data.append(row)

    categories = list(
        Category.objects.filter(is_active=True).values_list('name', flat=True).order_by('name')
    )

    return Response({
        'success': True,
        'count': len(data),
        'categories': categories,
        'products': data,
    })


@csrf_exempt
@api_view(['POST'])
@authentication_classes([MobileSessionAuthentication])
@permission_classes([MobileMemberPermission])
def request_biometric_otp(request):
    """
    Send OTP to member's email so they can verify their identity before
    enabling fingerprint login.
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response

    if not member.email:
        return Response(
            {'success': False, 'error': 'No email address on your account. Please contact support.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        otp = BiometricEnrollOTP.create_otp(member)
        send_biometric_otp_email(member, otp.otp_code)
        return Response({
            'success': True,
            'message': f'A verification code has been sent to {member.email}.',
            'expires_in': 600,
        })
    except Exception as e:
        logger.error(f'Biometric OTP request error: {e}', exc_info=True)
        return Response(
            {'success': False, 'error': 'Failed to send OTP. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(['POST'])
@authentication_classes([MobileSessionAuthentication])
@permission_classes([MobileMemberPermission])
def verify_biometric_otp(request):
    """
    Verify the OTP code submitted by the user before enabling fingerprint login.
    Expected JSON: {"otp_code": "123456"}
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response

    otp_code = request.data.get('otp_code', '').strip()
    if not otp_code:
        return Response(
            {'success': False, 'error': 'OTP code is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        otp = BiometricEnrollOTP.objects.get(
            member=member,
            otp_code=otp_code,
            is_used=False,
        )
    except BiometricEnrollOTP.DoesNotExist:
        return Response(
            {'success': False, 'error': 'Invalid or expired OTP. Please request a new one.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not otp.is_valid():
        return Response(
            {'success': False, 'error': 'OTP has expired. Please request a new one.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    otp.mark_as_used()
    return Response({'success': True, 'message': 'Identity verified. Fingerprint login has been enabled.'})


# ─── QR Code Endpoints ────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([MobileMemberPermission])
def my_qr_code(request):
    """
    Returns (or lazily creates) the authenticated member's own QR token.
    The mobile app renders this token as a QR code so other members can scan it.
    GET /api/mobile/qr/my-code/
    Response: { success, qr_token, member_name, rfid, is_active, feature_enabled }
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response

    settings = QRFeatureSettings.get_settings()
    qr = MemberQRCode.get_or_create_for_member(member)

    try:
        from admin_panel.audit import record_audit
        record_audit(
            "QR",
            actor=getattr(member, "user", None),
            description=f"{member.full_name} generated / viewed QR transfer code",
            request=request,
            object_type="MemberQRCode",
            object_id=getattr(qr, "pk", ""),
            metadata={"member": member.full_name, "feature_enabled": settings.is_enabled},
        )
    except Exception:
        pass

    return Response({
        'success': True,
        'feature_enabled': settings.is_enabled,
        'qr_token': str(qr.qr_token),
        'member_name': member.full_name,
        'rfid': member.rfid_card_number,
        'is_active': qr.is_active,
    })


@api_view(['GET'])
@permission_classes([MobileMemberPermission])
def scan_qr_code(request):
    """
    Resolves a scanned QR token to a member for the fund-transfer flow.
    Called by the scanner after reading another member's QR code.
    GET /api/mobile/qr/scan/?token=<uuid>
    Response mirrors search_member: { success, member } on hit.
    """
    scanner, error_response = get_member_from_request(request)
    if error_response:
        return error_response

    settings = QRFeatureSettings.get_settings()
    if not settings.is_enabled:
        return Response(
            {'success': False, 'error': 'QR transfer feature is currently disabled.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    token = request.query_params.get('token', '').strip()
    if not token:
        return Response(
            {'success': False, 'error': 'QR token is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        qr = MemberQRCode.objects.select_related('member').get(qr_token=token)
    except (MemberQRCode.DoesNotExist, Exception):
        return Response(
            {'success': False, 'error': 'Invalid or unrecognised QR code.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if not qr.is_active:
        return Response(
            {'success': False, 'error': 'This member\'s QR transfer is currently disabled.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    recipient = qr.member
    if not recipient.is_active:
        return Response(
            {'success': False, 'error': 'Member account is inactive.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if recipient.id == scanner.id:
        return Response(
            {'success': False, 'error': 'Cannot transfer funds to yourself.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Record the scan
    qr.record_scan()

    serializer = MemberSerializer(recipient)
    return Response({
        'success': True,
        'member': serializer.data,
        'max_transfer_amount': str(settings.max_transfer_amount),
    })


@csrf_exempt
@api_view(['POST'])
@authentication_classes([MobileSessionAuthentication])
@permission_classes([MobileMemberPermission])
def regenerate_my_qr(request):
    """
    Lets the authenticated member voluntarily regenerate their own QR token
    (e.g. if they suspect their token was leaked).
    POST /api/mobile/qr/regenerate/
    Response: { success, qr_token }
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response

    qr = MemberQRCode.get_or_create_for_member(member)
    qr.regenerate_token()

    return Response({
        'success': True,
        'message': 'QR code has been refreshed.',
        'qr_token': str(qr.qr_token),
    })


@api_view(['POST'])
@permission_classes([MobileMemberPermission])
def request_refund(request):
    """
    Let an authenticated member request a refund on one of their completed transactions.
    POST /api/mobile/transactions/request-refund/
    Body: { "transaction_id": <int> }
    Response: { success, message }
    """
    member, error_response = get_member_from_request(request)
    if error_response:
        return error_response

    transaction_id = request.data.get('transaction_id')
    if not transaction_id:
        return Response({'success': False, 'error': 'transaction_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        transaction = Transaction.objects.get(id=transaction_id, member=member)
    except Transaction.DoesNotExist:
        return Response({'success': False, 'error': 'Transaction not found.'}, status=status.HTTP_404_NOT_FOUND)

    if transaction.status != 'completed':
        status_labels = {
            'pending': 'pending',
            'cancelled': 'already cancelled',
            'refund_requested': 'already submitted for refund',
            'refunded': 'already refunded',
        }
        label = status_labels.get(transaction.status, transaction.status)
        return Response(
            {'success': False, 'error': f'Only completed transactions can be refunded. This transaction is {label}.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    from helper.database_helper import complete_transaction

    result = complete_transaction(transaction_id, status='refund_requested')
    if not result.success:
        return Response(
            {'success': False, 'error': result.error},
            status=status.HTTP_400_BAD_REQUEST if result.code == 'not_found' else status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    transaction = result.data['transaction']

    # Save or update the refund reason if provided
    refund_reason_value = request.data.get('refund_reason', '').strip()
    from transactions.models import RefundReason, TransactionItem
    valid_keys = {k for k, _ in RefundReason.REASON_CHOICES}
    reason_type = refund_reason_value if refund_reason_value in valid_keys else 'other'
    refund_reason_obj, _ = RefundReason.objects.update_or_create(
        transaction=transaction,
        defaults={'reason_type': reason_type},
    )

    # Store the specific items the member wants refunded (if provided)
    refund_item_ids = request.data.get('refund_item_ids', [])
    if refund_item_ids:
        valid_items = TransactionItem.objects.filter(
            id__in=refund_item_ids,
            transaction=transaction
        )
        refund_reason_obj.refund_items.set(valid_items)
    else:
        refund_reason_obj.refund_items.clear()

    # Notify admin/cashier via email (non-blocking)
    from .email_utils import send_refund_request_notification
    reason_display = dict(RefundReason.REASON_CHOICES).get(reason_type, reason_type.replace('_', ' ').title())
    send_refund_request_notification(transaction, member, reason_type=reason_type, reason_display=reason_display)

    return Response({
        'success': True,
        'message': f'Refund request submitted for transaction {transaction.transaction_number}. Please wait for admin approval.',
    })