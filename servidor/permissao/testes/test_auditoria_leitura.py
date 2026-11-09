"""Leitura da auditoria (005 R2 a R4, R7; A1 a A5, A7): escopo por empresa, papéis, nomes sem CPF e a própria consulta auditada."""

from datetime import timedelta

import pytest
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from comum.models import EventoAuditoria
from identidade.models import Pessoa
from permissao.auditoria_leitura import consultar
from permissao.models import Cargo, CargoPermissao, Permissao
from permissao.pode import com_permissao, esquecer

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def catalogo(db):
    """O catálogo vem das migrações; a 0011 tem de ter rodado (a ação existe e não é delegável)."""
    assert Permissao.objects.filter(codigo='ver_auditoria', delegavel=False).exists()


def _evento(acao='pessoa_criada', pessoa=None, empresa=None, alvo=None, detalhes=None, alvo_tipo='', alvo_id=None):
    """Grava o evento direto. `alvo` (objeto) define tipo e id; sem ele, `alvo_tipo` e `alvo_id` valem como passados."""
    return EventoAuditoria.objects.create(
        acao=acao, pessoa_id=getattr(pessoa, 'pk', pessoa), empresa_id=getattr(empresa, 'pk', empresa),
        alvo_tipo=type(alvo).__name__ if alvo is not None else alvo_tipo, alvo_id=alvo.pk if alvo is not None else alvo_id,
        detalhes=detalhes or {},
    )


def _ler(quem, **filtros):
    esquecer(quem)
    with com_permissao(quem, 'ver_auditoria'):
        return consultar(quem, **filtros)


def _admin(fabrica_pessoa, conceder_direto, cargo, escopo, nome='Admin'):
    pessoa = fabrica_pessoa(nome)
    conceder_direto(pessoa, cargo, escopo)
    return pessoa


def _contagem_de_consultas():
    return EventoAuditoria.objects.filter(acao='auditoria_consultada').count()


def test_administrador_de_empresa_ve_so_os_eventos_dela_e_empresa_alheia_da_404(cenario, fabrica_pessoa, conceder_direto):
    admin_x = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    de_x, de_y = _evento(empresa=cenario.x), _evento(empresa=cenario.y)
    ids = {linha['id'] for linha in _ler(admin_x)[0]}
    assert de_x.pk in ids and de_y.pk not in ids
    with pytest.raises(ObjectDoesNotExist):
        _ler(admin_x, empresa_id=cenario.y.pk)
    assert {linha['id'] for linha in _ler(admin_x, empresa_id=cenario.x.pk)[0]} >= {de_x.pk}


def test_empresa_que_nao_existe_da_o_mesmo_404_para_quem_nao_e_da_plataforma(cenario, fabrica_pessoa, conceder_direto):
    admin_x = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    with pytest.raises(ObjectDoesNotExist):
        _ler(admin_x, empresa_id=999999)


@pytest.mark.parametrize('base', ['curador', 'tecnico', 'usuario'])
def test_cargo_base_que_nao_e_administrador_nao_le(cenario, fabrica_pessoa, conceder_direto, base):
    pessoa = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x[base], cenario.x, 'Sem Acesso')
    _evento(empresa=cenario.x)
    with pytest.raises(ObjectDoesNotExist):
        _ler(pessoa)


def test_cargo_personalizado_com_todas_as_acoes_delegaveis_nao_le(cenario, fabrica_pessoa, conceder_direto):
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Quase Tudo', base='tecnico')
    CargoPermissao.objects.bulk_create(
        CargoPermissao(cargo=cargo, permissao=p) for p in Permissao.objects.filter(delegavel=True)
    )
    pessoa = _admin(fabrica_pessoa, conceder_direto, cargo, cenario.x, 'Personalizada')
    with pytest.raises(ObjectDoesNotExist):
        _ler(pessoa)


def test_administrador_so_de_uma_fazenda_nao_le_a_auditoria_da_empresa(cenario, fabrica_pessoa, conceder_direto):
    pessoa = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.f1, 'Admin da Fazenda')
    with pytest.raises(ObjectDoesNotExist):
        _ler(pessoa)


def test_pessoa_sem_concessao_nao_le(fabrica_pessoa):
    with pytest.raises(ObjectDoesNotExist):
        _ler(fabrica_pessoa('Sem Nada'))


def test_evento_sem_empresa_so_aparece_para_a_plataforma(cenario, plataforma, fabrica_pessoa, conceder_direto):
    sem_empresa = _evento('conta_bloqueada')
    admin_x = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    assert sem_empresa.pk in {linha['id'] for linha in _ler(plataforma)[0]}
    assert sem_empresa.pk not in {linha['id'] for linha in _ler(admin_x)[0]}


