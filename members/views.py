from django.shortcuts import redirect, render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
import json

from .models import Member, Role
from login_helper import (
    is_member_session_valid,
    resolve_redirect_url,
    resolve_redirect_url_for_member_only,
    rfid_validate_json_response,
)
from members.active_role import (
    POST_LOGIN_NEXT,
    activate_chosen_role,
    clear_chosen_role,
    member_for_request,
    role_choice_meta,
)


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


def _redirect_after_role_choice(request):
	next_url = request.session.pop(POST_LOGIN_NEXT, "") or ""
	user = request.user if getattr(request.user, "is_authenticated", False) else None
	if user is not None:
		return redirect(resolve_redirect_url(user, next_url))
	return redirect(resolve_redirect_url_for_member_only(next_url))


@require_http_methods(["GET", "POST"])
def choose_role(request):
	"""After login, pick which assigned role to open for this session."""
	member = member_for_request(request)
	if member is None or not member.is_active:
		if request.user.is_authenticated or is_member_session_valid(request):
			return redirect("user_choice")
		return redirect("root_login")

	roles = list(
		Role.objects.filter(slug__in=member.assigned_role_slugs(), is_active=True).order_by(
			"sort_order", "name"
		)
	)
	if len(roles) <= 1:
		slug = roles[0].slug if roles else "member"
		activate_chosen_role(request, member, slug)
		return _redirect_after_role_choice(request)

	error = ""
	if request.method == "POST":
		slug = (request.POST.get("role") or "").strip().lower()
		allowed = {role.slug for role in roles}
		if slug not in allowed:
			error = "Choose one of your roles."
		else:
			activate_chosen_role(request, member, slug)
			return _redirect_after_role_choice(request)

	cards = []
	for role in roles:
		icon, blurb = role_choice_meta(role.slug)
		cards.append({
			"slug": role.slug,
			"name": role.name,
			"icon": icon,
			"blurb": blurb,
		})
	return render(request, "admin_panel/choose_role.html", {
		"member": member,
		"role_cards": cards,
		"error": error,
	})


@require_http_methods(["GET"])
def switch_role(request):
	"""Clear the role opened for this login and show the picker again."""
	member = member_for_request(request)
	if member is None:
		return redirect("root_login")
	clear_chosen_role(request)
	return redirect("choose_role")
