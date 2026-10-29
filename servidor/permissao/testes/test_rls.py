"""Segunda barreira no banco (R12, R13, R19; aceite A11 e A12 de empresa e de fazenda).

Todo teste que consulta como o papel `app` é transacional: a conexão `app` só enxerga dado gravado. O teste
transacional esvazia o catálogo ao fim, então o mundo monta as próprias ações em vez de usar `cenario`.
"""

from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, ProgrammingError, connection, connections, transaction
from django.utils import timezone

from permissao.models import Cargo, CargoPermissao, CategoriaDado, ConcessaoCategoria, Permissao, concessoes_ativas
from permissao.contexto import fixar_contexto, fixar_identidade, ler_contexto
from permissao.delegacao import convidar, revogar_concessao
from permissao.models import Concessao
from permissao.pode import com_permissao, esquecer, pode
from territorio.cadastro import criar_fazenda
from territorio.listagem import fazendas_autorizadas
from territorio.models import Empresa, Fazenda, NivelDivisao, SubArea

TABELAS = ('empresa', 'nivel_divisao', 'fazenda', 'sub_area', 'cargo', 'categoria_dado', 'concessao')
# R12: fora da RLS, cada uma com a defesa que a protege (testes abaixo).
EXCECOES = {
    'pessoa', 'cargo_permissao', 'concessao_categoria', 'pedido_redefinicao', 'acesso_aplicativo', 'evento_auditoria',
}
INSERIR_SUB_AREA = 'INSERT INTO sub_area (empresa_id, fazenda_id, nivel, nome, caminho) VALUES (%s, %s, 1, %s, %s)'
INSERIR_FAZENDA = 'INSERT INTO fazenda (empresa_id, nome, criada_em) VALUES (%s, %s, now())'
INSERIR_CATEGORIA = 'INSERT INTO concessao_categoria (concessao_id, categoria_id) VALUES (%s, %s)'
FIXAR = 'SELECT set_config(%s, %s, true)'
pytestmark = pytest.mark.django_db(transaction=True, databases=['default', 'app'])


def fixar(consulta, nome, valor):
    """Fixa uma variável de RLS e reassina o contexto, como `com_permissao` faz."""
    consulta.execute(FIXAR, [f'app.{nome}', str(valor)])
    fixar_contexto(consulta, *ler_contexto(consulta)[:4])


@pytest.fixture
def mundo(fabrica_pessoa, conceder_direto):
    """X (fazendas F1 com glebas G1 e G2, e F2) e Y (fazenda FY). Gravado pelo dono, lido pelo `app`."""
    for codigo in ('ver', 'criar_fazenda', 'convidar_pessoa', 'revogar_acesso', 'redefinir_senha'):
        Permissao.objects.get_or_create(codigo=codigo, defaults={'descricao': codigo, 'delegavel': True})
    mundo = SimpleNamespace()
    mundo.x, mundo.y = Empresa.objects.create(nome='Empresa X'), Empresa.objects.create(nome='Empresa Y')
    mundo.f1 = Fazenda.objects.create(empresa=mundo.x, nome='F1')
    mundo.f2 = Fazenda.objects.create(empresa=mundo.x, nome='F2')
    mundo.fy = Fazenda.objects.create(empresa=mundo.y, nome='FY')
    mundo.g1 = SubArea.objects.create(empresa=mundo.x, fazenda=mundo.f1, nivel=1, nome='G1')
    mundo.g2 = SubArea.objects.create(empresa=mundo.x, fazenda=mundo.f1, nivel=1, nome='G2')
    mundo.g3 = SubArea.objects.create(empresa=mundo.x, fazenda=mundo.f2, nivel=1, nome='G3')
    for empresa in (mundo.x, mundo.y):
        NivelDivisao.objects.create(empresa=empresa, nivel=1, nome='gleba')
        CategoriaDado.objects.create(empresa=empresa, nome='solo')
    mundo.admin_x = Cargo.objects.create(empresa=mundo.x, nome='Administrador', base='administrador')
    mundo.usuario_x = Cargo.objects.create(empresa=mundo.x, nome='Usuário', base='usuario')
    mundo.admin_y = Cargo.objects.create(empresa=mundo.y, nome='Administrador', base='administrador')
    for cargo in (mundo.admin_x, mundo.usuario_x, mundo.admin_y):
        CargoPermissao.objects.create(cargo=cargo, permissao_id='ver')
    CargoPermissao.objects.create(cargo=mundo.admin_x, permissao_id='criar_fazenda')
    for cargo in (mundo.admin_x, mundo.admin_y):
        CargoPermissao.objects.create(cargo=cargo, permissao_id='redefinir_senha')
    mundo.curador_x = Cargo.objects.create(empresa=mundo.x, nome='Curador', base='curador')
    for codigo in ('ver', 'convidar_pessoa', 'revogar_acesso'):
        CargoPermissao.objects.create(cargo=mundo.curador_x, permissao_id=codigo)
    mundo.dono_x, mundo.dono_y, mundo.externo = (fabrica_pessoa(nome) for nome in ('Admin X', 'Admin Y', 'Externo'))
    mundo.de_x = conceder_direto(mundo.dono_x, mundo.admin_x, mundo.x)
    mundo.de_y = conceder_direto(mundo.dono_y, mundo.admin_y, mundo.y)
    mundo.do_externo = conceder_direto(mundo.externo, mundo.usuario_x, mundo.f1)
    mundo.curador = fabrica_pessoa('Curador F1')
    mundo.do_curador = conceder_direto(mundo.curador, mundo.curador_x, mundo.f1)
    return mundo