def test_plataforma_ve_todas_as_empresas_e_filtra_por_uma(cenario, plataforma):
    de_x, de_y = _evento(empresa=cenario.x), _evento(empresa=cenario.y)
    todos = {linha['id'] for linha in _ler(plataforma)[0]}
    assert {de_x.pk, de_y.pk} <= todos
    so_y = {linha['id'] for linha in _ler(plataforma, empresa_id=cenario.y.pk)[0]}
    assert de_y.pk in so_y and de_x.pk not in so_y


def test_saida_traz_nomes_e_rotulos_e_nunca_cpf_email_nem_json(cenario, plataforma, fabrica_pessoa, cpf_novo):
    cpf_quem, cpf_alvo = cpf_novo(), cpf_novo()
    quem = Pessoa.objects.criar(nome='Quem Agiu', email='quem.agiu@exemplo.test', cpf=cpf_quem)
    alvo = Pessoa.objects.criar(nome='Quem Sofreu', email='quem.sofreu@exemplo.test', cpf=cpf_alvo)
    _evento('redefinicao_pedida', quem, cenario.x, alvo, {'segredo_do_detalhe': 'nao-deve-aparecer'})
    (linha, *_), _ = _ler(plataforma, acao='redefinicao_pedida')
    assert (linha['quem'], linha['alvo'], linha['empresa'], linha['rotulo']) == (
        'Quem Agiu', 'Quem Sofreu', 'Empresa X', 'Redefinição de senha pedida',
    )
    assert set(linha) == {'id', 'hora', 'acao', 'rotulo', 'quem', 'alvo', 'empresa', 'resumo'}
    texto = str(linha)
    assert cpf_quem not in texto and cpf_alvo not in texto and quem.email not in texto
    assert 'nao-deve-aparecer' not in texto and 'cpf' not in set(linha)


def test_pessoa_e_empresa_apagadas_aparecem_como_removida_sem_erro(plataforma):
    _evento('pessoa_criada', pessoa=987654, empresa=987655)
    (linha, *_), _ = _ler(plataforma, acao='pessoa_criada')
    assert (linha['quem'], linha['empresa']) == ('removida', 'removida')


def test_evento_do_sistema_aparece_como_sistema(plataforma):
    _evento('conta_bloqueada', detalhes={'segundos': 30})
    (linha, *_), _ = _ler(plataforma, acao='conta_bloqueada')
    assert (linha['quem'], linha['resumo']) == ('Sistema', 'Bloqueada por 30 segundos.')


def test_alvo_de_concessao_ou_convite_mostra_a_pessoa_do_detalhe(cenario, plataforma, fabrica_pessoa):
    afetada = fabrica_pessoa('Pessoa Afetada')
    _evento('concessao_revogada', empresa=cenario.x, detalhes={'pessoa_id': afetada.pk}, alvo_tipo='Concessao', alvo_id=1)
    (linha, *_), _ = _ler(plataforma, acao='concessao_revogada')
    assert linha['alvo'] == 'Acesso de Pessoa Afetada'


def test_detalhe_com_pessoa_id_hostil_nao_derruba_a_leitura(cenario, plataforma):
    for valor in ('abc', None, True, [1], {'a': 1}, 1.5):
        _evento('concessao_revogada', empresa=cenario.x, detalhes={'pessoa_id': valor}, alvo_tipo='Concessao', alvo_id=1)
    linhas, _ = _ler(plataforma, acao='concessao_revogada')
    assert len(linhas) == 6 and all(linha['alvo'] == 'Acesso' for linha in linhas)


def test_janela_padrao_e_de_90_dias_e_desde_abre_o_intervalo(cenario, plataforma):
    velho = _evento(empresa=cenario.x)
    EventoAuditoria.objects.filter(pk=velho.pk).update(hora_servidor=timezone.now() - timedelta(days=91))
    novo = _evento(empresa=cenario.x)
    assert velho.pk not in {linha['id'] for linha in _ler(plataforma)[0]}
    assert novo.pk in {linha['id'] for linha in _ler(plataforma)[0]}
    aberto = {linha['id'] for linha in _ler(plataforma, desde=timezone.now() - timedelta(days=365))[0]}
    assert {velho.pk, novo.pk} <= aberto
    ate_ontem = {linha['id'] for linha in _ler(plataforma, desde=timezone.now() - timedelta(days=365), ate=timezone.now() - timedelta(days=30))[0]}
    assert velho.pk in ate_ontem and novo.pk not in ate_ontem


