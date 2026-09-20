from django.urls import path

from ingestion import views

app_name = 'ingestion'

urlpatterns = [
    path('', views.ingest_rows, name='ingest'),
]
