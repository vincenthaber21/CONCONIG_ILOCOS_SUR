"""Django admin views for bulk data export / import."""

from __future__ import annotations

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.views.decorators.http import require_http_methods

from admin_panel.data_transfer import (
    build_export_zip,
    dataset_row_counts,
    get_datasets,
    import_from_zip,
)
from helper.login_helper import can_access_django_admin


def _deny_if_unauthorized(request):
    if not request.user.is_authenticated or not can_access_django_admin(request.user):
        return HttpResponseForbidden('You do not have permission to access this page.')
    return None


@staff_member_required
@require_http_methods(['GET', 'POST'])
def data_transfer_view(request):
    denied = _deny_if_unauthorized(request)
    if denied:
        return denied

    datasets = dataset_row_counts()
    groups: dict[str, list] = {}
    for row in datasets:
        groups.setdefault(row['group'], []).append(row)

    import_results = None

    if request.method == 'POST':
        action = request.POST.get('action')
        selected = request.POST.getlist('datasets')
        if not selected:
            selected = [d.key for d in get_datasets()]

        if action == 'export':
            file_format = request.POST.get('file_format', 'csv')
            include_media = request.POST.get('include_media') == '1'
            zip_bytes, filename = build_export_zip(
                selected,
                file_format=file_format,
                include_media=include_media,
            )
            response = HttpResponse(zip_bytes, content_type='application/zip')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        if action == 'import':
            upload = request.FILES.get('import_file')
            dry_run = request.POST.get('dry_run') == '1'
            restore_media = request.POST.get('restore_media') == '1'
            if not upload:
                messages.error(request, 'Please choose a ZIP file to import.')
            elif not upload.name.lower().endswith('.zip'):
                messages.error(request, 'Import file must be a .zip export from this page.')
            else:
                try:
                    import_results = import_from_zip(
                        upload.read(),
                        keys=selected,
                        dry_run=dry_run,
                        restore_media=restore_media,
                    )
                    ok = sum(1 for r in import_results if r['status'] in ('ok', 'dry_run_ok'))
                    err = sum(1 for r in import_results if r['status'] == 'error')
                    if err:
                        failed = ', '.join(
                            r['label'] for r in import_results if r['status'] == 'error'
                        )
                        messages.warning(
                            request,
                            f'Import finished with {err} error(s). {ok} dataset(s) OK. '
                            f'Failed: {failed}. See details in the results table below.',
                        )
                    elif dry_run:
                        messages.info(
                            request,
                            f'Dry-run complete — {ok} dataset(s) would import. Nothing was saved.',
                        )
                    else:
                        messages.success(
                            request,
                            f'Import complete — {ok} dataset(s) imported successfully.',
                        )
                except Exception as exc:
                    messages.error(request, f'Import failed: {exc}')

    context = {
        **admin.site.each_context(request),
        'title': 'Export / Import all database data',
        'groups': groups,
        'total_rows': sum(r['count'] for r in datasets),
        'import_results': import_results,
        'data_transfer_url': reverse('admin_data_transfer'),
    }
    return render(request, 'admin/data_transfer.html', context)


def get_data_transfer_urls():
    """URL patterns to mount before admin.site.urls."""
    return [
        path(
            'admin/data-transfer/',
            admin.site.admin_view(data_transfer_view),
            name='admin_data_transfer',
        ),
    ]