def _ids(tabela, **variaveis):
    """Ids que o papel `app` enxerga em `tabela`, com as variáveis de RLS dadas (ou nenhuma)."""
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        for nome, valor in variaveis.items():
            fixar(consulta, nome, valor)
        consulta.execute(f'SELECT id FROM {tabela}')
        return {linha[0] for linha in consulta.fetchall()}


def _executar_como_app(variaveis, comando, parametros):
    """Roda `comando` como o papel `app` com as variáveis de RLS dadas e deixa a exceção subir."""
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        for nome, valor in variaveis.items():
            fixar(consulta, nome, valor)
        consulta.execute(comando, parametros)


@pytest.mark.parametrize('tabela', TABELAS)
def test_sem_variavel_o_papel_app_le_zero_linhas(mundo, tabela):
    with connection.cursor() as dono:
        dono.execute(f'SELECT count(*) FROM {tabela}')
        assert dono.fetchone()[0] > 0  # o dono vê: sem isso o zero do `app` poderia ser tabela vazia
    assert _ids(tabela) == set()


def test_papel_app_nao_e_dono_nem_ignora_a_rls():
    with connections['app'].cursor() as consulta:
        consulta.execute(
            'SELECT bool_or(c.relowner = r.oid), bool_or(r.rolbypassrls OR r.rolsuper), bool_and(c.relrowsecurity)'
            ' FROM pg_roles r, pg_class c WHERE r.rolname = current_user AND c.relname = ANY(%s)',
            [list(TABELAS)],
        )
        assert consulta.fetchone() == (False, False, True)


def test_variavel_de_fazenda_mostra_so_as_linhas_dela(mundo):
    assert _ids('fazenda', fazendas=mundo.f1.pk) == {mundo.f1.pk}
    assert _ids('sub_area', fazendas=mundo.f1.pk) == {mundo.g1.pk, mundo.g2.pk}
    assert _ids('concessao', fazendas=mundo.f1.pk) == {mundo.do_externo.pk, mundo.do_curador.pk}
    for tabela in ('empresa', 'cargo', 'categoria_dado', 'nivel_divisao'):
        assert _ids(tabela, fazendas=mundo.f1.pk) == set()


def test_variavel_de_empresa_mostra_so_a_empresa_dela(mundo):
    assert _ids('empresa', empresas=mundo.x.pk) == {mundo.x.pk}
    assert _ids('fazenda', empresas=mundo.x.pk) == {mundo.f1.pk, mundo.f2.pk}
    assert _ids('cargo', empresas=mundo.x.pk) == {mundo.admin_x.pk, mundo.usuario_x.pk, mundo.curador_x.pk}
    assert _ids('concessao', empresas=mundo.x.pk) == {mundo.de_x.pk, mundo.do_externo.pk, mundo.do_curador.pk}
    assert len(_ids('categoria_dado', empresas=mundo.x.pk)) == 1
    assert len(_ids('nivel_divisao', empresas=mundo.x.pk)) == 1


