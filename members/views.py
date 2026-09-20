from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
import json

from .models import Member
from login_helper import rfid_validate_json_response


@ensure_csrf_cookie
def rfid_gate(request):
	"""Render a small page that asks for an RFID scan before allowing access to the login screen."""
	return render(request, 'members/rfid_gate.html')


@require_http_methods(["POST"])
def api_validate_rfid_login(request):
	"""Validate RFID sent in JSON body — delegates to login_helper.

	Expected JSON: { "rfid": "1001" }
	"""
	try:
		data = json.loads(request.body)
	except json.JSONDecodeError:
		return JsonResponse({'success': False, 'error': 'Invalid JSON data'})

	rfid = (data.get('rfid') or '').strip()
	return rfid_validate_json_response(rfid)
