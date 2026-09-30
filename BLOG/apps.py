from django.apps import AppConfig


class BlogConfig(AppConfig):
    name = 'BLOG'

    def ready(self):
        from . import signals  # noqa: F401
