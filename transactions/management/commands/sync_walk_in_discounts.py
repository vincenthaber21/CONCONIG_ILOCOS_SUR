from django.core.management.base import BaseCommand

from transactions.models import WalkInCustomer
from transactions.walk_in_customers import sync_walk_in_customer_discounts


class Command(BaseCommand):
    help = 'Rebuild walk-in per-product manual discount totals from completed sales.'

    def handle(self, *args, **options):
        count = 0
        for customer in WalkInCustomer.objects.iterator():
            sync_walk_in_customer_discounts(customer)
            count += 1
        self.stdout.write(self.style.SUCCESS(f'Synced discount totals for {count} walk-in customer(s).'))
