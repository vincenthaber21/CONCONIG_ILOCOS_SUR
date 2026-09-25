import secrets
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone

class Role(models.Model):
    """Assignable roles for kiosk / admin users (Member, Staff, Cashier, Admin)."""

    slug = models.SlugField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=50)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    VALID_SLUGS = frozenset({"admin", "cashier", "staff", "loan_officer", "member", "committee"})

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Role"
        verbose_name_plural = "Roles"

    def __str__(self):
        return self.name

    @classmethod
    def resolve_slug(cls, slug):
        """Return the Role row for *slug* (any row in the Role table), defaulting to Member."""
        s = (slug or "").strip().lower()
        if not s:
            s = "member"
        obj = cls.objects.filter(slug__iexact=s).first()
        if obj:
            return obj
        fallback = cls.objects.filter(slug="member").first()
        if fallback is None:
            raise RuntimeError("Role table is empty; apply members migrations.")
        return fallback


class MemberStatus(models.Model):
    """Membership lifecycle status (Active, Resign, Suspended, etc.)."""

    SLUG_ACTIVE = "active"
    SLUG_RESIGN = "resign"
    SLUG_SUSPENDED = "suspended"
    SLUG_DECEASED = "deceased"
    SLUG_INACTIVE = "inactive"

    slug = models.SlugField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=50)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(
        default=True,
        help_text="Uncheck to hide this status from new assignments.",
    )

    VALID_SLUGS = frozenset({
        SLUG_ACTIVE,
        SLUG_RESIGN,
        SLUG_SUSPENDED,
        SLUG_DECEASED,
        SLUG_INACTIVE,
    })

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Member status"
        verbose_name_plural = "Member statuses"

    def __str__(self):
        return self.name

    @classmethod
    def resolve_slug(cls, slug, *, default=SLUG_ACTIVE):
        s = (slug or "").strip().lower()
        if not s:
            s = default
        obj = cls.objects.filter(slug__iexact=s, is_active=True).first()
        if obj:
            return obj
        obj = cls.objects.filter(slug__iexact=s).first()
        if obj:
            return obj
        fallback = cls.objects.filter(slug=default).first()
        if fallback is None:
            raise RuntimeError("MemberStatus table is empty; apply members migrations.")
        return fallback


