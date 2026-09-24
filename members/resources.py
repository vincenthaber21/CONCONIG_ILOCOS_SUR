"""Import/export resources for member models (Django admin)."""

from import_export import fields, resources
from import_export.widgets import ForeignKeyWidget, ManyToManyWidget

from .models import (
    BalanceTransaction,
    CardBalanceRefill,
    ConcessionDiscountPolicy,
    DeletedMember,
    Member,
    MemberEditHistory,
    MemberStatus,
    MemberType,
    Nationality,
    ProjectCategory,
    PWDProfile,
    Role,
    SegmentProductGroupDiscount,
    SeniorCitizenProfile,
    ShareCapitalTransaction,
)
from inventory.models import Category, ProductDiscountGroup


class RoleResource(resources.ModelResource):
    class Meta:
        model = Role
        fields = ('id', 'slug', 'name', 'sort_order', 'is_active')
        export_order = fields
        import_id_fields = ('slug',)
        skip_unchanged = True
        report_skipped = True


class MemberStatusResource(resources.ModelResource):
    class Meta:
        model = MemberStatus
        fields = ('id', 'slug', 'name', 'sort_order', 'is_active')
        export_order = fields
        import_id_fields = ('slug',)
        skip_unchanged = True
        report_skipped = True


class MemberTypeResource(resources.ModelResource):
    class Meta:
        model = MemberType
        fields = ('id', 'name', 'description', 'is_active')
        export_order = fields
        import_id_fields = ('name',)
        skip_unchanged = True
        report_skipped = True


class NationalityResource(resources.ModelResource):
    class Meta:
        model = Nationality
        fields = ('id', 'slug', 'name', 'sort_order', 'is_active')
        export_order = fields
        import_id_fields = ('slug',)
        skip_unchanged = True
        report_skipped = True


class ProjectCategoryResource(resources.ModelResource):
    class Meta:
        model = ProjectCategory
        fields = ('id', 'slug', 'name', 'description', 'sort_order', 'is_active')
        export_order = fields
        import_id_fields = ('slug',)
        skip_unchanged = True
        report_skipped = True


class MemberResource(resources.ModelResource):
    """
    Bulk import/export members.
    Prefer matching on rfid_card_number when set; otherwise use id.
    pin_hash is excluded — set PINs via the admin form, not spreadsheet import.
    """

    member_type = fields.Field(
        column_name='member_type',
        attribute='member_type',
        widget=ForeignKeyWidget(MemberType, field='name'),
    )
    member_role = fields.Field(
        column_name='member_role',
        attribute='member_role',
        widget=ForeignKeyWidget(Role, field='slug'),
    )
    member_status = fields.Field(
        column_name='member_status',
        attribute='member_status',
        widget=ForeignKeyWidget(MemberStatus, field='slug'),
    )
    nationality = fields.Field(
        column_name='nationality',
        attribute='nationality',
        widget=ForeignKeyWidget(Nationality, field='slug'),
    )
    project_categories = fields.Field(
        column_name='project_categories',
        attribute='project_categories',
        widget=ManyToManyWidget(Category, field='name', separator=','),
    )

    class Meta:
        model = Member
        fields = (
            'id',
            'username',
            'rfid_card_number',
            'membership_number',
            'first_name',
            'middle_name',
            'last_name',
            'email',
            'phone',
            'place_of_birth',
            'home_address',
            'barangay',
            'municipality',
            'province',
            'date_of_birth',
            'age',
            'gender',
            'tin',
            'civil_status',
            'religion',
            'nationality',
            'educational_attainment',
            'occupation',
            'income_sources',
            'annual_income',
            'complete_business_name_address',
            'business_telephone',
            'business_cellular',
            'spouse_last_name',
            'spouse_first_name',
            'spouse_middle_name',
            'spouse_name',
            'spouse_age',
            'spouse_gender',
            'spouse_date_of_birth',
            'spouse_employer_business',
            'spouse_occupation',
            'spouse_employer_address',
            'spouse_telephone',
            'spouse_cellular',
            'approval_date',
            'approved_by',
            'recorded_by',
            'resolution_number',
            'project_categories',
            'coop_type',
            'area',
            'member_status',
            'membership_status',
            'location',
            'rsbsa_remarks',
            'rsbsa_number',
            'other_assets',
            'date_of_pmes',
            'date_accepted',
            'or_number',
            'initial_capital_paid_up',
            'date_of_mf_recog',
            'mf_center',
            'member_type',
            'member_role',
            'balance',
            'share_capital',
            'is_active',
            'inactive_remark',
            'date_joined',
        )
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        # MySQL unique nullable columns: empty string '' is NOT NULL and collides.
        for key in ('rfid_card_number', 'email', 'username', 'member_type', 'project_categories'):
            if key in row and (row[key] is None or str(row[key]).strip() == ''):
                row[key] = None

    def before_save_instance(self, instance, row, **kwargs):
        # CharWidget turns None into "" — force real NULLs for unique nullable fields.
        for attr in ('rfid_card_number', 'email', 'username'):
            if getattr(instance, attr, None) == '':
                setattr(instance, attr, None)


