from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.utils import timezone

from permissao import pode as modulo_pode
from permissao.models import Cargo, CargoPermissao, CategoriaDado
from permissao.pode import administrador_da_empresa, com_permissao, esquecer, exige_permissao, pode

pytestmark = pytest.mark.django_db


@pytest.fixture
def pessoa(fabrica_pessoa):
    return fabrica_pessoa('Maria Concessionaria')


def _recarregar(pessoa):
    """A requisição seguinte: o Django carrega a pessoa de novo, sem a memória do objeto anterior."""
    return type(pessoa).objects.get(pk=pessoa.pk)


def test_sem_concessao_nega_tudo(pessoa, cenario):
    assert pode(pessoa, 'ver', cenario.f1) is False
    assert pode(pessoa, 'ver', cenario.x) is False


def test_anonimo_e_nulo_negam(cenario):
    assert pode(AnonymousUser(), 'ver', cenario.f1) is False
    assert pode(None, 'ver', cenario.f1) is False


def test_acao_fora_do_catalogo_nega_ate_para_a_plataforma(plataforma, cenario):
    assert pode(plataforma, 'acao_que_nao_existe', cenario.f1) is False
    assert pode(plataforma, 'ver', cenario.f1) is True


def test_plataforma_exerce_todo_o_catalogo_em_qualquer_empresa(plataforma, cenario):
    for acao in ('ver', 'tornar_revisao_vigente', 'criar_empresa'):
        assert pode(plataforma, acao, cenario.f1) is True
        assert pode(plataforma, acao, cenario.fy) is True
    assert pode(plataforma, 'criar_empresa') is True


def test_pessoa_sem_a_marca_da_plataforma_nao_cria_empresa(pessoa, cenario, conceder_direto):
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    assert pode(pessoa, 'criar_empresa') is False
    assert pode(pessoa, 'criar_empresa', cenario.x) is False


def test_cargo_personalizado_com_criar_empresa_continua_negado(pessoa, cenario, conceder_direto):
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Quase plataforma', base='administrador')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='criar_empresa')
    conceder_direto(pessoa, cargo, cenario.x)
    assert pode(pessoa, 'criar_empresa', cenario.x) is False


def test_sem_alvo_so_a_plataforma_decide(pessoa, cenario, conceder_direto):
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    assert pode(pessoa, 'ver') is False


def test_alvo_desconhecido_ou_nao_salvo_nega(pessoa, cenario, conceder_direto):
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    assert pode(pessoa, 'ver', 'F1') is False
    assert pode(pessoa, 'ver', type(cenario.f1)(empresa=cenario.x, nome='sem salvar')) is False


def test_concessao_de_empresa_cobre_fazendas_e_sub_areas_dela_e_nada_de_outra(pessoa, cenario, conceder_direto):
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.x)
    for alvo in (cenario.x, cenario.f1, cenario.f2, cenario.g1, cenario.t1, cenario.g2):
        assert pode(pessoa, 'ver', alvo) is True
    for alvo in (cenario.y, cenario.fy):
        assert pode(pessoa, 'ver', alvo) is False


def test_concessao_de_fazenda_cobre_as_sub_areas_e_nao_a_irma_nem_a_empresa(pessoa, cenario, conceder_direto):
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    for alvo in (cenario.f1, cenario.g1, cenario.t1, cenario.g2):
        assert pode(pessoa, 'ver', alvo) is True
    for alvo in (cenario.f2, cenario.x, cenario.fy, cenario.y):
        assert pode(pessoa, 'ver', alvo) is False


def test_concessao_de_sub_area_cobre_descendentes_e_nao_a_irma_a_fazenda_nem_a_empresa(pessoa, cenario, conceder_direto):
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.g1)
    assert pode(pessoa, 'ver', cenario.g1) is True
    assert pode(pessoa, 'ver', cenario.t1) is True
    for alvo in (cenario.g2, cenario.f1, cenario.x):
        assert pode(pessoa, 'ver', alvo) is False


