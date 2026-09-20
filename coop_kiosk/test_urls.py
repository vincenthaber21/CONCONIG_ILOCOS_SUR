from django.urls import include, path

urlpatterns = [
    path('api/ingest/', include('ingestion.urls')),
]
