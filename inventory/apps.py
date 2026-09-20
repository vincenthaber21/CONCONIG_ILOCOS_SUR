from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inventory'
    
    def ready(self):
        import inventory.signals
        _patch_django_context_copy()


def _patch_django_context_copy():
    """
    Django 4.2 uses copy(super()) inside BaseContext.__copy__, which breaks
    on Python 3.14 because super() objects no longer support attribute
    assignment via copy().  Patch it to use a plain __dict__ copy instead.
    """
    import sys
    if sys.version_info < (3, 14):
        return

    from django.template.context import BaseContext

    if getattr(BaseContext, '_py314_patched', False):
        return

    def _fixed_copy(self):
        duplicate = self.__class__.__new__(self.__class__)
        duplicate.__dict__ = self.__dict__.copy()
        duplicate.dicts = self.dicts[:]
        return duplicate

    BaseContext.__copy__ = _fixed_copy
    BaseContext._py314_patched = True