def test_lista_de_variavel_vale_para_varias_empresas(mundo):
    assert _ids('empresa', empresas=f'{mundo.x.pk},{mundo.y.pk}') == {mundo.x.pk, mundo.y.pk}


def test_variavel_vazia_ou_zero_nao_da_erro_nem_abre_linha(mundo):
    assert _ids('fazenda', empresas='', fazendas='', plataforma='') == set()
    assert _ids('fazenda', plataforma='0') == set()


def test_plataforma_le_de_qualquer_empresa_e_sem_a_variavel_le_zero(mundo):
    assert _ids('empresa', plataforma='1') == {mundo.x.pk, mundo.y.pk}
    assert _ids('fazenda', plataforma='1') == {mundo.f1.pk, mundo.f2.pk, mundo.fy.pk}
    assert _ids('fazenda') == set()


def test_insert_em_fazenda_fora_do_escopo_falha(mundo):
    with pytest.raises(ProgrammingError, match='row-level security'):
        _executar_como_app({'fazendas': mundo.f1.pk}, INSERIR_SUB_AREA, [mundo.x.pk, mundo.f2.pk, 'intrusa', '/'])


def test_insert_na_fazenda_do_escopo_passa(mundo):
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        fixar(consulta, 'fazendas', mundo.f1.pk)
        consulta.execute(INSERIR_SUB_AREA, [mundo.x.pk, mundo.f1.pk, 'legitima', '/'])
    assert SubArea.objects.filter(nome='legitima').exists()


def test_insert_em_empresa_fora_do_escopo_falha(mundo):
    with pytest.raises(ProgrammingError, match='row-level security'):
        _executar_como_app({'empresas': mundo.x.pk}, INSERIR_FAZENDA, [mundo.y.pk, 'intrusa'])


def test_atualizacao_em_linha_de_outra_fazenda_atinge_zero_linhas(mundo):
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        fixar(consulta, 'fazendas', mundo.f1.pk)
        consulta.execute("UPDATE fazenda SET nome = 'invadida' WHERE id = %s", [mundo.f2.pk])
        assert consulta.rowcount == 0
        consulta.execute("UPDATE fazenda SET nome = 'minha' WHERE id = %s", [mundo.f1.pk])
        assert consulta.rowcount == 1


def test_atualizacao_que_leva_a_linha_para_fora_do_escopo_falha(mundo):
    with pytest.raises(ProgrammingError, match='row-level security'):
        _executar_como_app(
            {'empresas': mundo.x.pk}, 'UPDATE nivel_divisao SET empresa_id = %s WHERE empresa_id = %s', [mundo.y.pk, mundo.x.pk]
        )


def test_colaborador_externo_nao_le_outra_empresa_nem_fazenda_irma(mundo):
    # A12 (empresa e fazenda): a concessão do externo é só na F1 de X.
    visiveis = _ids('fazenda', fazendas=mundo.f1.pk)
    assert visiveis == {mundo.f1.pk}
    assert _ids('empresa', fazendas=mundo.f1.pk) == set()


def test_duas_concessoes_em_empresas_diferentes_valem_as_duas(mundo, conceder_direto):
    conceder_direto(mundo.externo, mundo.admin_y, mundo.y)
    esquecer(mundo.externo)
    with com_permissao(mundo.externo, 'ver', usando='app'), connections['app'].cursor() as consulta:
        consulta.execute('SELECT id FROM fazenda')
        assert {linha[0] for linha in consulta.fetchall()} == {mundo.f1.pk, mundo.fy.pk}


def test_variavel_nao_vaza_para_a_transacao_seguinte_na_mesma_conexao(mundo):
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        fixar(consulta, 'empresas', mundo.x.pk)
        consulta.execute('SELECT count(*) FROM fazenda')
        assert consulta.fetchone()[0] == 2
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        consulta.execute('SELECT count(*) FROM fazenda')
        assert consulta.fetchone()[0] == 0


