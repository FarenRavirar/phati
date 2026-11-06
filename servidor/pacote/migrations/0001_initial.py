import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from psycopg import sql

import importlib

# Mesma leitura de escopo da tabela `concessao` (permissao 0003 e 0004): a plataforma, a empresa inteira ou a fazenda.
POLITICA = "app_lista_contem('app.empresas', empresa_id) OR app_lista_contem('app.fazendas', fazenda_id)"


def papel_app(schema_editor):
    """Nome do papel `app` como identificador SQL escapado. `quote_name` do Django não escapa aspas dentro do nome
    (medido: `a"b` volta `"a"b"`), e o nome vem de variável de ambiente; `psycopg.sql.Identifier` escapa de verdade."""
    return sql.Identifier(settings.DATABASES['app']['USER']).as_string(schema_editor.connection.connection)


def proteger(apps, schema_editor):
    """RLS no molde da 001, privilégio mínimo e chave composta (004b R2, R20).

    O `app` só atualiza `vigente` e nunca apaga: `manifesto` e `numero` são imutáveis e o histórico fica (limpeza de versões
    antigas é outra rotina). A chave composta impede empresa e fazenda de andar separadas, como em `sub_area`."""
    contexto = importlib.import_module('permissao.migrations.0004_contexto_assinado')
    app = papel_app(schema_editor)
    schema_editor.execute(
        'ALTER TABLE versao_pacote ADD CONSTRAINT versao_pacote_fazenda_da_empresa '
        'FOREIGN KEY (fazenda_id, empresa_id) REFERENCES fazenda (id, empresa_id)'
    )
    schema_editor.execute('ALTER TABLE versao_pacote ENABLE ROW LEVEL SECURITY')
    schema_editor.execute(
        f'CREATE POLICY escopo ON versao_pacote FOR ALL USING ({contexto.PLATAFORMA_ASSINADA} OR {contexto._com_contexto(POLITICA)})'
    )
    schema_editor.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON versao_pacote FROM {app}')
    schema_editor.execute(f'GRANT UPDATE (vigente) ON versao_pacote TO {app}')


def desproteger(apps, schema_editor):
    app = papel_app(schema_editor)
    schema_editor.execute(f'REVOKE UPDATE (vigente) ON versao_pacote FROM {app}')
    schema_editor.execute(f'GRANT UPDATE, DELETE, TRUNCATE ON versao_pacote TO {app}')
    schema_editor.execute('DROP POLICY escopo ON versao_pacote')
    schema_editor.execute('ALTER TABLE versao_pacote DISABLE ROW LEVEL SECURITY')
    schema_editor.execute('ALTER TABLE versao_pacote DROP CONSTRAINT versao_pacote_fazenda_da_empresa')


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('territorio', '0006_nome_ativo_unico'),
        ('permissao', '0004_contexto_assinado'),
    ]

    operations = [
        migrations.CreateModel(
            name='VersaoPacote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('numero', models.PositiveIntegerField()),
                ('gerado_em', models.DateTimeField(auto_now_add=True)),
                ('manifesto', models.JSONField()),
                ('vigente', models.BooleanField(default=False)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='territorio.empresa')),
                ('fazenda', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='territorio.fazenda')),
            ],
            options={
                'db_table': 'versao_pacote',
                'constraints': [models.UniqueConstraint(fields=('fazenda', 'numero'), name='versao_pacote_numero_unico'), models.UniqueConstraint(condition=models.Q(('vigente', True)), fields=('fazenda',), name='versao_pacote_uma_vigente'), models.CheckConstraint(condition=models.Q(('numero__gte', 1)), name='versao_pacote_numero_positivo')],
            },
        ),
        migrations.RunPython(proteger, desproteger),
    ]
