from django.contrib.admin.apps import AdminConfig
from django.contrib.staticfiles.apps import StaticFilesConfig


class ConfiguracaoDoPainel(AdminConfig):
    # O painel é o `PainelSite` (projeto/painel.py): login por CPF, sessão do R15 e RLS por requisição.
    default_site = 'projeto.painel.PainelSite'

    def ready(self):
        super().ready()
        # O `django.contrib.auth` registra `Group`, que usa o modelo de permissão do Django; aqui vale `pode()`.
        from django.contrib import admin
        from django.contrib.auth.models import Group

        admin.site.unregister(Group)


class ConfiguracaoDosEstaticos(StaticFilesConfig):
    # O teste de JS mora ao lado do script (par arquivo–teste); o `collectstatic` não o publica (Qodo, PR #19).
    ignore_patterns = [*StaticFilesConfig.ignore_patterns, '*.test.js']
