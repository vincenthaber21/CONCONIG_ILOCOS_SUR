"""
Bulk export / import of all registered Django admin datasets.

Produces a ZIP of CSV (or XLSX) files — one per model — plus a media/ folder
for logos and product images, and can re-import them in FK-safe order.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from import_export.formats.base_formats import CSV, XLSX
from import_export.results import RowResult


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    group: str
    resource_factory: Callable
    importable: bool = True


def _get_datasets() -> list[Dataset]:
    """
    Ordered for import (parents before children).
    Lazy imports avoid circular app loading at module import time.
    """
    from admin_panel.resources import (
        KioskConfigResource,
        KioskSessionConfigResource,
        PrinterSettingsResource,
        ReportScheduleConfigResource,
        SentDailyReportResource,
        StoreProfileResource,
    )
    from inventory.resources import (
        CategoryResource,
        GiveawayProductResource,
        ProductDiscountGroupResource,
        ProductDiscountResource,
        ProductResource,
        ProductSaleUnitResource,
        ProductStockBatchResource,
        ProductStockHistoryResource,
        StockTransactionResource,
        TaxRateResource,
    )
    from members.resources import (
        BalanceTransactionResource,
        CardBalanceRefillResource,
        ConcessionDiscountPolicyResource,
        DeletedMemberResource,
        MemberEditHistoryResource,
        MemberResource,
        MemberTypeResource,
        PWDProfileResource,
        RoleResource,
        SegmentProductGroupDiscountResource,
        SeniorCitizenProfileResource,
    )
    from transactions.resources import (
        CreditPaymentLineResource,
        CreditPaymentResource,
        RefundReasonResource,
        RefundReturnWindowResource,
        TransactionItemResource,
        TransactionResource,
        WalkInCustomerProductDiscountResource,
        WalkInCustomerResource,
    )

    return [
        # ── Store / kiosk config (logo path + settings) ───────────────
        Dataset('admin_storeprofile', 'Store profile (logo)', 'Store & kiosk', StoreProfileResource),
        Dataset('admin_kioskconfig', 'Kiosk config', 'Store & kiosk', KioskConfigResource),
        Dataset(
            'admin_kiosksessionconfig',
            'Kiosk session config',
            'Store & kiosk',
            KioskSessionConfigResource,
        ),
        Dataset('admin_printersettings', 'Printer settings', 'Store & kiosk', PrinterSettingsResource),
        Dataset(
            'admin_reportscheduleconfig',
            'Report schedule config',
            'Store & kiosk',
            ReportScheduleConfigResource,
        ),
        Dataset('admin_sentdailyreport', 'Sent daily reports', 'Store & kiosk', SentDailyReportResource),
        # ── Inventory master ──────────────────────────────────────────
        Dataset('inventory_category', 'Categories', 'Inventory', CategoryResource),
        Dataset('inventory_taxrate', 'Tax rates', 'Inventory', TaxRateResource),
        Dataset(
            'inventory_productdiscountgroup',
            'Product discount groups',
            'Inventory',
            ProductDiscountGroupResource,
        ),
        Dataset('inventory_product', 'Products (incl. image paths)', 'Inventory', ProductResource),
        Dataset(
            'inventory_productsaleunit',
            'Product sale units',
            'Inventory',
            ProductSaleUnitResource,
        ),
        Dataset(
            'inventory_productstockbatch',
            'Product stock batches',
            'Inventory',
            ProductStockBatchResource,
        ),
        Dataset(
            'inventory_productdiscount',
            'Product discounts',
            'Inventory',
            ProductDiscountResource,
        ),
        Dataset(
            'inventory_giveawayproduct',
            'Giveaway products',
            'Inventory',
            GiveawayProductResource,
        ),
        Dataset(
            'inventory_stocktransaction',
            'Stock transactions',
            'Inventory',
            StockTransactionResource,
        ),
        Dataset(
            'inventory_productstockhistory',
            'Product stock history',
            'Inventory',
            ProductStockHistoryResource,
        ),
        # ── Members master ────────────────────────────────────────────
        Dataset('members_role', 'Roles', 'Members', RoleResource),
        Dataset('members_membertype', 'Member types', 'Members', MemberTypeResource),
        Dataset('members_member', 'Members', 'Members', MemberResource),
        Dataset(
            'members_seniorcitizenprofile',
            'Senior citizen profiles',
            'Members',
            SeniorCitizenProfileResource,
        ),
        Dataset('members_pwdprofile', 'PWD profiles', 'Members', PWDProfileResource),
        Dataset(
            'members_segmentproductgroupdiscount',
            'Segment product discounts',
            'Members',
            SegmentProductGroupDiscountResource,
        ),
        Dataset(
            'members_concessiondiscountpolicy',
            'Concession discount policies',
            'Members',
            ConcessionDiscountPolicyResource,
        ),
        Dataset(
            'members_balancetransaction',
            'Balance transactions',
            'Members',
            BalanceTransactionResource,
        ),
        Dataset(
            'members_cardbalancerefill',
            'Card balance refills',
            'Members',
            CardBalanceRefillResource,
        ),
        Dataset(
            'members_deletedmember',
            'Deleted members',
            'Members',
            DeletedMemberResource,
        ),
        Dataset(
            'members_memberedithistory',
            'Member edit history',
            'Members',
            MemberEditHistoryResource,
        ),
        # ── Sales / purchases / revenue ───────────────────────────────
        Dataset(
            'transactions_walkincustomer',
            'Walk-in customers',
            'Sales & revenue',
            WalkInCustomerResource,
        ),
        Dataset(
            'transactions_walkincustomerproductdiscount',
            'Walk-in product discounts',
            'Sales & revenue',
            WalkInCustomerProductDiscountResource,
        ),
        Dataset(
            'transactions_creditpayment',
            'Credit payments (utang settlements)',
            'Sales & revenue',
            CreditPaymentResource,
        ),
        Dataset(
            'transactions_transaction',
            'Transactions (purchases / revenue)',
            'Sales & revenue',
            TransactionResource,
        ),
        Dataset(
            'transactions_transactionitem',
            'Transaction line items',
            'Sales & revenue',
            TransactionItemResource,
        ),
        Dataset(
            'transactions_creditpaymentline',
            'Credit payment lines',
            'Sales & revenue',
            CreditPaymentLineResource,
        ),
        Dataset(
            'transactions_refundreason',
            'Refund reasons',
            'Sales & revenue',
            RefundReasonResource,
        ),
        Dataset(
            'transactions_refundreturnwindow',
            'Refund return windows',
            'Sales & revenue',
            RefundReturnWindowResource,
        ),
    ]


def get_datasets(keys: Iterable[str] | None = None) -> list[Dataset]:
    all_ds = _get_datasets()
    if keys is None:
        return all_ds
    key_set = set(keys)
    return [d for d in all_ds if d.key in key_set]


def dataset_row_counts(datasets: list[Dataset] | None = None) -> list[dict]:
    rows = []
    for ds in datasets or get_datasets():
        resource = ds.resource_factory()
        model = resource._meta.model
        rows.append(
            {
                'key': ds.key,
                'label': ds.label,
                'group': ds.group,
                'importable': ds.importable,
                'count': model.objects.count(),
            }
        )
    return rows


def _format_for(ext: str):
    ext = (ext or 'csv').lower().lstrip('.')
    if ext == 'xlsx':
        return XLSX()
    return CSV()


def _media_root() -> Path:
    return Path(getattr(settings, 'MEDIA_ROOT', '') or '')


def _pack_media_into_zip(zf: zipfile.ZipFile) -> list[str]:
    """Copy MEDIA_ROOT files into zip under media/. Returns arc names added."""
    root = _media_root()
    packed: list[str] = []
    if not root.is_dir():
        return packed
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        # Skip junk / temp
        if path.name.startswith('.') or path.suffix.lower() in {'.tmp', '.temp'}:
            continue
        rel = path.relative_to(root).as_posix()
        arcname = f'media/{rel}'
        zf.write(path, arcname)
        packed.append(arcname)
    return packed


def _restore_media_from_zip(zf: zipfile.ZipFile, dry_run: bool = False) -> dict:
    """Restore files from media/ entries in the ZIP into MEDIA_ROOT."""
    root = _media_root()
    restored = 0
    skipped = 0
    for name in zf.namelist():
        if not name.startswith('media/') or name.endswith('/'):
            continue
        rel = name[len('media/') :]
        if not rel or '..' in rel.split('/'):
            skipped += 1
            continue
        dest = root / rel
        if dry_run:
            restored += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(name) as src, open(dest, 'wb') as out:
            out.write(src.read())
        restored += 1
    return {'restored': restored, 'skipped': skipped}


def _prepare_import_payload(filename: str, raw: bytes):
    """
    ZIP entries are always bytes. tablib CSV expects a text string;
    XLSX expects bytes.
    """
    lower = filename.lower()
    if lower.endswith('.csv'):
        text = raw.decode('utf-8-sig')
        if not text.strip() or text.strip().count('\n') < 1:
            return CSV(), text
        return CSV(), text
    if lower.endswith('.xlsx'):
        return XLSX(), raw
    raise ValueError(f'Unsupported import file type: {filename}')


def _collect_import_errors(result, limit: int = 8) -> list[str]:
    msgs: list[str] = []
    for row in list(getattr(result, 'invalid_rows', []) or [])[:limit]:
        msgs.append(f'Row {getattr(row, "number", "?")}: {row.error}')
    row_errors = getattr(result, 'row_errors', None)
    try:
        items = row_errors() if callable(row_errors) else (row_errors or [])
    except Exception:
        items = []
    for item in list(items)[:limit]:
        msgs.append(str(item))
    for err in list(getattr(result, 'base_errors', []) or [])[:limit]:
        msgs.append(str(getattr(err, 'error', err)))
    return msgs


def build_export_zip(
    keys: Iterable[str] | None = None,
    file_format: str = 'csv',
    include_media: bool = True,
) -> tuple[bytes, str]:
    """
    Build a ZIP archive with one data file per selected dataset + manifest.json
    + optional media/ (store logo, product images, barcodes).
    """
    datasets = get_datasets(keys)
    fmt = _format_for(file_format)
    ext = fmt.get_title()
    buf = io.BytesIO()
    manifest = {
        'exported_at': timezone.now().isoformat(),
        'format': ext,
        'include_media': include_media,
        'datasets': [],
        'media_files': [],
    }

    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for ds in datasets:
            resource = ds.resource_factory()
            qs = resource.get_queryset()
            dataset = resource.export(queryset=qs)
            payload = fmt.export_data(dataset)
            if isinstance(payload, str):
                payload = payload.encode('utf-8')
            filename = f'{ds.key}.{ext}'
            zf.writestr(filename, payload)
            manifest['datasets'].append(
                {
                    'key': ds.key,
                    'label': ds.label,
                    'group': ds.group,
                    'file': filename,
                    'rows': qs.count(),
                    'importable': ds.importable,
                }
            )
        if include_media:
            manifest['media_files'] = _pack_media_into_zip(zf)
        zf.writestr(
            'manifest.json',
            json.dumps(manifest, indent=2, ensure_ascii=False),
        )

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'coop_kiosk_full_backup_{stamp}.zip'
    return buf.getvalue(), filename


def import_from_zip(
    zip_bytes: bytes,
    keys: Iterable[str] | None = None,
    dry_run: bool = False,
    restore_media: bool = True,
) -> list[dict]:
    """
    Import datasets from a ZIP produced by build_export_zip.
    Processes in registry order (FK-safe). Optionally restores media/ files.
    """
    selected = {d.key: d for d in get_datasets(keys)}

    def _run() -> list[dict]:
        results: list[dict] = []
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            names = set(zf.namelist())

            for ds in get_datasets():
                if ds.key not in selected:
                    continue
                if not ds.importable:
                    results.append(
                        {
                            'key': ds.key,
                            'label': ds.label,
                            'status': 'skipped',
                            'message': 'Export-only dataset (not imported).',
                            'totals': {},
                        }
                    )
                    continue

                csv_name = f'{ds.key}.csv'
                xlsx_name = f'{ds.key}.xlsx'
                if csv_name in names:
                    filename = csv_name
                elif xlsx_name in names:
                    filename = xlsx_name
                else:
                    results.append(
                        {
                            'key': ds.key,
                            'label': ds.label,
                            'status': 'missing',
                            'message': f'No {csv_name} or {xlsx_name} in ZIP.',
                            'totals': {},
                        }
                    )
                    continue

                raw = zf.read(filename)
                try:
                    fmt, payload = _prepare_import_payload(filename, raw)
                    if filename.lower().endswith('.csv'):
                        body = payload.strip().splitlines()
                        if len(body) <= 1:
                            results.append(
                                {
                                    'key': ds.key,
                                    'label': ds.label,
                                    'status': 'dry_run_ok' if dry_run else 'ok',
                                    'message': 'Empty table (header only) — nothing to import.',
                                    'totals': {
                                        'new': 0,
                                        'update': 0,
                                        'skip': 0,
                                        'error': 0,
                                        'delete': 0,
                                    },
                                    'file': filename,
                                }
                            )
                            continue
                    dataset = fmt.create_dataset(payload)
                except Exception as exc:
                    results.append(
                        {
                            'key': ds.key,
                            'label': ds.label,
                            'status': 'error',
                            'message': f'Could not read {filename}: {exc}',
                            'totals': {},
                        }
                    )
                    continue

                resource = ds.resource_factory()
                try:
                    result = resource.import_data(
                        dataset,
                        dry_run=False,
                        raise_errors=False,
                    )
                except Exception as exc:
                    results.append(
                        {
                            'key': ds.key,
                            'label': ds.label,
                            'status': 'error',
                            'message': str(exc),
                            'totals': {},
                        }
                    )
                    continue

                totals = {
                    'new': result.totals.get(RowResult.IMPORT_TYPE_NEW, 0),
                    'update': result.totals.get(RowResult.IMPORT_TYPE_UPDATE, 0),
                    'skip': result.totals.get(RowResult.IMPORT_TYPE_SKIP, 0),
                    'error': result.totals.get(RowResult.IMPORT_TYPE_ERROR, 0),
                    'delete': result.totals.get(RowResult.IMPORT_TYPE_DELETE, 0),
                }
                error_msgs = _collect_import_errors(result)
                has_errors = (
                    bool(result.has_errors())
                    or totals['error'] > 0
                    or bool(error_msgs)
                )

                if has_errors:
                    message = '; '.join(error_msgs) if error_msgs else 'Import reported errors.'
                    status = 'error'
                elif dry_run:
                    message = 'Dry-run OK — no changes saved.'
                    status = 'dry_run_ok'
                else:
                    message = 'Imported successfully.'
                    status = 'ok'

                results.append(
                    {
                        'key': ds.key,
                        'label': ds.label,
                        'status': status,
                        'message': message,
                        'totals': totals,
                        'file': filename,
                    }
                )

            if restore_media:
                media_info = _restore_media_from_zip(zf, dry_run=dry_run)
                n_files = media_info.get('restored', 0)
                if dry_run:
                    media_msg = 'Would restore {} file(s).'.format(n_files)
                    media_status = 'dry_run_ok'
                else:
                    media_msg = 'Restored {} file(s) into MEDIA_ROOT.'.format(n_files)
                    media_status = 'ok'
                results.append(
                    {
                        'key': '_media',
                        'label': 'Media files (logos & product images)',
                        'status': media_status,
                        'message': media_msg,
                        'totals': media_info,
                    }
                )
        return results

    if dry_run:
        with transaction.atomic():
            results = _run()
            transaction.set_rollback(True)
        return results

    return _run()
