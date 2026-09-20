from django.apps import AppConfig


class LoansConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "loans"
    verbose_name = "Loans"

    def ready(self):
        # Connect FSM post_transition signal handlers.
        from . import signals  # noqa: F401
