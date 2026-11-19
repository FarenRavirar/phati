from django.apps import AppConfig


class AplicacaoCatalogo(AppConfig):
    """Catálogo e ingestão de camadas (spec 008): estudo, camada, versão e feição."""
    name = 'catalogo'
    default_auto_field = 'django.db.models.BigAutoField'
