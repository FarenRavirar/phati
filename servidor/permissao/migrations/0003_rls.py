# Segunda barreira no banco (R12; plan.md §Camada de banco — RLS). Escrita à mão: política, função e gatilho.
#
# Variáveis de transação que `permissao.pode.com_permissao` fixa com `set_config(..., true)`:
#   app.plataforma ('1' ou vazio), app.empresas e app.fazendas (listas de ids separados por vírgula).
# Sem variável, `current_setting(..., true)` devolve NULL ou '' e nenhuma linha passa. O dono das tabelas
# (papel das migrações) ignora a RLS porque não há FORCE; o papel `app` não é dono e não tem BYPASSRLS.

from django.conf import settings
from django.db import migrations

TABELAS_POR_EMPRESA = ('nivel_divisao', 'cargo', 'categoria_dado')
PLATAFORMA = "coalesce(current_setting('app.plataforma', true), '') = '1'"

# Uma política `FOR ALL` por tabela: o `USING` vale também de `WITH CHECK`, então INSERT e UPDATE em linha fora
# do escopo falham. `empresa` só abre por empresa inteira; fazenda, sub-área e concessão abrem também por fazenda.
POLITICAS = {
    'empresa': "app_lista_contem('app.empresas', id)",
    'fazenda': "app_lista_contem('app.empresas', empresa_id) OR app_lista_contem('app.fazendas', id)",
    'sub_area': "app_lista_contem('app.empresas', empresa_id) OR app_lista_contem('app.fazendas', fazenda_id)",
    'concessao': "app_lista_contem('app.empresas', empresa_id) OR app_lista_contem('app.fazendas', fazenda_id)",
    **{tabela: "app_lista_contem('app.empresas', empresa_id)" for tabela in TABELAS_POR_EMPRESA},
}

FUNCOES = """
-- Id está na lista da variável? Variável ausente ou vazia vira NULL, que a política trata como negado (o cast de
-- '' para bigint daria erro em vez de zero linhas).
CREATE FUNCTION app_lista_contem(variavel text, valor bigint) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT valor = ANY (string_to_array(nullif(current_setting(variavel, true), ''), ',')::bigint[])
$$;

-- Bootstrap de `pode()`: as concessões ativas da própria pessoa, com a base e as permissões do cargo e as
-- categorias, lidas sem depender das variáveis (que `pode()` ainda vai calcular a partir delas). SECURITY DEFINER
-- devolve só as linhas da pessoa pedida; quem chama já foi autenticado pela aplicação.
CREATE FUNCTION vinculos_da_pessoa(pessoa bigint, agora timestamptz) RETURNS TABLE (
    concessao_id bigint, empresa_id bigint, fazenda_id bigint, sub_area_id bigint, fim timestamptz,
    base text, permissoes text[], categorias bigint[]
) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT k.id, k.empresa_id, k.fazenda_id, k.sub_area_id, k.fim, c.base,
        ARRAY(SELECT cp.permissao_id FROM public.cargo_permissao cp WHERE cp.cargo_id = c.id),
        ARRAY(SELECT cc.categoria_id FROM public.concessao_categoria cc WHERE cc.concessao_id = k.id)
    FROM public.concessao k JOIN public.cargo c ON c.id = k.cargo_id
    WHERE k.pessoa_id = pessoa AND k.revogada_em IS NULL AND k.inicio <= agora AND (k.fim IS NULL OR k.fim > agora)
$$;
"""

# Os gatilhos que consultam tabela com RLS rodam como o dono: com o papel de quem chama, a linha que a RLS esconde
# faria `concessao_validar` aprovar o que deveria barrar (a regra do titular, R23) e `concessao_categoria_validar`
# recusar categoria legítima.
GATILHOS_COMO_DONO = ('concessao_validar', 'concessao_categoria_validar')


def _executar(schema_editor, instrucoes):
    for instrucao in instrucoes:
        schema_editor.execute(instrucao)


def criar(apps, schema_editor):
    app = schema_editor.quote_name(settings.DATABASES['app']['USER'])
    schema_editor.execute(FUNCOES)
    _executar(schema_editor, [
        'REVOKE ALL ON FUNCTION vinculos_da_pessoa(bigint, timestamptz) FROM PUBLIC',
        f'GRANT EXECUTE ON FUNCTION vinculos_da_pessoa(bigint, timestamptz) TO {app}',
        'REVOKE ALL ON FUNCTION app_lista_contem(text, bigint) FROM PUBLIC',
        f'GRANT EXECUTE ON FUNCTION app_lista_contem(text, bigint) TO {app}',
    ])
    _executar(schema_editor, [f'ALTER FUNCTION {nome}() SECURITY DEFINER' for nome in GATILHOS_COMO_DONO])
    for tabela, expressao in POLITICAS.items():
        schema_editor.execute(f'ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'CREATE POLICY escopo ON {tabela} FOR ALL USING ({PLATAFORMA} OR {expressao})')


def remover(apps, schema_editor):
    for tabela in POLITICAS:
        schema_editor.execute(f'DROP POLICY escopo ON {tabela}')
        schema_editor.execute(f'ALTER TABLE {tabela} DISABLE ROW LEVEL SECURITY')
    _executar(schema_editor, [f'ALTER FUNCTION {nome}() SECURITY INVOKER' for nome in GATILHOS_COMO_DONO])
    schema_editor.execute('DROP FUNCTION vinculos_da_pessoa(bigint, timestamptz)')
    schema_editor.execute('DROP FUNCTION app_lista_contem(text, bigint)')


class Migration(migrations.Migration):
    dependencies = [
        ('comum', '0001_privilegios_app'),
        ('permissao', '0002_cargo_concessao'),
        ('territorio', '0003_empresa_titular'),
    ]
    operations = [migrations.RunPython(criar, remover)]