def _variaveis_da_conexao_app():
    with connections['app'].cursor() as consulta:
        consulta.execute("SELECT current_setting('app.empresas', true), current_setting('app.plataforma', true)")
        return consulta.fetchone()


def test_com_permissao_fixa_e_devolve_as_variaveis(mundo):
    with com_permissao(mundo.dono_x, 'ver', usando='app'):
        assert _variaveis_da_conexao_app() == (str(mundo.x.pk), '')
        with com_permissao(mundo.dono_y, 'ver', usando='app'):
            assert _variaveis_da_conexao_app() == (str(mundo.y.pk), '')
        assert _variaveis_da_conexao_app() == (str(mundo.x.pk), '')  # o bloco interno devolveu o que havia
    assert _variaveis_da_conexao_app()[0] in ('', None)


def test_com_permissao_de_quem_nao_tem_a_acao_nao_abre_linha(mundo):
    with com_permissao(mundo.dono_x, 'criar_sub_area', usando='app'), connections['app'].cursor() as consulta:
        consulta.execute('SELECT count(*) FROM fazenda')
        assert consulta.fetchone()[0] == 0


def test_com_permissao_da_plataforma_le_tudo(mundo, plataforma):
    with com_permissao(plataforma, 'ver', usando='app'), connections['app'].cursor() as consulta:
        consulta.execute('SELECT count(*) FROM fazenda')
        assert consulta.fetchone()[0] == 3


def test_com_permissao_anonimo_nao_abre_linha(mundo):
    with com_permissao(AnonymousUser(), 'ver', usando='app'), connections['app'].cursor() as consulta:
        consulta.execute('SELECT count(*) FROM fazenda')
        assert consulta.fetchone()[0] == 0


def test_com_permissao_com_erro_nao_deixa_variavel_para_tras(mundo):
    with pytest.raises(RuntimeError), com_permissao(mundo.dono_x, 'ver', usando='app'):
        raise RuntimeError
    assert _variaveis_da_conexao_app()[0] in ('', None)


def _respostas(pessoa, alvos):
    return [pode(pessoa, 'ver', alvo) for alvo in alvos]


def test_pode_da_a_mesma_resposta_com_rls_ligada_dentro_e_fora_de_com_permissao(mundo, como_app):
    # `default` aponta para o papel `app`: `pode()` lê as concessões pela função do banco, sem variável nenhuma.
    pessoa = type(mundo.dono_x).objects.get(pk=mundo.dono_x.pk)
    alvos = (mundo.x, mundo.f1, mundo.g1, mundo.y, mundo.fy)
    fora = _respostas(pessoa, alvos)
    esquecer(pessoa)
    with com_permissao(pessoa, 'ver'):
        dentro = _respostas(pessoa, alvos)
        esquecer(pessoa)
        depois = _respostas(pessoa, alvos)
    assert fora == dentro == depois == [True, True, True, False, False]


def test_servico_roda_como_papel_app_dentro_de_com_permissao(mundo, como_app):
    administrador = type(mundo.dono_x).objects.get(pk=mundo.dono_x.pk)
    with com_permissao(administrador, 'criar_fazenda', 'ver'):
        nova = criar_fazenda(administrador, mundo.x, 'F3')
        assert nova.pk in {f.pk for f in fazendas_autorizadas(administrador)}


def test_servico_sem_com_permissao_nao_grava_como_papel_app(mundo, como_app):
    administrador = type(mundo.dono_x).objects.get(pk=mundo.dono_x.pk)
    with pytest.raises(ProgrammingError, match='row-level security'):
        criar_fazenda(administrador, mundo.x, 'F3')


