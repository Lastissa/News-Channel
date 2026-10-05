from django.apps import AppConfig


class AdminConfig(AppConfig):
    name = 'ADMIN'

    def ready(self):
        from . import signals  # noqa: F401