def test_duas_concessoes_em_empresas_diferentes_valem_as_duas(pessoa, cenario, conceder_direto):
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f2)
    conceder_direto(pessoa, cenario.cargos_y['tecnico'], cenario.y)
    assert pode(pessoa, 'ver', cenario.f2) is True
    assert pode(pessoa, 'criar_registro_campo', cenario.fy) is True
    assert pode(pessoa, 'criar_registro_campo', cenario.f2) is False  # o cargo de X é só leitura


def test_acao_do_cargo_de_outra_concessao_nao_vaza_para_o_escopo_da_primeira(pessoa, cenario, conceder_direto):
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    conceder_direto(pessoa, cenario.cargos_x['curador'], cenario.f2)
    assert pode(pessoa, 'convidar_pessoa', cenario.f2) is True
    assert pode(pessoa, 'convidar_pessoa', cenario.f1) is False


def _tecnico_com_categorias(cenario, pessoa, conceder_direto, *categorias):
    conceder_direto(pessoa, cenario.cargos_x['tecnico'], cenario.f1, categorias=categorias)


def test_tecnico_com_categoria_so_vale_para_ela(pessoa, cenario, conceder_direto):
    solo = CategoriaDado.objects.create(empresa=cenario.x, nome='Solo')
    agua = CategoriaDado.objects.create(empresa=cenario.x, nome='Água')
    _tecnico_com_categorias(cenario, pessoa, conceder_direto, solo)
    assert pode(pessoa, 'criar_registro_campo', cenario.f1, categoria=solo) is True
    assert pode(pessoa, 'criar_registro_campo', cenario.f1, categoria=agua) is False


def test_dado_sem_categoria_nao_e_restringido(pessoa, cenario, conceder_direto):
    solo = CategoriaDado.objects.create(empresa=cenario.x, nome='Solo')
    _tecnico_com_categorias(cenario, pessoa, conceder_direto, solo)
    assert pode(pessoa, 'criar_registro_campo', cenario.f1) is True


def test_tecnico_sem_nenhuma_categoria_nao_alcanca_dado_categorizado(pessoa, cenario, conceder_direto):
    solo = CategoriaDado.objects.create(empresa=cenario.x, nome='Solo')
    _tecnico_com_categorias(cenario, pessoa, conceder_direto)
    assert pode(pessoa, 'criar_registro_campo', cenario.f1, categoria=solo) is False
    assert pode(pessoa, 'criar_registro_campo', cenario.f1) is True


def test_curador_e_administrador_nao_tem_limite_por_categoria(fabrica_pessoa, cenario, conceder_direto):
    solo = CategoriaDado.objects.create(empresa=cenario.x, nome='Solo')
    for base in ('curador', 'administrador'):
        alguem = fabrica_pessoa(f'Alguem {base}')
        conceder_direto(alguem, cenario.cargos_x[base], cenario.f1)
        assert pode(alguem, 'ver', cenario.f1, categoria=solo) is True


def test_revogacao_vale_na_requisicao_seguinte_com_a_mesma_sessao(pessoa, cenario, conceder_direto, fabrica_pessoa):
    concessao = conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    assert pode(_recarregar(pessoa), 'ver', cenario.f1) is True
    concessao.revogada_em = timezone.now()
    concessao.revogada_por = fabrica_pessoa('Quem revoga')
    concessao.save()
    assert pode(_recarregar(pessoa), 'ver', cenario.f1) is False


def test_concessao_vencida_ou_com_inicio_no_futuro_nega(pessoa, cenario, conceder_direto):
    agora = timezone.now()
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1, inicio=agora - timedelta(days=2), fim=agora - timedelta(days=1))
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f2, inicio=agora + timedelta(days=1))
    assert pode(pessoa, 'ver', cenario.f1) is False
    assert pode(pessoa, 'ver', cenario.f2) is False


def test_concessao_dentro_do_periodo_vale(pessoa, cenario, conceder_direto):
    agora = timezone.now()
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1, inicio=agora - timedelta(days=1), fim=agora + timedelta(days=1))
    assert pode(pessoa, 'ver', cenario.f1) is True