def test_gatilho_de_categoria_roda_como_dono_e_nao_depende_da_visibilidade(mundo):
    # O externo só tem escopo de fazenda: pela RLS ele não enxerga o cargo nem a categoria. O gatilho precisa
    # enxergá-los (SECURITY DEFINER) para aceitar a categoria legítima.
    categoria = CategoriaDado.objects.get(empresa=mundo.x)
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        fixar(consulta, 'fazendas', mundo.f1.pk)
        consulta.execute(INSERIR_CATEGORIA, [mundo.do_externo.pk, categoria.pk])
    assert ConcessaoCategoria.objects.filter(concessao=mundo.do_externo).count() == 1


def test_gatilho_continua_barrando_categoria_de_outra_empresa(mundo):
    outra = CategoriaDado.objects.get(empresa=mundo.y)
    with pytest.raises(IntegrityError, match='categoria de outra empresa'):
        _executar_como_app({'fazendas': mundo.f1.pk}, INSERIR_CATEGORIA, [mundo.do_externo.pk, outra.pk])


def test_gatilhos_que_consultam_tabela_com_rls_sao_security_definer():
    with connection.cursor() as consulta:
        consulta.execute(
            "SELECT proname, prosecdef FROM pg_proc WHERE proname IN ('concessao_validar', 'concessao_categoria_validar')"
        )
        assert dict(consulta.fetchall()) == {'concessao_validar': True, 'concessao_categoria_validar': True}


def test_funcao_de_bootstrap_nao_e_publica():
    with connection.cursor() as consulta:
        consulta.execute("SELECT has_function_privilege('public', 'vinculos_da_pessoa(bigint, timestamptz)', 'EXECUTE')")
        assert consulta.fetchone() == (False,)


def test_funcao_de_vinculos_confere_com_concessoes_ativas_nas_bordas(mundo, conceder_direto, fabrica_pessoa):
    agora = timezone.now()
    pessoa = fabrica_pessoa('Bordas')
    dois_dias = timedelta(days=2)
    casos = {
        'comeca_agora': {'inicio': agora},
        'termina_agora': {'inicio': agora - dois_dias, 'fim': agora},
        'termina_depois': {'inicio': agora - dois_dias, 'fim': agora + timedelta(seconds=1)},
        'comeca_depois': {'inicio': agora + timedelta(seconds=1)},
        'revogada': {'inicio': agora - dois_dias, 'revogada_em': agora, 'revogada_por': mundo.dono_x},
        'aberta': {'inicio': agora - dois_dias},
    }
    concessoes = {nome: conceder_direto(pessoa, mundo.usuario_x, mundo.f2, **campos) for nome, campos in casos.items()}
    with transaction.atomic(), connection.cursor() as consulta:
        fixar_identidade(consulta, pessoa.pk)
        consulta.execute('SELECT concessao_id FROM vinculos_da_pessoa(%s, %s)', [pessoa.pk, agora])
        pelo_banco = {linha[0] for linha in consulta.fetchall()}
    pelo_orm = set(concessoes_ativas(agora).filter(pessoa=pessoa).values_list('pk', flat=True))
    assert pelo_banco == pelo_orm == {concessoes[nome].pk for nome in ('comeca_agora', 'termina_depois', 'aberta')}


def _tabelas_sem_rls_nem_excecao():
    """Tabelas com coluna de empresa ou fazenda, ou chave estrangeira para elas, sem RLS e fora da lista de R12."""
    with connection.cursor() as consulta:
        consulta.execute(
            """
            SELECT DISTINCT c.relname FROM pg_class c
            WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace AND NOT c.relrowsecurity AND (
                EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND NOT a.attisdropped
                        AND a.attname IN ('empresa_id', 'fazenda_id'))
                OR EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'f'
                           AND k.confrelid IN ('empresa'::regclass, 'fazenda'::regclass))
            )
            """
        )
        return {linha[0] for linha in consulta.fetchall()} - EXCECOES


def test_toda_tabela_com_empresa_ou_fazenda_tem_rls_ou_consta_das_excecoes():
    assert _tabelas_sem_rls_nem_excecao() == set()


def test_tabela_nova_com_empresa_id_e_sem_rls_faz_o_teste_acima_falhar():
    with transaction.atomic(), connection.cursor() as consulta:
        consulta.execute('CREATE TABLE tabela_nova_sem_rls (id int, empresa_id bigint)')
        assert _tabelas_sem_rls_nem_excecao() == {'tabela_nova_sem_rls'}
        transaction.set_rollback(True)