def test_filtros_de_acao_e_de_quem_agiu(cenario, plataforma, fabrica_pessoa):
    ana, beto = fabrica_pessoa('Ana'), fabrica_pessoa('Beto')
    a1, b1 = _evento('fazenda_criada', ana, cenario.x), _evento('sub_area_criada', beto, cenario.x)
    assert {linha['id'] for linha in _ler(plataforma, acao='fazenda_criada')[0]} == {a1.pk}
    assert {linha['id'] for linha in _ler(plataforma, pessoa_id=beto.pk)[0]} == {b1.pk}
    assert _ler(plataforma, acao='acao_que_nao_existe')[0] == []


def test_historico_da_pessoa_como_alvo_direto_e_pelo_detalhe(cenario, plataforma, fabrica_pessoa):
    alvo, outra = fabrica_pessoa('Alvo'), fabrica_pessoa('Outra')
    direto = _evento('redefinicao_pedida', plataforma, cenario.x, alvo)
    pelo_detalhe = _evento('concessao_criada', plataforma, cenario.x, detalhes={'pessoa_id': alvo.pk}, alvo_tipo='Concessao', alvo_id=5)
    de_outra = _evento('concessao_criada', plataforma, cenario.x, detalhes={'pessoa_id': outra.pk}, alvo_tipo='Concessao', alvo_id=6)
    # `alvo_id` igual ao da pessoa, mas de outro tipo, não é a pessoa.
    homonimo = _evento('fazenda_criada', plataforma, cenario.x, cenario.f1)
    achados = {linha['id'] for linha in _ler(plataforma, alvo_pessoa_id=alvo.pk)[0]}
    assert achados == {direto.pk, pelo_detalhe.pk}
    assert de_outra.pk not in achados and homonimo.pk not in achados


def test_cursor_pagina_do_mais_recente_ao_mais_antigo_sem_repetir(cenario, plataforma):
    criados = [_evento('fazenda_criada', empresa=cenario.x).pk for _ in range(5)]
    primeira, mais = _ler(plataforma, acao='fazenda_criada', limite=2)
    assert [linha['id'] for linha in primeira] == [criados[4], criados[3]]
    assert mais is True
    segunda, mais = _ler(plataforma, acao='fazenda_criada', limite=2, depois=primeira[-1]['id'])
    assert [linha['id'] for linha in segunda] == [criados[2], criados[1]] and mais is True
    ultima, mais = _ler(plataforma, acao='fazenda_criada', limite=2, depois=segunda[-1]['id'])
    assert [linha['id'] for linha in ultima] == [criados[0]] and mais is False


def test_abrir_a_lista_grava_uma_consulta_e_paginar_nao_grava(cenario, plataforma):
    for _ in range(3):
        _evento('fazenda_criada', empresa=cenario.x)
    antes = _contagem_de_consultas()
    primeira, _ = _ler(plataforma, acao='fazenda_criada', limite=2)
    assert _contagem_de_consultas() == antes + 1
    _ler(plataforma, acao='fazenda_criada', limite=2, depois=primeira[-1]['id'])
    assert _contagem_de_consultas() == antes + 1
    consulta = EventoAuditoria.objects.filter(acao='auditoria_consultada').latest('pk')
    assert consulta.pessoa_id == plataforma.pk and consulta.detalhes == {'acao': 'fazenda_criada'}


def test_consulta_do_administrador_de_empresa_fica_na_empresa_dele_e_sem_cpf(cenario, conceder_direto, cpf_novo):
    cpf = cpf_novo()
    admin_x = Pessoa.objects.criar(nome='Admin', email='admin@exemplo.test', cpf=cpf)
    conceder_direto(admin_x, cenario.cargos_x['administrador'], cenario.x)
    _ler(admin_x)
    consulta = EventoAuditoria.objects.filter(acao='auditoria_consultada').latest('pk')
    assert (consulta.pessoa_id, consulta.empresa_id) == (admin_x.pk, cenario.x.pk)
    assert cpf not in str(consulta.detalhes)


def test_consulta_negada_nao_grava_nada(cenario, fabrica_pessoa, conceder_direto):
    curador = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.x)
    antes = _contagem_de_consultas()
    with pytest.raises(ObjectDoesNotExist):
        _ler(curador)
    with pytest.raises(ObjectDoesNotExist):
        _ler(curador, empresa_id=cenario.y.pk)
    assert _contagem_de_consultas() == antes