def test_uma_carga_por_requisicao_a_segunda_chamada_nao_consulta_o_banco(pessoa, cenario, conceder_direto, django_assert_num_queries):
    conceder_direto(pessoa, cenario.cargos_x['curador'], cenario.f1)
    pessoa = _recarregar(pessoa)
    assert pode(pessoa, 'ver', cenario.f1) is True
    with django_assert_num_queries(0):
        assert pode(pessoa, 'convidar_pessoa', cenario.t1) is True
        assert pode(pessoa, 'criar_empresa', cenario.f1) is False


def test_esquecer_obriga_a_ler_de_novo(pessoa, cenario, conceder_direto):
    assert pode(pessoa, 'ver', cenario.f1) is False
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    assert pode(pessoa, 'ver', cenario.f1) is False  # memória da requisição
    esquecer(pessoa)
    assert pode(pessoa, 'ver', cenario.f1) is True


def test_permissao_nao_vai_para_a_sessao():
    fonte = Path(modulo_pode.__file__).read_text(encoding='utf-8')
    assert 'session' not in fonte.lower()


def test_administrador_da_empresa_exige_nivel_administrador_escopo_de_empresa_e_a_permissao(fabrica_pessoa, cenario, conceder_direto):
    na_empresa = fabrica_pessoa('Admin Empresa')
    na_fazenda = fabrica_pessoa('Admin Fazenda')
    curador = fabrica_pessoa('Curador Empresa')
    sem_permissao = fabrica_pessoa('Admin Capado')
    conceder_direto(na_empresa, cenario.cargos_x['administrador'], cenario.x)
    conceder_direto(na_fazenda, cenario.cargos_x['administrador'], cenario.f1)
    conceder_direto(curador, cenario.cargos_x['curador'], cenario.x)
    capado = Cargo.objects.create(empresa=cenario.x, nome='Admin sem redefinir', base='administrador')
    CargoPermissao.objects.create(cargo=capado, permissao_id='ver')
    conceder_direto(sem_permissao, capado, cenario.x)
    assert administrador_da_empresa(na_empresa, cenario.x.pk) is True
    assert administrador_da_empresa(na_empresa, cenario.y.pk) is False
    assert administrador_da_empresa(na_fazenda, cenario.x.pk) is False
    assert administrador_da_empresa(curador, cenario.x.pk) is False
    assert administrador_da_empresa(sem_permissao, cenario.x.pk) is False


def test_cargo_de_nivel_curador_com_redefinir_senha_nao_e_administrador_da_empresa(fabrica_pessoa, cenario, conceder_direto):
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Curador que redefine', base='curador')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='redefinir_senha')
    pessoa = fabrica_pessoa('Curador Redefine')
    conceder_direto(pessoa, cargo, cenario.x)
    assert administrador_da_empresa(pessoa, cenario.x.pk) is False


def _requisicao(pessoa):
    return SimpleNamespace(user=pessoa)


def test_decorador_nega_antes_de_rodar_a_rota(pessoa, cenario, conceder_direto):
    chamadas = []

    @exige_permissao('ver', lambda requisicao, fazenda: fazenda)
    def rota(requisicao, fazenda):
        chamadas.append(fazenda)
        return 'ok'

    requisicao = _requisicao(pessoa)
    with pytest.raises(PermissionDenied):
        rota(requisicao, cenario.f1)
    assert chamadas == []
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    assert rota(_requisicao(_recarregar(pessoa)), cenario.f1) == 'ok'
    assert chamadas == [cenario.f1]