def test_as_excecoes_de_r12_estao_sem_rls():
    with connection.cursor() as consulta:
        consulta.execute('SELECT relname FROM pg_class WHERE relname = ANY(%s) AND relrowsecurity', [sorted(EXCECOES)])
        assert consulta.fetchall() == []


def test_tabelas_de_acesso_guardam_so_o_hash():
    with connection.cursor() as consulta:
        consulta.execute(
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_name IN ('pedido_redefinicao', 'acesso_aplicativo') AND column_name ~ 'segredo|token|senha'"
        )
        assert set(consulta.fetchall()) == {('pedido_redefinicao', 'hash_segredo'), ('acesso_aplicativo', 'hash_segredo')}


def _como(mundo, pessoa):
    return type(pessoa).objects.get(pk=pessoa.pk)


def test_curador_de_fazenda_convida_sob_rls(mundo, como_app, cpf_novo):
    curador = _como(mundo, mundo.curador)
    with com_permissao(curador, 'convidar_pessoa', 'revogar_acesso'):
        pessoa, _ = convidar(curador, 'Nova', 'nova@exemplo.test', cpf_novo(), mundo.usuario_x, mundo.f1)
        assert Concessao.objects.filter(pessoa_id=pessoa.pk, fazenda_id=mundo.f1.pk).count() == 1


def test_curador_de_fazenda_revoga_sob_rls(mundo, como_app):
    curador = _como(mundo, mundo.curador)
    with com_permissao(curador, 'convidar_pessoa', 'revogar_acesso'):
        revogar_concessao(curador, Concessao.objects.get(pk=mundo.do_externo.pk))
        assert Concessao.objects.get(pk=mundo.do_externo.pk).revogada_em is not None


def test_curador_de_fazenda_nao_revoga_concessao_da_empresa_inteira_sob_rls(mundo, como_app):
    from django.core.exceptions import PermissionDenied

    curador = _como(mundo, mundo.curador)
    with com_permissao(curador, 'convidar_pessoa', 'revogar_acesso'), pytest.raises(PermissionDenied):
        revogar_concessao(curador, mundo.de_x)


def test_leitura_por_fazenda_nao_vira_escrita(mundo):
    leitura = {'empresas_de_fazendas': mundo.x.pk, 'fazendas': mundo.f1.pk}
    assert _ids('empresa', **leitura) == {mundo.x.pk}
    assert mundo.admin_x.pk in _ids('cargo', **leitura)
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        for nome, valor in leitura.items():
            fixar(consulta, nome, valor)
        consulta.execute("UPDATE empresa SET nome = 'invadida' WHERE id = %s", [mundo.x.pk])
        assert consulta.rowcount == 0
        consulta.execute("UPDATE cargo SET nome = 'invadido' WHERE id = %s", [mundo.admin_x.pk])
        assert consulta.rowcount == 0
        consulta.execute("DELETE FROM categoria_dado WHERE empresa_id = %s", [mundo.x.pk])
        assert consulta.rowcount == 0
    with pytest.raises(ProgrammingError, match='row-level security'):
        _executar_como_app(leitura, "INSERT INTO cargo (empresa_id, nome, base) VALUES (%s, 'novo', 'usuario')", [mundo.x.pk])


def test_leitura_por_fazenda_nao_mostra_outra_empresa(mundo):
    assert _ids('empresa', empresas_de_fazendas=mundo.x.pk, fazendas=mundo.f1.pk) == {mundo.x.pk}
    assert mundo.y.pk not in _ids('empresa', empresas_de_fazendas=mundo.x.pk)
    assert _ids('cargo', empresas_de_fazendas=mundo.y.pk) == {mundo.admin_y.pk}


def test_listagem_roda_como_papel_app(mundo, como_app):
    externo = _como(mundo, mundo.externo)
    assert [f.pk for f in fazendas_autorizadas(externo)] == [mundo.f1.pk]


