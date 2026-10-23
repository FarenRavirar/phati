from django.conf import settings
from django.db import migrations


def _alterar_privilegios_padrao(schema_editor, acao, preposicao):
    app = schema_editor.quote_name(settings.DATABASES['app']['USER'])
    # Vale para as tabelas e sequências que o dono criar daqui em diante; por isso esta migração
    # vem antes das demais. Auditoria (Fase 4) restringe depois para só INSERT e SELECT.
    schema_editor.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public {acao} SELECT, INSERT, UPDATE, DELETE ON TABLES {preposicao} {app}'
    )
    schema_editor.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public {acao} USAGE, SELECT ON SEQUENCES {preposicao} {app}')


def conceder(apps, schema_editor):
    _alterar_privilegios_padrao(schema_editor, 'GRANT', 'TO')


def revogar(apps, schema_editor):
    _alterar_privilegios_padrao(schema_editor, 'REVOKE', 'FROM')


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.RunPython(conceder, revogar)]
