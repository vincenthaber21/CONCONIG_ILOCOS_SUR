from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    """Custom user model for the cooperative credit service.

    Extends Django's AbstractUser with a `role` field that drives
    permissions and UI routing across the loan origination pipeline.
    """

    class Role(models.TextChoices):
        MEMBER = "MEMBER", "Member"
        STAFF = "STAFF", "Staff"
        CREDIT_OFFICER = "CREDIT_OFFICER", "Credit Officer"
        COMMITTEE = "COMMITTEE", "Credit Committee"
        CASHIER = "CASHIER", "Cashier"
        ADMIN = "ADMIN", "Admin"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    phone_number = models.CharField(max_length=20, blank=True)
    member_number = models.CharField(max_length=30, blank=True)

    objects = UserManager()

    class Meta:
        ordering = ["username"]

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def is_member(self):
        return self.role == self.Role.MEMBER

    @property
    def is_credit_officer(self):
        return self.role == self.Role.CREDIT_OFFICER

    @property
    def is_committee(self):
        return self.role == self.Role.COMMITTEE

    @property
    def is_cashier(self):
        return self.role == self.Role.CASHIER

    def has_role(self, *roles):
        return self.role in roles
