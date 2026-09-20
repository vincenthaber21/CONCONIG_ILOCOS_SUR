import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_member_cannot_access_committee_review(client, application, member):
    client.force_login(member)
    url = reverse("loans:committee-review", kwargs={"pk": application.pk})

    response = client.get(url)

    assert response.status_code == 403


@pytest.mark.django_db
def test_committee_member_with_permission_can_access_committee_review(
    client, application, committee_member
):
    from django.contrib.auth.models import Permission

    permission = Permission.objects.get(
        content_type__app_label="loans", codename="can_approve"
    )
    committee_member.user_permissions.add(permission)

    client.force_login(committee_member)
    url = reverse("loans:committee-review", kwargs={"pk": application.pk})

    response = client.get(url)

    assert response.status_code == 200


@pytest.mark.django_db
def test_anonymous_user_redirected_to_login(client, application):
    url = reverse("loans:application-detail", kwargs={"pk": application.pk})

    response = client.get(url)

    assert response.status_code == 302
    assert reverse("login") in response.url
