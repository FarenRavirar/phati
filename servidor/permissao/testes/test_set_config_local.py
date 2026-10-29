"""A variável de RLS é sempre local à transação (R12, A11).

`set_config(..., false)` e `SET` sem `LOCAL` valem para a conexão inteira e vazariam o escopo de uma requisição
para a seguinte, com o mesmo papel `app` reaproveitado (prova de conceito, `docs/pesquisa/05` §A3). O teste varre o
código do servidor, migrações incluídas; os próprios testes ficam de fora porque citam os exemplos proibidos.
"""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CHAMADA = re.compile(r'set_config\s*\(([^()]*)\)', re.IGNORECASE)
# `SET` no começo de um comando ou de uma linha (o `SET` de UPDATE e o atributo de função vêm no meio da linha),
# que não seja `SET LOCAL`; e `ALTER ROLE|DATABASE ... SET`, que grava a variável como padrão permanente.
COMANDO_DEFINIR = re.compile(r'(?:^|[;\'"`])\s*SET\s+(?!LOCAL\b)\w', re.IGNORECASE | re.MULTILINE)
PADRAO_PERMANENTE = re.compile(r'ALTER\s+(?:ROLE|DATABASE|USER)\b[^;\'"`]*\bSET\b', re.IGNORECASE)


def achados_em(texto):
    """Trechos proibidos de `texto`: `set_config` sem `true` no fim, `SET` sem `LOCAL`, `ALTER ROLE|DATABASE SET`."""
    achados = [chamada.group(0) for chamada in CHAMADA.finditer(texto) if chamada.group(1).split(',')[-1].strip().lower() != 'true']
    achados += [comando.group(0).strip() for comando in COMANDO_DEFINIR.finditer(texto)]
    achados += [padrao.group(0) for padrao in PADRAO_PERMANENTE.finditer(texto)]
    return achados


def _arquivos_do_servidor():
    return [
        arquivo
        for arquivo in RAIZ.rglob('*.py')
        if 'testes' not in arquivo.parts and '.venv' not in arquivo.parts and arquivo.name != 'conftest.py'
    ]


def test_o_codigo_do_servidor_so_usa_variavel_local():
    arquivos = _arquivos_do_servidor()
    assert {'pode.py', 'contexto.py'} <= {arquivo.name for arquivo in arquivos}  # a varredura enxerga o código que importa
    achados = {str(a.relative_to(RAIZ)): achados_em(a.read_text(encoding='utf-8')) for a in arquivos}
    assert {arquivo: itens for arquivo, itens in achados.items() if itens} == {}


def test_o_codigo_fixa_as_variaveis_de_forma_local():
    # Os dois modelos de `set_config` (cinco variáveis de contexto e a assinatura da identidade) vivem em contexto.py.
    texto = (RAIZ / 'permissao' / 'contexto.py').read_text(encoding='utf-8')
    assert texto.count("', %s, true)") == 6
    assert 'set_config' not in (RAIZ / 'permissao' / 'pode.py').read_text(encoding='utf-8')


def test_definir_variavel_com_false_e_barrado():
    assert achados_em("SELECT set_config('app.empresas', '1', false)") != []
    assert achados_em("cursor.execute('SELECT set_config(%s, %s, false)', [a, b])") != []


def test_definir_variavel_com_valor_calculado_no_ultimo_argumento_e_barrado():
    assert achados_em("SELECT set_config('app.empresas', '1', is_local)") != []


def test_definir_variavel_local_passa():
    assert achados_em("SELECT set_config('app.empresas', '1', true)") == []
    assert achados_em("SELECT set_config(%s, %s, TRUE)") == []


def test_definir_sem_local_e_barrado():
    assert achados_em("SET app.empresas = '1'") != []
    assert achados_em("execute('SET SESSION app.empresas = 1')") != []
    assert achados_em("a; SET app.fazendas TO '1'") != []


def test_definir_local_passa():
    assert achados_em("SET LOCAL app.empresas = '1'") == []


def test_atributo_de_funcao_e_atualizacao_no_meio_da_linha_passam():
    assert achados_em("CREATE FUNCTION f() RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$ $$") == []
    assert achados_em("UPDATE fazenda SET nome = 'x'") == []


def test_alterar_papel_ou_banco_com_definicao_e_barrado():
    assert achados_em("ALTER ROLE app SET app.plataforma = '1'") != []
    assert achados_em("ALTER DATABASE phati SET app.plataforma TO '1'") != []
