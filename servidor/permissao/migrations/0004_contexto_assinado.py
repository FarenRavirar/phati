# Contexto de RLS assinado (R12; ver permissao/contexto.py). O papel `app` fixa qualquer `app.*` na própria sessão,
# então a 0003 sozinha só protegia contra filtro esquecido na aplicação. Aqui a política passa a exigir
# `app.assinatura`, HMAC do número da transação e dos escopos, e `vinculos_da_pessoa` exige a assinatura da identidade.
# O segredo vem de `PHATI_SEGREDO_RLS` e fica em `rls_segredo`, que o `app` não lê. Escrita à mão.
#
# O valor do segredo entra no SQL desta migração: não rodar com `log_statement = all` no servidor.

from importlib import import_module

from django.conf import settings
from django.db import migrations

SEGREDO = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE rls_segredo (
    id smallint PRIMARY KEY CHECK (id = 1),
    valor bytea NOT NULL CHECK (octet_length(valor) = 32)
);

-- Mesma ordem e separador de `contexto._assinar`. Falta de variável ou de assinatura dá NULL, tratado como falso.
CREATE FUNCTION app_contexto_ok() RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT coalesce(
        current_setting('app.assinatura', true) = encode(hmac(convert_to(
            pg_current_xact_id()::text || '|' || coalesce(current_setting('app.plataforma', true), '')
            || '|' || coalesce(current_setting('app.empresas', true), '')
            || '|' || coalesce(current_setting('app.empresas_de_fazendas', true), '')
            || '|' || coalesce(current_setting('app.fazendas', true), ''), 'UTF8'),
            (SELECT valor FROM public.rls_segredo), 'sha256'), 'hex'),
        false)
$$;

CREATE FUNCTION app_identidade_ok(pessoa bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT coalesce(
        current_setting('app.assinatura_pessoa', true) = encode(hmac(convert_to(
            pg_current_xact_id()::text || '|' || pessoa::text, 'UTF8'),
            (SELECT valor FROM public.rls_segredo), 'sha256'), 'hex'),
        false)
$$;

-- Como na 0003, mais a exigência de que a pessoa pedida seja a de identidade assinada pela aplicação.
CREATE OR REPLACE FUNCTION vinculos_da_pessoa(pessoa bigint, agora timestamptz) RETURNS TABLE (
    concessao_id bigint, empresa_id bigint, fazenda_id bigint, sub_area_id bigint, fim timestamptz,
    base text, permissoes text[], categorias bigint[]
) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT k.id, k.empresa_id, k.fazenda_id, k.sub_area_id, k.fim, c.base,
        ARRAY(SELECT cp.permissao_id FROM public.cargo_permissao cp WHERE cp.cargo_id = c.id),
        ARRAY(SELECT cc.categoria_id FROM public.concessao_categoria cc WHERE cc.concessao_id = k.id)
    FROM public.concessao k JOIN public.cargo c ON c.id = k.cargo_id
    WHERE public.app_identidade_ok(pessoa) AND k.pessoa_id = pessoa AND k.revogada_em IS NULL
        AND k.inicio <= agora AND (k.fim IS NULL OR k.fim > agora)
$$;
"""
GUARDA = '(SELECT app_contexto_ok()) AND '


def _politicas(schema_editor, guarda):
    anterior = import_module('permissao.migrations.0003_rls')
    for tabela, expressao in anterior.POLITICAS.items():
        schema_editor.execute(
            f'ALTER POLICY escopo ON {schema_editor.quote_name(tabela)} '
            f'USING ({guarda}({anterior.PLATAFORMA} OR {expressao}))'
        )
    for tabela, coluna in anterior.LEITURA_POR_FAZENDA.items():
        schema_editor.execute(
            f'ALTER POLICY leitura_por_fazenda ON {schema_editor.quote_name(tabela)} '
            f"USING ({guarda}app_lista_contem('app.empresas_de_fazendas', {schema_editor.quote_name(coluna)}))"
        )


def criar(apps, schema_editor):
    app = schema_editor.quote_name(settings.DATABASES['app']['USER'])
    schema_editor.execute(SEGREDO)
    schema_editor.execute('INSERT INTO rls_segredo (id, valor) VALUES (1, %s)', [settings.SEGREDO_RLS])
    for instrucao in (
        # Tabela nova nasce com privilégio padrão para o `app` (comum 0001): tirar.
        f'REVOKE ALL ON rls_segredo FROM PUBLIC, {app}',
        'REVOKE ALL ON FUNCTION app_contexto_ok() FROM PUBLIC',
        f'GRANT EXECUTE ON FUNCTION app_contexto_ok() TO {app}',
        'REVOKE ALL ON FUNCTION app_identidade_ok(bigint) FROM PUBLIC',
    ):
        schema_editor.execute(instrucao)
    _politicas(schema_editor, GUARDA)


def remover(apps, schema_editor):
    _politicas(schema_editor, '')
    antigas = import_module('permissao.migrations.0003_rls').FUNCOES
    vinculos = antigas[antigas.index('CREATE FUNCTION vinculos_da_pessoa'):]
    schema_editor.execute(vinculos.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1))
    schema_editor.execute('DROP FUNCTION app_contexto_ok()')
    schema_editor.execute('DROP FUNCTION app_identidade_ok(bigint)')
    schema_editor.execute('DROP TABLE rls_segredo')


class Migration(migrations.Migration):
    dependencies = [('permissao', '0003_rls')]
    operations = [migrations.RunPython(criar, remover)]