def test_decorador_confere_a_categoria_do_dado(pessoa, cenario, conceder_direto):
    solo = CategoriaDado.objects.create(empresa=cenario.x, nome='Solo')
    agua = CategoriaDado.objects.create(empresa=cenario.x, nome='Água')
    conceder_direto(pessoa, cenario.cargos_x['tecnico'], cenario.f1, categorias=[solo])

    @exige_permissao('criar_registro_campo', lambda requisicao, fazenda, categoria: fazenda, lambda requisicao, fazenda, categoria: categoria)
    def rota(requisicao, fazenda, categoria):
        return 'ok'

    requisicao = _requisicao(_recarregar(pessoa))
    assert rota(requisicao, cenario.f1, solo) == 'ok'
    with pytest.raises(PermissionDenied):
        rota(requisicao, cenario.f1, agua)


def test_decorador_marca_a_acao_exigida_e_sem_alvo_nega_quem_nao_e_plataforma(pessoa, plataforma):
    @exige_permissao('criar_empresa')
    def rota(requisicao):
        return 'ok'

    assert getattr(rota, 'acao_exigida') == 'criar_empresa'
    requisicao = _requisicao(pessoa)
    with pytest.raises(PermissionDenied):
        rota(requisicao)
    assert rota(_requisicao(plataforma)) == 'ok'


def _variaveis_de_rls():
    with connection.cursor() as consulta:
        consulta.execute("SELECT current_setting('app.empresas', true), current_setting('app.fazendas', true)")
        return consulta.fetchone()


def test_decorador_roda_a_rota_dentro_de_com_permissao(pessoa, cenario, conceder_direto):
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    vistas = []

    @exige_permissao('ver', lambda requisicao: cenario.f1)
    def rota(requisicao):
        vistas.append(_variaveis_de_rls())

    rota(_requisicao(_recarregar(pessoa)))
    assert vistas == [('', str(cenario.f1.pk))]
    assert _variaveis_de_rls()[1] in ('', None)  # a rota terminou: nada fica para a transação seguinte


def test_com_permissao_une_os_escopos_das_acoes(pessoa, cenario, conceder_direto):
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)  # só `ver`
    conceder_direto(pessoa, cenario.cargos_x['curador'], cenario.f2)  # `ver` e `convidar_pessoa`
    with com_permissao(_recarregar(pessoa), 'ver', 'convidar_pessoa'):
        assert _variaveis_de_rls() == ('', f'{cenario.f1.pk},{cenario.f2.pk}')
    with com_permissao(_recarregar(pessoa), 'convidar_pessoa'):
        assert _variaveis_de_rls() == ('', str(cenario.f2.pk))


def test_com_permissao_sem_acao_usa_ver(pessoa, cenario, conceder_direto):
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.x)
    with com_permissao(_recarregar(pessoa)):
        assert _variaveis_de_rls() == (str(cenario.x.pk), '')


def test_com_permissao_inclui_a_fazenda_das_sub_areas(pessoa, cenario, conceder_direto):
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.g1)
    with com_permissao(_recarregar(pessoa)):
        assert _variaveis_de_rls() == ('', str(cenario.f1.pk))


def test_com_permissao_sem_concessao_nao_abre_escopo(pessoa, cenario):
    with com_permissao(pessoa, 'ver'):
        assert _variaveis_de_rls() == ('', '')


def test_decorador_de_listagem_abre_o_bloco_sem_chamar_pode_e_marca_a_rota(pessoa, cenario):
    # Sem alvo, `pode()` só passaria a plataforma; a listagem filtra por escopo e devolve vazio a quem não tem concessão.
    @exige_permissao('ver', listagem=True)
    def rota(requisicao):
        return _variaveis_de_rls()

    assert rota(SimpleNamespace(user=pessoa)) is not None
    assert getattr(rota, 'listagem') is True
    assert getattr(rota, 'acao_exigida') == 'ver'


def test_decorador_sem_listagem_mantem_pode_e_marca_listagem_falsa(pessoa, cenario):
    @exige_permissao('ver', lambda requisicao: cenario.f1)
    def rota(requisicao):
        return 'ok'

    assert getattr(rota, 'listagem') is False
    requisicao = SimpleNamespace(user=pessoa)
    with pytest.raises(PermissionDenied):
        rota(requisicao)
