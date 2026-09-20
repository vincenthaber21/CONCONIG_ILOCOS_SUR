import pymysql

pymysql.install_as_MySQLdb()

from coop_kiosk.celery import app as celery_app

__all__ = ('celery_app',)