class MemberType(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Member type"
        verbose_name_plural = "Member types"


class Nationality(models.Model):
    """Lookup of nationalities for membership application forms."""

    SLUG_FILIPINO = "filipino"

    slug = models.SlugField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(
        default=True,
        help_text="Uncheck to hide this nationality from new assignments.",
    )

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Nationality"
        verbose_name_plural = "Nationalities"

    def __str__(self):
        return self.name

    @classmethod
    def resolve_slug(cls, slug, *, default=SLUG_FILIPINO):
        s = (slug or "").strip().lower()
        if not s:
            s = default
        obj = cls.objects.filter(slug__iexact=s, is_active=True).first()
        if obj:
            return obj
        obj = cls.objects.filter(slug__iexact=s).first()
        if obj:
            return obj
        fallback = cls.objects.filter(slug=default).first()
        if fallback is None:
            raise RuntimeError("Nationality table is empty; apply members migrations.")
        return fallback


class ProjectCategory(models.Model):
    """
    Project / livelihood category assigned when cashiers or admins register a member.
    Managed under Members → Project categories; selectable on Add member.
    """

    slug = models.SlugField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(
        default=True,
        help_text="Uncheck to hide this category from new member assignments.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Project category"
        verbose_name_plural = "Project categories"

    def __str__(self):
        return self.name

    @classmethod
    def resolve_slug(cls, slug):
        s = (slug or "").strip().lower()
        if not s:
            return None
        obj = cls.objects.filter(slug__iexact=s, is_active=True).first()
        if obj:
            return obj
        return cls.objects.filter(slug__iexact=s).first()


class Member(models.Model):
    GENDER_MALE = "male"
    GENDER_FEMALE = "female"
    GENDER_OTHER = "other"
    GENDER_CHOICES = [
        (GENDER_MALE, "Male"),
        (GENDER_FEMALE, "Female"),
        (GENDER_OTHER, "Other"),
    ]

    CIVIL_SINGLE = "single"
    CIVIL_MARRIED = "married"
    CIVIL_WIDOWED = "widowed"
    CIVIL_SEPARATED = "separated"
    CIVIL_LIVE_IN = "live_in"
    CIVIL_STATUS_CHOICES = [
        (CIVIL_SINGLE, "Single"),
        (CIVIL_MARRIED, "Married"),
        (CIVIL_WIDOWED, "Widowed"),
        (CIVIL_SEPARATED, "Separated"),
        (CIVIL_LIVE_IN, "Live-in"),
    ]

    EDUC_ELEMENTARY = "elementary"
    EDUC_HIGH_SCHOOL = "high_school"
    EDUC_COLLEGE_LEVEL = "college_level"
    EDUC_COLLEGE_GRAD = "college_grad"
    EDUC_POST_GRADUATE = "post_graduate"
    EDUCATIONAL_ATTAINMENT_CHOICES = [
        (EDUC_ELEMENTARY, "Elementary"),
        (EDUC_HIGH_SCHOOL, "High School"),
        (EDUC_COLLEGE_LEVEL, "College Level"),
        (EDUC_COLLEGE_GRAD, "College Grad."),
        (EDUC_POST_GRADUATE, "Post Graduate"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    username = models.CharField(max_length=150, unique=True, null=True, blank=True)
    rfid_card_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    # store a hashed 4-digit PIN for member security (not plaintext)
    pin_hash = models.CharField(max_length=128, blank=True, null=True)
    membership_number = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name="Membership number",
    )
    photo = models.ImageField(
        upload_to="members/photos/",
        null=True,
        blank=True,
        verbose_name="Photo",
    )
    first_name = models.CharField(max_length=100, verbose_name="First name")
    middle_name = models.CharField(max_length=100, blank=True, default="", verbose_name="Middle name")
    last_name = models.CharField(max_length=100, verbose_name="Surname")
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Cellular no.",
    )
    member_type = models.ForeignKey(MemberType, on_delete=models.SET_NULL, null=True, blank=True)
    member_role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="members",
        help_text="Default role kept for existing member lists. Prefer Member when it is one of the assigned roles.",
    )
    roles = models.ManyToManyField(
        Role,
        related_name="assigned_members",
        blank=True,
        help_text="Every role this person may open after login.",
    )

    # Membership application — Personal data
    place_of_birth = models.CharField(max_length=255, blank=True, default="")
    home_address = models.TextField(
        blank=True,
        default="",
        verbose_name="Home (mailing) / present / permanent address",
    )
    barangay = models.CharField(max_length=150, blank=True, default="")
    municipality = models.CharField(max_length=150, blank=True, default="")
    province = models.CharField(max_length=150, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True, default="", choices=GENDER_CHOICES)
    tin = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name="Tax identification no.",
    )
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    civil_status = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=CIVIL_STATUS_CHOICES,
    )
    nationality = models.ForeignKey(
        Nationality,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="members",
        verbose_name="Nationality",
    )
    religion = models.CharField(max_length=100, blank=True, default="")
    educational_attainment = models.CharField(
        max_length=150,
        blank=True,
        default="",
        choices=EDUCATIONAL_ATTAINMENT_CHOICES,
        verbose_name="Highest educ. attainment",
    )
    occupation = models.CharField(max_length=150, blank=True, default="")
    income_sources = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Business / occupation / source of income",
    )
    annual_income = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Monthly salary / annual income",
    )
    complete_business_name_address = models.TextField(
        blank=True,
        default="",
        verbose_name="Complete business name / address",
    )
    business_telephone = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="Telephone no.",
    )
    business_cellular = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="Cellular phone no.",
    )

    # Name of spouse
    spouse_last_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Spouse surname",
    )
    spouse_first_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Spouse first name",
    )
    spouse_middle_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Spouse middle name",
    )
    spouse_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Name of spouse (full)",
        help_text="Auto-filled from spouse name parts when those are set.",
    )
    spouse_age = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Spouse age")
    spouse_gender = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=GENDER_CHOICES,
        verbose_name="Spouse gender",
    )
    spouse_date_of_birth = models.DateField(
        null=True,
        blank=True,
        verbose_name="Spouse date of birth",
    )
    spouse_employer_business = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Name of employer / business",
    )
    spouse_occupation = models.CharField(
        max_length=150,
        blank=True,
        default="",
        verbose_name="Spouse occupation",
    )
    spouse_employer_address = models.TextField(
        blank=True,
        default="",
        verbose_name="Employer / business address",
    )
    spouse_telephone = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="Spouse telephone no.",
    )
    spouse_cellular = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="Spouse cell. phone no.",
    )

    # Approval area (membership application)
    approval_date = models.DateField(null=True, blank=True, verbose_name="Approval date")
    approved_by = models.CharField(
        max_length=150,
        blank=True,
        default="",
        verbose_name="Approved by (Chairperson)",
    )
    recorded_by = models.CharField(
        max_length=150,
        blank=True,
        default="",
        verbose_name="Recorded by (Cooperative Secretary)",
    )
    resolution_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="BOD Resolution No.",
    )
    signature = models.ImageField(
        upload_to="members/signatures/",
        null=True,
        blank=True,
        verbose_name="Signature over printed name",
    )
    thumb_mark = models.ImageField(
        upload_to="members/thumb_marks/",
        null=True,
        blank=True,
        verbose_name="Right hand thumb mark",
    )

    # Legacy / RSBSA profile details (optional)
    project_categories = models.ManyToManyField(
        "inventory.Category",
        blank=True,
        related_name="members",
        verbose_name="Project categories",
        help_text=(
            "Project categories assigned at registration (cashier or admin). "
            "Select one or more. Managed under Inventory → Categories."
        ),
    )
    coop_type = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Type",
        help_text="Membership / farm type classification.",
    )
    area = models.CharField(max_length=150, blank=True, default="")
    member_status = models.ForeignKey(
        MemberStatus,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="members",
        verbose_name="Status",
        help_text="Membership lifecycle status (e.g. Active, Resign).",
    )
    membership_status = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Status (label)",
        help_text="Display label kept in sync with member status when set.",
    )
    location = models.CharField(max_length=255, blank=True, default="")
    rsbsa_remarks = models.TextField(
        blank=True,
        default="",
        verbose_name="Remarks (RSBSA)",
    )
    rsbsa_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="RSBSA number",
    )
    other_assets = models.TextField(blank=True, default="")
    date_of_pmes = models.DateField(
        null=True,
        blank=True,
        verbose_name="Date of PMES",
    )
    date_accepted = models.DateField(null=True, blank=True)
    or_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="OR number",
    )
    initial_capital_paid_up = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Initial capital paid-up",
    )
    date_of_mf_recog = models.DateField(
        null=True,
        blank=True,
        verbose_name="Date of MF Recog",
    )
    mf_center = models.CharField(
        max_length=150,
        blank=True,
        default="",
        verbose_name="MF Center",
    )

    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    share_capital = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Current paid-up share capital balance for this member.",
    )

    pin_attempts = models.IntegerField(default=0)
    is_pin_locked = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)
    inactive_remark = models.TextField(
        blank=True,
        default="",
        help_text="Required when the member is inactive. Explain why the account was deactivated.",
    )
    date_joined = models.DateTimeField(
        default=timezone.now,
        help_text=(
            "Exact registration date and time. Used to determine loan eligibility."
        ),
    )
    last_transaction = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        rfid = self.rfid_card_number or 'No RFID'
        return f"{self.first_name} {self.last_name} ({rfid})"

    @property
    def stored_role_slug(self):
        """Primary role saved on the account, ignoring the role chosen for this login."""
        if self.member_role_id:
            return self.member_role.slug
        return "member"

    def assigned_role_slugs(self):
        """Slugs this person may choose after login, including the primary role."""
        cached = getattr(self, "_assigned_role_slug_cache", None)
        if cached is not None:
            return cached
        prefetched = getattr(self, "_prefetched_objects_cache", {})
        if "roles" in prefetched:
            slugs = {role.slug.lower() for role in self.roles.all()}
        else:
            slugs = {slug.lower() for slug in self.roles.values_list("slug", flat=True)}
        if self.member_role_id:
            slugs.add(self.member_role.slug.lower())
        if not slugs:
            slugs.add("member")
        self._assigned_role_slug_cache = frozenset(slugs)
        return self._assigned_role_slug_cache

    def clear_assigned_role_cache(self):
        if hasattr(self, "_assigned_role_slug_cache"):
            del self._assigned_role_slug_cache

    def has_assigned_role(self, slug):
        return (slug or "").strip().lower() in self.assigned_role_slugs()

    def shows_account_balance(self):
        """Committee-only accounts do not use a card balance."""
        return self.assigned_role_slugs() != frozenset({"committee"})

    def assigned_roles_csv(self):
        prefetched = getattr(self, "_prefetched_objects_cache", {})
        if "roles" in prefetched:
            ordered = sorted(self.roles.all(), key=lambda role: (role.sort_order, role.name))
            slugs = [role.slug for role in ordered]
        else:
            slugs = list(
                self.roles.order_by("sort_order", "name").values_list("slug", flat=True)
            )
        if not slugs and self.member_role_id:
            slugs = [self.member_role.slug]
        return ",".join(slugs) or "member"

    @classmethod
    def pick_primary_role(cls, role_objects):
        """Prefer Member so cooperative lists still include multi-role people."""
        roles = list(role_objects or [])
        if not roles:
            return Role.resolve_slug("member")
        member_role = next((role for role in roles if role.slug == "member"), None)
        if member_role is not None:
            return member_role
        return sorted(roles, key=lambda role: (role.sort_order, role.name, role.pk))[0]

    def set_assigned_roles(self, role_objects):
        """Save every login role and keep ``member_role`` as the primary default."""
        unique = []
        seen = set()
        for role in role_objects or []:
            if role is None or role.pk in seen:
                continue
            seen.add(role.pk)
            unique.append(role)
        if not unique:
            unique = [Role.resolve_slug("member")]
        self.roles.set(unique)
        primary = self.pick_primary_role(unique)
        self.clear_assigned_role_cache()
        if self.member_role_id != primary.pk:
            self.member_role = primary
            self.save(update_fields=["member_role", "updated_at"])

    @property
    def role(self):
        """Role slug for this login when the person has chosen one, else the primary role."""
        stored = self.stored_role_slug
        from members.active_role import current_request, SESSION_MEMBER_ID, SESSION_ROLE

        request = current_request()
        if request is None:
            return stored
        active = (request.session.get(SESSION_ROLE) or "").strip().lower()
        member_id = request.session.get(SESSION_MEMBER_ID)
        if not active or member_id is None:
            return stored
        try:
            if int(member_id) != int(self.pk):
                return stored
        except (TypeError, ValueError):
            return stored
        if active in self.assigned_role_slugs():
            return active
        return stored

    def get_role_display(self):
        """Human-readable role label for the role currently in use."""
        slug = self.role
        if slug != self.stored_role_slug:
            match = self.roles.filter(slug=slug).first()
            if match is not None:
                return match.name
        if self.member_role_id:
            return self.member_role.name
        return "Member"

    @property
    def full_name(self):
        parts = [self.first_name, (self.middle_name or "").strip(), self.last_name]
        return " ".join(p for p in parts if p)

    @property
    def spouse_full_name(self):
        parts = [
            self.spouse_first_name,
            (self.spouse_middle_name or "").strip(),
            self.spouse_last_name,
        ]
        composed = " ".join(p for p in parts if p)
        return composed or (self.spouse_name or "")

    def compute_age(self, on_date=None, born=None):
        """Return age in years from a birth date, or stored ``age`` if no DOB."""
        dob = born if born is not None else self.date_of_birth
        if not dob:
            return self.age
        today = on_date or timezone.localdate()
        years = today.year - dob.year - (
            (today.month, today.day) < (dob.month, dob.day)
        )
        return max(0, years)

    def sync_age_from_dob(self):
        """Set ``age`` / spouse age from date of birth when present."""
        if self.date_of_birth:
            self.age = self.compute_age()
        if self.spouse_date_of_birth:
            self.spouse_age = self.compute_age(born=self.spouse_date_of_birth)

    def sync_spouse_name(self):
        """Keep legacy ``spouse_name`` in sync with structured spouse name parts."""
        parts = [
            self.spouse_first_name,
            (self.spouse_middle_name or "").strip(),
            self.spouse_last_name,
        ]
        composed = " ".join(p for p in parts if p)
        if composed:
            self.spouse_name = composed

    def apply_member_status(self, status_or_slug, *, deactivate=None):
        """
        Assign a ``MemberStatus`` (instance or slug) and sync ``membership_status``.

        When *deactivate* is True/False, also update ``is_active``. When None,
        resign / suspended / deceased / inactive slugs deactivate the member.
        """
        if isinstance(status_or_slug, MemberStatus):
            status = status_or_slug
        else:
            status = MemberStatus.resolve_slug(status_or_slug)
        self.member_status = status
        self.membership_status = status.name
        inactive_slugs = {
            MemberStatus.SLUG_RESIGN,
            MemberStatus.SLUG_SUSPENDED,
            MemberStatus.SLUG_DECEASED,
            MemberStatus.SLUG_INACTIVE,
        }
        if deactivate is None:
            deactivate = status.slug in inactive_slugs
        if deactivate:
            self.is_active = False
        elif status.slug == MemberStatus.SLUG_ACTIVE:
            self.is_active = True
            self.inactive_remark = ""

    def get_loan_eligibility(self):
        """Loan request eligibility based on registration date (``date_joined``)."""
        from loans.services import member_loan_waiting_period

        return member_loan_waiting_period(self, user=self.user)

    @property
    def available_balance(self):
        return self.balance

    def add_balance(self, amount):
        self.balance += amount
        self.save()

    def deduct_balance(self, amount):
        if self.balance >= amount:
            self.balance -= amount
            self.save()
            return True
        return False

    def add_share_capital(self, amount):
        self.share_capital += amount
        self.save(update_fields=["share_capital", "updated_at"])

    def deduct_share_capital(self, amount):
        if self.share_capital >= amount:
            self.share_capital -= amount
            self.save(update_fields=["share_capital", "updated_at"])
            return True
        return False

    def set_pin(self, pin: str):
        """Set a 4-digit PIN for the member. PIN is hashed using Django's password hasher.

        Raises ValueError if PIN is not exactly 4 digits.
        """
        pin = '' if pin is None else str(pin).strip()
        if not pin.isdigit() or len(pin) != 4:
            raise ValueError('PIN must be a 4-digit string')
        self.pin_hash = make_password(pin)
        # Always persist the hash immediately so later check_pin() can verify it.
        if self.pk:
            self.save(update_fields=['pin_hash', 'updated_at'])
        else:
            self.save()

    def check_pin(self, pin: str) -> bool:
        """Validate a candidate PIN against the value stored in pin_hash."""
        if not self.pin_hash:
            return False
        pin = '' if pin is None else str(pin).strip()
        if not pin:
            return False
        stored = str(self.pin_hash).strip()
        # Legacy / accidental plaintext 4-digit values — accept once, then upgrade.
        if len(stored) == 4 and stored.isdigit():
            if stored != pin:
                return False
            if self.pk:
                self.set_pin(pin)
            return True
        return check_password(pin, stored)

    @property
    def masked_rfid(self):
        """Return masked RFID showing only the last 4 digits (e.g. ******5033)."""
        from .utils import mask_rfid
        return mask_rfid(self.rfid_card_number)

    def get_senior_profile_safe(self):
        try:
            return self.senior_profile
        except ObjectDoesNotExist:
            return None

    def get_pwd_profile_safe(self):
        try:
            return self.pwd_profile
        except ObjectDoesNotExist:
            return None

    @property
    def active_concession_kind(self):
        """Active concession at kiosk: ``senior``, ``pwd``, or ``None``."""
        sp = self.get_senior_profile_safe()
        if sp and sp.is_active:
            return 'senior'
        pp = self.get_pwd_profile_safe()
        if pp and pp.is_active:
            return 'pwd'
        return None

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        remark = (self.inactive_remark or "").strip()
        if self.is_active:
            self.inactive_remark = ""
        elif not remark:
            raise ValidationError({
                "inactive_remark": "Please enter a remark explaining why this member is inactive.",
            })
        else:
            self.inactive_remark = remark

    class Meta:
        verbose_name = "Member"
        verbose_name_plural = "Members"
        ordering = ['-date_joined']


