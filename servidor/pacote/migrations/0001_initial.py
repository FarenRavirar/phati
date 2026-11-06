import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from psycopg import sql

import importlib

# Mesma leitura de escopo da tabela `concessao` (permissao 0003 e 0004): a plataforma, a empresa inteira ou a fazenda.
POLITICA = "app_lista_contem('app.empresas', empresa_id) OR app_lista_contem('app.fazendas', fazenda_id)"


def _comando(schema_editor, modelo, *partes):
    """Monta o SQL com `psycopg.sql`: identificador escapado de verdade e trecho fixo marcado como tal. `quote_name` do
    Django não escapa aspas dentro do nome (medido: `a"b` volta `"a"b"`) e o nome do papel vem de variável de ambiente."""
    return sql.SQL(modelo).format(*partes).as_string(schema_editor.connection.connection)


def papel_app(schema_editor):
    return _comando(schema_editor, '{}', sql.Identifier(settings.DATABASES['app']['USER']))


def proteger(apps, schema_editor):
    """RLS no molde da 001, privilégio mínimo e chave composta (004b R2, R20).

    O `app` só atualiza `vigente` e nunca apaga: `manifesto` e `numero` são imutáveis e o histórico fica (limpeza de versões
    antigas é outra rotina). A chave composta impede empresa e fazenda de andar separadas, como em `sub_area`."""
    contexto = importlib.import_module('permissao.migrations.0004_contexto_assinado')
    app = sql.Identifier(settings.DATABASES['app']['USER'])
    schema_editor.execute(
        'ALTER TABLE versao_pacote ADD CONSTRAINT versao_pacote_fazenda_da_empresa '
        'FOREIGN KEY (fazenda_id, empresa_id) REFERENCES fazenda (id, empresa_id)'
    )
    schema_editor.execute('ALTER TABLE versao_pacote ENABLE ROW LEVEL SECURITY')
    # Os argumentos de `format` não são reinterpretados: o `'{}'` dentro da expressão da política passa intacto.
    politica = _comando(
        schema_editor, 'CREATE POLICY escopo ON versao_pacote FOR ALL USING ({} OR {})',
        sql.SQL(contexto.PLATAFORMA_ASSINADA), sql.SQL(contexto._com_contexto(POLITICA)),
    )
    revogar = _comando(schema_editor, 'REVOKE UPDATE, DELETE, TRUNCATE ON versao_pacote FROM {}', app)
    conceder = _comando(schema_editor, 'GRANT UPDATE (vigente) ON versao_pacote TO {}', app)
    for comando in (politica, revogar, conceder):
        schema_editor.execute(comando)


def desproteger(apps, schema_editor):
    app = sql.Identifier(settings.DATABASES['app']['USER'])
    revogar = _comando(schema_editor, 'REVOKE UPDATE (vigente) ON versao_pacote FROM {}', app)
    conceder = _comando(schema_editor, 'GRANT UPDATE, DELETE, TRUNCATE ON versao_pacote TO {}', app)
    for comando in (revogar, conceder):
        schema_editor.execute(comando)
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
