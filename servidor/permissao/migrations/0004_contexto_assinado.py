# Contexto de RLS assinado (R12; ver permissao/contexto.py). O papel `app` fixa qualquer `app.*` na própria sessão,
# então a 0003 sozinha só protegia contra filtro esquecido na aplicação. Aqui a política passa a exigir
# `app.assinatura`, HMAC do número da transação e dos escopos, e `vinculos_da_pessoa` exige a assinatura da identidade.
# O segredo vem de `PHATI_SEGREDO_RLS` e fica em `rls_segredo`, que o `app` não lê. Escrita à mão.
#
# O valor do segredo entra no SQL desta migração: não rodar com `log_statement = all` no servidor.

import re
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

-- Os escopos já validados, para as políticas: a assinatura é conferida e as listas são lidas no mesmo instante, e a
-- política usa só o valor devolvido (um `InitPlan`, uma vez por consulta). Ler `app.empresas` de novo a cada linha
-- deixava um `set_config` volátil no WHERE trocar o escopo no meio da mesma consulta; chamar `app_contexto_ok()` por
-- linha fecharia a janela, mas custou cerca de 34 µs por linha (20 mil linhas: 18 ms viraram 700 ms). Assinatura
-- inválida não devolve linha: o `= ANY (NULL)` das políticas nega.
CREATE FUNCTION app_contexto(OUT de_plataforma boolean, OUT das_empresas bigint[], OUT empresas_das_fazendas bigint[],
    OUT das_fazendas bigint[])
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT coalesce(current_setting('app.plataforma', true), '') = '1',
        string_to_array(nullif(current_setting('app.empresas', true), ''), ',')::bigint[],
        string_to_array(nullif(current_setting('app.empresas_de_fazendas', true), ''), ',')::bigint[],
        string_to_array(nullif(current_setting('app.fazendas', true), ''), ',')::bigint[]
    WHERE public.app_contexto_ok()
$$;

CREATE FUNCTION app_identidade_ok(pessoa bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT coalesce(
        current_setting('app.assinatura_pessoa', true) = encode(hmac(convert_to(
            pg_current_xact_id()::text || '|' || pessoa::text, 'UTF8'),
            (SELECT valor FROM public.rls_segredo), 'sha256'), 'hex'),
        false)
$$;

-- Impressão (SHA-256) do segredo, para `permissao.checks` acusar PHATI_SEGREDO_RLS diferente do gravado; de um
-- segredo aleatório de 32 bytes o hash não devolve o segredo, e quem a chama não consegue assinar com ela.
CREATE FUNCTION app_segredo_impressao() RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT encode(sha256(valor), 'hex') FROM public.rls_segredo
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
# Variável da 0003 -> coluna de `app_contexto()`.
COLUNAS_DO_CONTEXTO = {
    'empresas': 'das_empresas', 'fazendas': 'das_fazendas', 'empresas_de_fazendas': 'empresas_das_fazendas',
}
LISTA = re.compile(r"app_lista_contem\('app\.(\w+)', (\"?\w+\"?)\)")  # a coluna pode vir entre aspas (`quote_name`)
PLATAFORMA_ASSINADA = '(SELECT de_plataforma FROM app_contexto())'


def _com_contexto(expressao):
    """A expressão da 0003 lendo os escopos validados de `app_contexto()` em vez das variáveis soltas."""
    # `ANY ((SELECT ...))` seria lido como subconsulta de linhas; o coalesce a torna expressão de array.
    return LISTA.sub(
        lambda m: f"{m[2]} = ANY (coalesce((SELECT {COLUNAS_DO_CONTEXTO[m[1]]} FROM app_contexto()), '{{}}'))", expressao
    )


def _politicas(schema_editor, assinadas):
    anterior = import_module('permissao.migrations.0003_rls')
    plataforma = PLATAFORMA_ASSINADA if assinadas else anterior.PLATAFORMA
    por_expressao = _com_contexto if assinadas else str
    for tabela, expressao in anterior.POLITICAS.items():
        schema_editor.execute(
            f'ALTER POLICY escopo ON {schema_editor.quote_name(tabela)} '
            f'USING ({plataforma} OR {por_expressao(expressao)})'
        )
    for tabela, coluna in anterior.LEITURA_POR_FAZENDA.items():
        leitura = f"app_lista_contem('app.empresas_de_fazendas', {schema_editor.quote_name(coluna)})"
        schema_editor.execute(
            f'ALTER POLICY leitura_por_fazenda ON {schema_editor.quote_name(tabela)} USING ({por_expressao(leitura)})'
        )


def criar(apps, schema_editor):
    app = schema_editor.quote_name(settings.DATABASES['app']['USER'])
    schema_editor.execute(SEGREDO)
    schema_editor.execute('INSERT INTO rls_segredo (id, valor) VALUES (1, %s)', [settings.SEGREDO_RLS])
    for instrucao in (
        # Tabela nova nasce com privilégio padrão para o `app` (comum 0001): tirar.
        f'REVOKE ALL ON rls_segredo FROM PUBLIC, {app}',
        'REVOKE ALL ON FUNCTION app_contexto_ok() FROM PUBLIC',
        'REVOKE ALL ON FUNCTION app_contexto() FROM PUBLIC',
        f'GRANT EXECUTE ON FUNCTION app_contexto() TO {app}',
        'REVOKE ALL ON FUNCTION app_identidade_ok(bigint) FROM PUBLIC',
        'REVOKE ALL ON FUNCTION app_segredo_impressao() FROM PUBLIC',
        f'GRANT EXECUTE ON FUNCTION app_segredo_impressao() TO {app}',
    ):
        schema_editor.execute(instrucao)
    _politicas(schema_editor, True)


def remover(apps, schema_editor):
    _politicas(schema_editor, False)
    antigas = import_module('permissao.migrations.0003_rls').FUNCOES
    vinculos = antigas[antigas.index('CREATE FUNCTION vinculos_da_pessoa'):]
    schema_editor.execute(vinculos.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1))
    schema_editor.execute('DROP FUNCTION app_contexto()')
    schema_editor.execute('DROP FUNCTION app_contexto_ok()')
    schema_editor.execute('DROP FUNCTION app_identidade_ok(bigint)')
    schema_editor.execute('DROP FUNCTION app_segredo_impressao()')
    schema_editor.execute('DROP TABLE rls_segredo')


class Migration(migrations.Migration):
    dependencies = [('permissao', '0003_rls')]
    operations = [migrations.RunPython(criar, remover)]