class SegmentProductGroupDiscountResource(resources.ModelResource):
    discount_group = fields.Field(
        column_name='discount_group',
        attribute='discount_group',
        widget=ForeignKeyWidget(ProductDiscountGroup, field='code'),
    )

    class Meta:
        model = SegmentProductGroupDiscount
        fields = (
            'id',
            'segment',
            'discount_group',
            'amount_off',
            'label',
            'is_active',
        )
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True


class SeniorCitizenProfileResource(resources.ModelResource):
    member = fields.Field(
        column_name='member_id',
        attribute='member',
        widget=ForeignKeyWidget(Member, field='id'),
    )

    class Meta:
        model = SeniorCitizenProfile
        fields = ('id', 'member', 'is_active', 'osca_id_number')
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True


class PWDProfileResource(resources.ModelResource):
    member = fields.Field(
        column_name='member_id',
        attribute='member',
        widget=ForeignKeyWidget(Member, field='id'),
    )

    class Meta:
        model = PWDProfile
        fields = ('id', 'member', 'is_active', 'pwd_id_number')
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True


class ConcessionDiscountPolicyResource(resources.ModelResource):
    class Meta:
        model = ConcessionDiscountPolicy
        fields = ('id', 'slug', 'discount_percent', 'is_active', 'notes')
        export_order = fields
        import_id_fields = ('slug',)
        skip_unchanged = True
        report_skipped = True


class BalanceTransactionResource(resources.ModelResource):
    member = fields.Field(
        column_name='member_id',
        attribute='member',
        widget=ForeignKeyWidget(Member, field='id'),
    )

    class Meta:
        model = BalanceTransaction
        fields = (
            'id',
            'transaction_number',
            'member',
            'transaction_type',
            'amount',
            'balance_before',
            'balance_after',
            'notes',
            'created_at',
        )
        export_order = fields
        import_id_fields = ('transaction_number',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        if 'notes' in row and row['notes'] is None:
            row['notes'] = ''


class ShareCapitalTransactionResource(resources.ModelResource):
    member = fields.Field(
        column_name='member_id',
        attribute='member',
        widget=ForeignKeyWidget(Member, field='id'),
    )

    class Meta:
        model = ShareCapitalTransaction
        fields = (
            'id',
            'transaction_number',
            'member',
            'transaction_type',
            'amount',
            'balance_before',
            'balance_after',
            'notes',
            'created_at',
        )
        export_order = fields
        import_id_fields = ('transaction_number',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        if 'notes' in row and row['notes'] is None:
            row['notes'] = ''


class CardBalanceRefillResource(resources.ModelResource):
    member = fields.Field(
        column_name='member_id',
        attribute='member',
        widget=ForeignKeyWidget(Member, field='id'),
    )

    class Meta:
        model = CardBalanceRefill
        fields = (
            'id',
            'member',
            'amount',
            'balance_before',
            'balance_after',
            'notes',
            'created_at',
        )
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        if 'notes' in row and row['notes'] is None:
            row['notes'] = ''


class DeletedMemberResource(resources.ModelResource):
    class Meta:
        model = DeletedMember
        fields = (
            'id',
            'original_id',
            'rfid_card_number',
            'first_name',
            'last_name',
            'email',
            'phone',
            'member_type_name',
            'role',
            'balance',
            'share_capital',
            'username',
            'deleted_at',
            'deleted_by',
            'restored',
        )
        export_order = fields
        import_id_fields = ('id',)


class MemberEditHistoryResource(resources.ModelResource):
    class Meta:
        model = MemberEditHistory
        fields = (
            'id',
            'member',
            'username',
            'first_name',
            'last_name',
            'email',
            'phone',
            'rfid_card_number',
            'role',
            'edited_at',
            'edited_by',
        )
        export_order = fields
        import_id_fields = ('id',)