class MemberBeneficiaryDependent(models.Model):
    """Beneficiary / dependent row from the membership application form."""

    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="beneficiaries_dependents",
    )
    name = models.CharField(max_length=200)
    date_of_birth = models.DateField(null=True, blank=True)
    relationship = models.CharField(max_length=100, blank=True, default="")
    is_dependent = models.BooleanField(default=False, verbose_name="Dependent")
    is_beneficiary = models.BooleanField(default=False, verbose_name="Beneficiary")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "Beneficiary / dependent"
        verbose_name_plural = "Beneficiaries / dependents"

    def __str__(self):
        flags = []
        if self.is_dependent:
            flags.append("dependent")
        if self.is_beneficiary:
            flags.append("beneficiary")
        suffix = f" ({', '.join(flags)})" if flags else ""
        return f"{self.name}{suffix}"


class ConcessionDiscountPolicy(models.Model):
    """
    Legacy percent-based policy (no longer used at checkout).

    Checkout now uses Segment product discounts (fixed pesos per segment + product discount_group).
    This table is kept for existing databases only; you may ignore or remove rows in admin if unused.
    """

    SLUG_SENIOR = 'senior'
    SLUG_PWD = 'pwd'
    SLUG_CHOICES = [
        (SLUG_SENIOR, 'Senior citizen'),
        (SLUG_PWD, 'PWD (Person with disability)'),
    ]

    slug = models.CharField(max_length=20, choices=SLUG_CHOICES, unique=True)
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('20.00'),
        help_text='Percent off the product list price for eligible members.',
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Concession discount policy'
        verbose_name_plural = 'Concession discount policies'

    def __str__(self):
        return f'{self.get_slug_display()} — {self.discount_percent}%'

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if self.discount_percent <= 0 or self.discount_percent > 100:
            raise ValidationError({'discount_percent': 'Percent must be between 0 and 100.'})


