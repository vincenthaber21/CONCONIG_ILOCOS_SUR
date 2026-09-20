import pytest

from accounts.models import User


@pytest.mark.django_db
def test_create_user_defaults_to_member_role():
    user = User.objects.create_user(username="jdoe", password="pass12345")
    assert user.role == User.Role.MEMBER
    assert user.is_member is True


@pytest.mark.django_db
def test_create_superuser_defaults_to_admin_role():
    admin = User.objects.create_superuser(username="root", password="pass12345")
    assert admin.role == User.Role.ADMIN
    assert admin.is_staff is True
    assert admin.is_superuser is True
