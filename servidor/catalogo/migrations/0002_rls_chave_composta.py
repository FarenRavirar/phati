# Empresa e fazenda desnormalizadas nas tabelas do catálogo, chave composta e RLS (008 R11, R13; D115).
#
# Consistência pelo banco, sem gatilho: cada filho referencia o pai por (id, empresa_id, fazenda_id), então uma
# camada não fica com empresa ou fazenda diferente do estudo. RLS no molde de `permissao/migrations/0003_rls.py` e
# `0004_contexto_assinado.py`: a política lê o escopo validado de `app_contexto()`, com assinatura.
#
# Sem dado real: a migração supõe tabelas vazias (catálogo ainda não usado). O `default=1` do AddField só serve para o
# ADD COLUMN NOT NULL em tabela vazia; em tabela com linhas falharia, por isso a 0002 não roda na VM sem backup.

import importlib

from django.conf import settings
from django.db import migrations, models
from psycopg import sql

import django.db.models.deletion

contexto = importlib.import_module('permissao.migrations.0004_contexto_assinado')

# Mesma leitura de escopo das tabelas com empresa e fazenda: a empresa inteira ou a fazenda.
POLITICA_POR_FAZENDA = "app_lista_contem('app.empresas', empresa_id) OR app_lista_contem('app.fazendas', fazenda_id)"
POLITICA_POR_EMPRESA = "app_lista_contem('app.empresas', empresa_id)"

TABELAS_COM_FAZENDA = (
    'catalogo_estudo', 'catalogo_camada', 'catalogo_versao_camada', 'catalogo_atributo_versao',
    'catalogo_feicao', 'catalogo_envio_camada',
)
TABELAS_POR_EMPRESA = ('catalogo_tema',)

# FK composta: filho -> pai, pelas três colunas.
CHAVES_COMPOSTAS = (
    ('catalogo_camada', 'camada_estudo_da_empresa', '(estudo_id, empresa_id, fazenda_id)', 'catalogo_estudo'),
    ('catalogo_versao_camada', 'versao_camada_da_camada', '(camada_id, empresa_id, fazenda_id)', 'catalogo_camada'),
    ('catalogo_atributo_versao', 'atributo_da_versao', '(versao_id, empresa_id, fazenda_id)', 'catalogo_versao_camada'),
    ('catalogo_feicao', 'feicao_da_versao', '(versao_id, empresa_id, fazenda_id)', 'catalogo_versao_camada'),
)


def _app():
    return sql.Identifier(settings.DATABASES['app']['USER'])


def _politicas_e_grants(schema_editor):
    app = _app()
    for tabela in TABELAS_COM_FAZENDA + TABELAS_POR_EMPRESA:
        expressao = POLITICA_POR_EMPRESA if tabela in TABELAS_POR_EMPRESA else POLITICA_POR_FAZENDA
        expressao = contexto._com_contexto(expressao)
        nome = schema_editor.quote_name(tabela)
        schema_editor.execute(f'ALTER TABLE {nome} ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(
            f'CREATE POLICY escopo ON {nome} FOR ALL USING ({contexto.PLATAFORMA_ASSINADA} OR {expressao})'
        )
        schema_editor.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}').format(
            sql.Identifier(tabela), app).as_string(schema_editor.connection.connection))
        schema_editor.execute(sql.SQL('GRANT USAGE, SELECT ON SEQUENCE {} TO {}').format(
            sql.Identifier(f'{tabela}_id_seq'), app).as_string(schema_editor.connection.connection))


def _desfazer_politicas(schema_editor):
    for tabela in TABELAS_COM_FAZENDA + TABELAS_POR_EMPRESA:
        nome = schema_editor.quote_name(tabela)
        schema_editor.execute(f'DROP POLICY escopo ON {nome}')
        schema_editor.execute(f'ALTER TABLE {nome} DISABLE ROW LEVEL SECURITY')


def criar_chaves_compostas(apps, schema_editor):
    # Chave pai: `estudo`, `camada` e `versao_camada` ganham `UNIQUE (id, empresa_id, fazenda_id)` nas operações acima.
    for tabela, nome, colunas, pai in CHAVES_COMPOSTAS:
        schema_editor.execute(
            f'ALTER TABLE {schema_editor.quote_name(tabela)} ADD CONSTRAINT {schema_editor.quote_name(nome)} '
            f'FOREIGN KEY {colunas} REFERENCES {schema_editor.quote_name(pai)} (id, empresa_id, fazenda_id)'
        )
    # Envio: fazenda e empresa como na chave do pacote (`fazenda (id, empresa_id)`, pacote 0001).
    schema_editor.execute(
        'ALTER TABLE catalogo_envio_camada ADD CONSTRAINT envio_fazenda_da_empresa '
        'FOREIGN KEY (fazenda_id, empresa_id) REFERENCES fazenda (id, empresa_id)'
    )


def remover_chaves_compostas(apps, schema_editor):
    schema_editor.execute('ALTER TABLE catalogo_envio_camada DROP CONSTRAINT envio_fazenda_da_empresa')
    for tabela, nome, _colunas, _pai in reversed(CHAVES_COMPOSTAS):
        schema_editor.execute(f'ALTER TABLE {schema_editor.quote_name(tabela)} DROP CONSTRAINT {schema_editor.quote_name(nome)}')


def politicas(apps, schema_editor):
    _politicas_e_grants(schema_editor)


def remover_politicas(apps, schema_editor):
    _desfazer_politicas(schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0001_initial'),
        ('permissao', '0004_contexto_assinado'),
        ('territorio', '0006_nome_ativo_unico'),
    ]

    operations = [
        migrations.AddField(
            model_name='camada', name='empresa',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='territorio.empresa'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='camada', name='fazenda',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='territorio.fazenda'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='versaocamada', name='empresa',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='territorio.empresa'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='versaocamada', name='fazenda',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='territorio.fazenda'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='atributoversao', name='empresa',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='territorio.empresa'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='atributoversao', name='fazenda',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='territorio.fazenda'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='feicao', name='empresa',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='territorio.empresa'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='feicao', name='fazenda',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='territorio.fazenda'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='enviocamada', name='empresa',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='territorio.empresa'),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name='estudo',
            constraint=models.UniqueConstraint(fields=('id', 'empresa', 'fazenda'), name='estudo_chave_composta'),
        ),
        migrations.AddConstraint(
            model_name='camada',
            constraint=models.UniqueConstraint(fields=('id', 'empresa', 'fazenda'), name='camada_chave_composta'),
        ),
        migrations.AddConstraint(
            model_name='versaocamada',
            constraint=models.UniqueConstraint(fields=('id', 'empresa', 'fazenda'), name='versao_camada_chave_composta'),
        ),
        migrations.RunPython(criar_chaves_compostas, remover_chaves_compostas),
        migrations.RunPython(politicas, remover_politicas),
    ]