class SeniorCitizenProfile(models.Model):
    """Registers a member as eligible for senior-citizen concession pricing at the kiosk."""

    member = models.OneToOneField(
        Member,
        on_delete=models.CASCADE,
        related_name='senior_profile',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Uncheck to suspend senior benefits without deleting the record.',
    )
    osca_id_number = models.CharField(
        max_length=64,
        blank=True,
        help_text='Optional OSCA / ID reference for your records.',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Senior citizen profile'
        verbose_name_plural = 'Senior citizen profiles'

    def __str__(self):
        return f'Senior — {self.member.full_name}'

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if self.is_active and self.member_id:
            if PWDProfile.objects.filter(member_id=self.member_id, is_active=True).exists():
                raise ValidationError(
                    'This member already has an active PWD profile. '
                    'Only one concession type (senior or PWD) may be active at a time.'
                )


class PWDProfile(models.Model):
    """Registers a member as eligible for PWD concession pricing at the kiosk."""

    member = models.OneToOneField(
        Member,
        on_delete=models.CASCADE,
        related_name='pwd_profile',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Uncheck to suspend PWD benefits without deleting the record.',
    )
    pwd_id_number = models.CharField(
        max_length=64,
        blank=True,
        help_text='Optional PWD ID reference for your records.',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'PWD profile'
        verbose_name_plural = 'PWD profiles'

    def __str__(self):
        return f'PWD — {self.member.full_name}'

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if self.is_active and self.member_id:
            qs = SeniorCitizenProfile.objects.filter(member_id=self.member_id, is_active=True)
            if qs.exists():
                raise ValidationError(
                    'This member already has an active senior citizen profile. '
                    'Only one concession type (senior or PWD) may be active at a time.'
                )


class SegmentProductGroupDiscount(models.Model):
    """
    Fixed peso discount per customer segment and product discount_group (see inventory.Product).
    Examples: Seniors/PWDs ₱5 off dairy SKUs; members ₱10 off dairy 1L/500ml, ₱5 off 250ml, etc.
    """

    SEG_SENIOR_PWD = 'senior_pwd'
    SEG_MEMBER_RESELLER = 'member_reseller'
    SEGMENT_CHOICES = [
        (SEG_SENIOR_PWD, 'Seniors and PWDs'),
        (SEG_MEMBER_RESELLER, 'Members / resellers'),
    ]

    segment = models.CharField(max_length=32, choices=SEGMENT_CHOICES)
    discount_group = models.ForeignKey(
        'inventory.ProductDiscountGroup',
        on_delete=models.PROTECT,
        related_name='segment_discount_rules',
    )
    amount_off = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Pesos deducted per unit after promotional discounts are applied.',
    )
    label = models.CharField(
        max_length=160,
        blank=True,
        help_text='Optional label on receipts (defaults to amount off).',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['segment', 'discount_group']
        verbose_name = 'Segment product discount'
        verbose_name_plural = 'Segment product discounts'
        unique_together = [['segment', 'discount_group']]

    def __str__(self):
        dg = self.discount_group.name if self.discount_group_id else '—'
        return f'{self.get_segment_display()} — {dg} (₱{self.amount_off})'

    def get_discount_group_display(self):
        """Same contract as Django’s choice-field helper (used in templates)."""
        return self.discount_group.name if self.discount_group_id else '—'

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if self.amount_off is not None and self.amount_off <= 0:
            raise ValidationError({'amount_off': 'Amount must be greater than zero.'})


class ShareCapitalTransaction(models.Model):
    """Ledger of member share-capital deposits and withdrawals."""

    TRANSACTION_TYPES = [
        ("opening", "Opening deposit"),
        ("deposit", "Deposit"),
        ("withdrawal", "Withdrawal"),
        ("adjustment", "Adjustment"),
    ]

    transaction_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Unique reference for this share-capital ledger row.",
    )
    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="share_capital_transactions",
    )
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="share_capital_transactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.transaction_number:
            for _ in range(8):
                candidate = secrets.token_hex(12).upper()
                if not ShareCapitalTransaction.objects.filter(
                    transaction_number=candidate
                ).exclude(pk=self.pk).exists():
                    self.transaction_number = candidate
                    break
            else:
                raise RuntimeError("Could not allocate a unique transaction_number")
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.transaction_number} — {self.member.full_name} - "
            f"{self.transaction_type} - {self.amount}"
        )

    class Meta:
        verbose_name = "Share Capital Transaction"
        verbose_name_plural = "Share Capital Transactions"
        ordering = ["-created_at"]


class BalanceTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('deposit', 'Deposit'),
        ('deduction', 'Deduction'),
    ]

    transaction_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Unique reference for this ledger row (audit / support).",
    )
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='balance_transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    balance_before = models.DecimalField(max_digits=10, decimal_places=2)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.transaction_number:
            # Uniquely identify each balance movement for security and support.
            for _ in range(8):
                candidate = secrets.token_hex(12).upper()
                if not BalanceTransaction.objects.filter(transaction_number=candidate).exclude(pk=self.pk).exists():
                    self.transaction_number = candidate
                    break
            else:
                raise RuntimeError("Could not allocate a unique transaction_number")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction_number} — {self.member.full_name} - {self.transaction_type} - {self.amount}"

    class Meta:
        verbose_name = "Balance Transaction"
        verbose_name_plural = "Balance Transactions"
        ordering = ['-created_at']


class CardBalanceRefill(models.Model):
    """Card top-up performed from Django admin (and recorded for API refills)."""

    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name='card_balance_refills')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    balance_before = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    notes = models.TextField(blank=True, help_text="Optional note shown on the ledger entry.")
    balance_transaction = models.OneToOneField(
        BalanceTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='card_refill',
    )
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='card_balance_refills',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversed_balance_refills',
    )
    reversal_balance_transaction = models.OneToOneField(
        BalanceTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='card_refill_reversal',
    )

    class Meta:
        verbose_name = "Refill card balance"
        verbose_name_plural = "Refill card balances"
        ordering = ['-created_at']

    def __str__(self):
        ref = self.balance_transaction.transaction_number if self.balance_transaction_id else "(pending)"
        return f"{ref} — {self.member.full_name} +{self.amount}"


