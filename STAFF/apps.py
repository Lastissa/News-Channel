from django.apps import AppConfig


class StaffConfig(AppConfig):
    name = 'STAFF'

    def ready(self):
        from . import signals  # noqa: F401
