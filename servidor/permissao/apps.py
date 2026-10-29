from django.apps import AppConfig


class AplicacaoPermissao(AppConfig):
    name = 'permissao'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from permissao import checks  # noqa: F401  (o import registra a verificação)