class MemberEditHistory(models.Model):
    """Snapshot of a member's editable fields taken just before each profile update."""

    member = models.ForeignKey(
        'Member',
        on_delete=models.CASCADE,
        related_name='edit_history',
    )
    username = models.CharField(max_length=150, blank=True, null=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    rfid_card_number = models.CharField(max_length=50, null=True, blank=True)
    role = models.CharField(
        max_length=128,
        blank=True,
        help_text="Comma-separated role slugs at the time of the edit.",
    )

    edited_at = models.DateTimeField(auto_now_add=True)
    edited_by = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name = 'Member Edit History'
        verbose_name_plural = 'Member Edit Histories'
        ordering = ['-edited_at']

    def __str__(self):
        return f"Edit snapshot for {self.first_name} {self.last_name} at {self.edited_at}"


class DeletedMember(models.Model):
    """Record of deleted members for easy restoration."""
    # Store original member data
    original_id = models.IntegerField(help_text="Original member ID before deletion")
    rfid_card_number = models.CharField(max_length=50, null=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    member_type_name = models.CharField(max_length=100, blank=True, null=True)
    role = models.CharField(max_length=20)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    share_capital = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    username = models.CharField(max_length=150, blank=True, null=True)
    pin_hash = models.CharField(max_length=128, blank=True, null=True)
    
    # Metadata
    deleted_at = models.DateTimeField(auto_now_add=True)
    deleted_by = models.CharField(max_length=150, blank=True, null=True, help_text="Username of person who deleted")
    deletion_reason = models.TextField(blank=True, help_text="Optional reason for deletion")
    
    # Store original timestamps
    original_created_at = models.DateTimeField(null=True, blank=True)
    original_updated_at = models.DateTimeField(null=True, blank=True)
    original_date_joined = models.DateTimeField(null=True, blank=True)
    original_last_transaction = models.DateTimeField(null=True, blank=True)
    
    # Restoration tracking
    restored = models.BooleanField(default=False)
    restored_at = models.DateTimeField(null=True, blank=True)
    restored_by = models.CharField(max_length=150, blank=True, null=True)
    
    class Meta:
        verbose_name = "Deleted Member"
        verbose_name_plural = "Deleted Members"
        ordering = ['-deleted_at']
    
    def __str__(self):
        return f"Deleted: {self.first_name} {self.last_name} ({self.rfid_card_number}) - {self.deleted_at}"