def test_decorador_carrega_o_alvo_sob_rls(mundo, como_app):
    from types import SimpleNamespace

    from permissao.pode import exige_permissao

    @exige_permissao('ver', lambda requisicao, pk: Fazenda.objects.get(pk=pk))
    def rota(requisicao, pk):
        return 'ok'

    requisicao = SimpleNamespace(user=_como(mundo, mundo.externo))
    assert rota(requisicao, mundo.f1.pk) == 'ok'
    with pytest.raises(Fazenda.DoesNotExist):
        rota(requisicao, mundo.f2.pk)  # fora do escopo: a RLS esconde, a rota responde como não encontrada


def test_pedido_de_redefinicao_por_administrador_de_empresa_com_concessao_sob_rls(mundo, como_app, conceder_direto, mailoutbox, cpf_novo, plataforma):
    from identidade.models import Pessoa
    from identidade.redefinicao import pedir_redefinicao

    cpf = cpf_novo()
    colaborador = Pessoa.objects.criar('Colaboradora', 'colab@exemplo.test', cpf)  # sem empresa de origem: só a concessão liga
    with com_permissao(plataforma, 'ver'):  # montagem do cenário: o papel `app` só grava com escopo
        conceder_direto(colaborador, mundo.usuario_x, mundo.f1)
    pedir_redefinicao(cpf, _como(mundo, mundo.dono_x))
    assert len(mailoutbox) == 1
    pedir_redefinicao(cpf, _como(mundo, mundo.dono_y))  # administrador de empresa sem vínculo: recusado em silêncio
    assert len(mailoutbox) == 1


def test_reverter_a_migracao_remove_politicas_funcoes_e_gatilhos_definer():
    migracao = import_module('permissao.migrations.0003_rls')
    with connection.schema_editor() as editor:
        migracao.remover(None, editor)
    try:
        with connection.cursor() as consulta:
            consulta.execute('SELECT count(*) FROM pg_policies WHERE tablename = ANY(%s)', [list(TABELAS)])
            assert consulta.fetchone() == (0,)
            consulta.execute('SELECT count(*) FROM pg_class WHERE relname = ANY(%s) AND relrowsecurity', [list(TABELAS)])
            assert consulta.fetchone() == (0,)
            consulta.execute("SELECT count(*) FROM pg_proc WHERE proname IN ('app_lista_contem', 'vinculos_da_pessoa')")
            assert consulta.fetchone() == (0,)
            consulta.execute("SELECT bool_or(prosecdef) FROM pg_proc WHERE proname IN ('concessao_validar', 'concessao_categoria_validar')")
            assert consulta.fetchone() == (False,)
    finally:
        # Transacional: o banco só é esvaziado ao fim, então o estado aplicado volta mesmo se uma asserção falhar.
        with connection.schema_editor() as editor:
            migracao.criar(None, editor)
    assert _tabelas_sem_rls_nem_excecao() == set()


def test_administrador_de_cargo_enxuto_convida_e_revoga_sob_rls(mundo, como_app, cpf_novo, fabrica_pessoa, conceder_direto, plataforma):
    # D043: o Administrador conta como quem tem `convidar_pessoa` e `revogar_acesso` mesmo sem listá-las no cargo;
    # o escopo de RLS dessas ações segue a regra (achado do Codex, PR #12).
    with com_permissao(plataforma, 'ver'):  # montagem do cenário: o papel `app` só grava com escopo
        enxuto = Cargo.objects.create(empresa=mundo.x, nome='Admin enxuto', base='administrador')
        CargoPermissao.objects.create(cargo=enxuto, permissao_id='ver')
        admin = fabrica_pessoa('Admin Enxuto')
        conceder_direto(admin, enxuto, mundo.f1)
    admin = _como(mundo, admin)
    with com_permissao(admin, 'convidar_pessoa', 'revogar_acesso'):
        pessoa, _ = convidar(admin, 'Nova', 'nova@exemplo.test', cpf_novo(), mundo.usuario_x, mundo.f1)
        nova = Concessao.objects.get(pessoa_id=pessoa.pk)
        revogar_concessao(admin, nova)
        assert Concessao.objects.get(pk=nova.pk).revogada_em is not None
