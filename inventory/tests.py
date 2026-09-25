from decimal import Decimal

from django.test import TestCase

from admin_panel.views import _apply_product_stock_batches
from inventory.models import Product, ProductStockBatch
from inventory.pricing import deduct_stock_batches, fifo_line_gross


class ExtraNewStockBatchTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name='Rice',
            barcode='EXTRA-NEW-1',
            price=Decimal('10.00'),
            cost=Decimal('5.00'),
            stock_quantity=Decimal('30'),
        )
        ProductStockBatch.objects.create(
            product=self.product,
            tier=ProductStockBatch.TIER_OLD,
            quantity=Decimal('10'),
            unit_price=Decimal('10.00'),
            cost=Decimal('4.00'),
        )
        ProductStockBatch.objects.create(
            product=self.product,
            tier=ProductStockBatch.TIER_NEW,
            sequence=0,
            quantity=Decimal('8'),
            unit_price=Decimal('12.00'),
            cost=Decimal('6.00'),
        )
        ProductStockBatch.objects.create(
            product=self.product,
            tier=ProductStockBatch.TIER_NEW,
            sequence=1,
            quantity=Decimal('12'),
            unit_price=Decimal('15.00'),
            cost=Decimal('7.00'),
        )

    def test_fifo_sells_old_then_each_new_batch(self):
        # 10×10 + 8×12 + 2×15
        self.assertEqual(fifo_line_gross(self.product, 20), Decimal('226.00'))

    def test_deduct_promotes_first_new_and_keeps_later_batch(self):
        deduct_stock_batches(self.product, 10)
        self.product.refresh_from_db()
        old = self.product.old_stock_batch
        self.assertEqual(old.quantity, Decimal('8.000'))
        self.assertEqual(old.unit_price, Decimal('12.00'))
        self.assertEqual(self.product.price, Decimal('12.00'))
        new = self.product.new_stock_batch
        self.assertEqual(new.sequence, 0)
        self.assertEqual(new.quantity, Decimal('12.000'))
        self.assertEqual(new.unit_price, Decimal('15.00'))
        self.assertEqual(self.product.extra_new_stocks_payload(), [])

    def test_apply_form_saves_extra_new_stock_rows(self):
        data = {
            'old_stock_quantity': '4',
            'old_stock_price': '10.00',
            'old_stock_cost': '4.00',
            'new_stock_quantity': '3',
            'new_stock_price': '12.00',
            'new_stock_cost': '6.00',
            'extra_new_stocks': (
                '[{"quantity":"5","selling_price":"15.00","buying_price":"7.00"},'
                '{"quantity":"2","selling_price":"18.00","buying_price":"8.00"}]'
            ),
        }
        total = _apply_product_stock_batches(
            self.product,
            data.get,
            default_price=Decimal('12.00'),
            default_cost=Decimal('6.00'),
        )
        self.assertEqual(total, Decimal('14'))
        batches = list(
            ProductStockBatch.objects.filter(
                product=self.product,
                tier=ProductStockBatch.TIER_NEW,
            ).order_by('sequence')
        )
        self.assertEqual(len(batches), 3)
        self.assertEqual(batches[1].quantity, Decimal('5.000'))
        self.assertEqual(batches[1].unit_price, Decimal('15.00'))
        self.assertEqual(batches[1].cost, Decimal('7.00'))
        self.assertEqual(batches[2].sequence, 2)
        self.assertEqual(len(self.product.extra_new_stocks_payload()), 2)
