"""Leitura da auditoria (005 R2 a R4, R7; A1 a A5, A7): escopo por empresa, papéis, nomes sem CPF e a própria consulta auditada."""

from datetime import timedelta

import pytest
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from comum.models import EventoAuditoria
from identidade.models import Pessoa
from permissao.auditoria_leitura import consultar, data_da_janela_padrao, inicio_do_dia, pessoas_citadas
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


def _pessoas(quem):
    esquecer(quem)
    with com_permissao(quem, 'ver_auditoria'):
        return pessoas_citadas(quem)


def test_administrador_de_empresa_ve_so_os_eventos_dela_e_empresa_alheia_da_404(cenario, fabrica_pessoa, conceder_direto):
    admin_x = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    de_x, de_y = _evento(empresa=cenario.x), _evento(empresa=cenario.y)
    ids = {linha['id'] for linha in _ler(admin_x)[0]}
    assert de_x.pk in ids
    assert de_y.pk not in ids
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
    sem_nada = fabrica_pessoa('Sem Nada')
    with pytest.raises(ObjectDoesNotExist):
        _ler(sem_nada)


def test_pode_ver_auditoria_so_para_plataforma_e_administrador_de_empresa(cenario, plataforma, fabrica_pessoa, conceder_direto):
    from permissao.auditoria_leitura import pode_ver_auditoria

    admin_x = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    curador_x = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.x, 'Curador')
    so_fazenda = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.f1, 'Admin da Fazenda')
    assert pode_ver_auditoria(plataforma) is True
    assert pode_ver_auditoria(admin_x) is True
    assert pode_ver_auditoria(curador_x) is False
    assert pode_ver_auditoria(so_fazenda) is False
    assert pode_ver_auditoria(fabrica_pessoa('Sem nada')) is False


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
    assert de_y.pk in so_y
    assert de_x.pk not in so_y


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
    assert cpf_quem not in texto
    assert cpf_alvo not in texto
    assert quem.email not in texto
    assert 'nao-deve-aparecer' not in texto
    assert 'cpf' not in set(linha)


def test_pessoa_e_empresa_apagadas_aparecem_como_removida_sem_erro(plataforma):
    _evento('pessoa_criada', pessoa=987654, empresa=987655)
    (linha, *_), _ = _ler(plataforma, acao='pessoa_criada')
    assert (linha['quem'], linha['empresa']) == ('removida', 'removida')


def test_evento_do_sistema_aparece_como_sistema(plataforma):
    _evento('conta_bloqueada', detalhes={'segundos': 30})
    (linha, *_), _ = _ler(plataforma, acao='conta_bloqueada')
    assert (linha['quem'], linha['resumo']) == ('Sistema', 'Bloqueada por 30 segundos.')


def test_alvo_de_concessao_mostra_a_pessoa_do_detalhe(cenario, plataforma, fabrica_pessoa):
    afetada = fabrica_pessoa('Pessoa Afetada')
    _evento('concessao_revogada', empresa=cenario.x, detalhes={'pessoa_id': afetada.pk}, alvo_tipo='Concessao', alvo_id=1)
    (linha, *_), _ = _ler(plataforma, acao='concessao_revogada')
    assert linha['alvo'] == 'Acesso de Pessoa Afetada'


def test_convite_nao_nomeia_a_pessoa_convidada_nem_quem_recusou(cenario, plataforma, fabrica_pessoa):
    """Greptile e Sourcery (PR #55): convidar CPF que já existe não revela a conta; a auditoria também não a nomeia."""
    convidada = fabrica_pessoa('Conta Existente')
    for acao in ('convite_criado', 'convite_cancelado'):
        _evento(acao, plataforma, cenario.x, detalhes={'pessoa_id': convidada.pk}, alvo_tipo='Convite', alvo_id=1)
    _evento('convite_recusado', convidada, cenario.x, detalhes={'pessoa_id': convidada.pk}, alvo_tipo='Convite', alvo_id=1)
    linhas, _ = _ler(plataforma, desde=timezone.now() - timedelta(days=1))
    por_acao = {linha['acao']: linha for linha in linhas}
    assert por_acao['convite_criado']['alvo'] == 'Convite'
    assert por_acao['convite_cancelado']['alvo'] == 'Convite'
    assert por_acao['convite_recusado']['quem'] == 'Pessoa convidada'
    assert 'Conta Existente' not in str(linhas)


def test_filtros_por_pessoa_nao_casam_convite_nem_recusa(cenario, plataforma, fabrica_pessoa):
    """Sem isto o filtro viraria a pergunta "esta conta foi convidada?"."""
    convidada = fabrica_pessoa('Conta Existente')
    _evento('convite_criado', plataforma, cenario.x, detalhes={'pessoa_id': convidada.pk}, alvo_tipo='Convite', alvo_id=1)
    _evento('convite_recusado', convidada, cenario.x, detalhes={'pessoa_id': convidada.pk}, alvo_tipo='Convite', alvo_id=1)
    assert _ler(plataforma, alvo_pessoa_id=convidada.pk)[0] == []
    assert _ler(plataforma, pessoa_id=convidada.pk)[0] == []


def test_convite_aceito_aparece_no_historico_de_quem_aceitou_porque_agora_ha_vinculo(cenario, plataforma, fabrica_pessoa):
    aceitou = fabrica_pessoa('Quem Aceitou')
    evento = _evento('convite_aceito', aceitou, cenario.x, detalhes={'pessoa_id': aceitou.pk}, alvo_tipo='Convite', alvo_id=1)
    assert {linha['id'] for linha in _ler(plataforma, pessoa_id=aceitou.pk)[0]} == {evento.pk}


def test_convite_aceito_aparece_no_filtro_de_pessoa_como_alvo_e_o_convite_criado_nao(cenario, plataforma, fabrica_pessoa):
    """O aceite tem vínculo, então entra no filtro `alvo_pessoa_id`; o convite criado a quem não tem conta continua de fora."""
    aceitou = fabrica_pessoa('Quem Aceitou')
    evento = _evento('convite_aceito', aceitou, cenario.x, detalhes={'pessoa_id': aceitou.pk}, alvo_tipo='Convite', alvo_id=1)
    _evento('convite_criado', plataforma, cenario.x, detalhes={'pessoa_id': aceitou.pk}, alvo_tipo='Convite', alvo_id=1)
    assert {linha['id'] for linha in _ler(plataforma, alvo_pessoa_id=aceitou.pk)[0]} == {evento.pk}


def test_consulta_gravada_nao_volta_na_lista_da_pessoa_que_ela_filtrava(cenario, plataforma, fabrica_pessoa):
    """Sem `exclude(acao='auditoria_consultada')`, uma consulta com `detalhes.pessoa_id` = X apareceria no histórico de X."""
    alvo = fabrica_pessoa('Alvo da Consulta')
    gravada_antes = _evento('auditoria_consultada', plataforma, detalhes={'pessoa_id': alvo.pk})
    _ler(plataforma, alvo_pessoa_id=alvo.pk)
    _ler(plataforma)
    linhas, _ = _ler(plataforma, alvo_pessoa_id=alvo.pk)
    assert gravada_antes.pk not in {linha['id'] for linha in linhas}
    assert 'auditoria_consultada' not in {linha['acao'] for linha in linhas}


def test_titular_que_saiu_ve_a_transferencia_no_historico_dele(cenario, plataforma, fabrica_pessoa):
    antigo, novo = fabrica_pessoa('Titular Antigo'), fabrica_pessoa('Titular Novo')
    transferencia = _evento('titularidade_transferida', plataforma, cenario.x, detalhes={'de': antigo.pk, 'para': novo.pk, 'pessoa_id': novo.pk}, alvo_tipo='Empresa', alvo_id=cenario.x.pk)
    assert {linha['id'] for linha in _ler(plataforma, alvo_pessoa_id=antigo.pk)[0]} == {transferencia.pk}
    assert {linha['id'] for linha in _ler(plataforma, alvo_pessoa_id=novo.pk)[0]} == {transferencia.pk}


def test_nivel_definido_mostra_o_nivel_afetado_e_removida_se_ja_nao_existe(cenario, plataforma):
    from territorio.models import NivelDivisao

    nivel = NivelDivisao.objects.filter(empresa=cenario.x).first() or NivelDivisao.objects.create(empresa=cenario.x, nivel=1, nome='Quadra')
    _evento('nivel_definido', plataforma, cenario.x, nivel, {'nivel': nivel.nivel, 'nome_antigo': None, 'nome_novo': nivel.nome})
    _evento('nivel_definido', plataforma, cenario.x, detalhes={'nivel': 3}, alvo_tipo='NivelDivisao', alvo_id=999999)
    alvos = sorted(linha['alvo'] for linha in _ler(plataforma, acao='nivel_definido')[0])
    assert alvos == sorted([f'Nível: {nivel.nome}', 'Nível: removida'])


def test_detalhe_com_pessoa_id_hostil_nao_derruba_a_leitura(cenario, plataforma):
    for valor in ('abc', None, True, [1], {'a': 1}, 1.5):
        _evento('concessao_revogada', empresa=cenario.x, detalhes={'pessoa_id': valor}, alvo_tipo='Concessao', alvo_id=1)
    linhas, _ = _ler(plataforma, acao='concessao_revogada')
    assert len(linhas) == 6
    assert all(linha['alvo'] == 'Acesso' for linha in linhas)


def test_janela_padrao_e_de_90_dias_e_desde_abre_o_intervalo(cenario, plataforma):
    velho = _evento(empresa=cenario.x)
    EventoAuditoria.objects.filter(pk=velho.pk).update(hora_servidor=timezone.now() - timedelta(days=91))
    novo = _evento(empresa=cenario.x)
    assert velho.pk not in {linha['id'] for linha in _ler(plataforma)[0]}
    assert novo.pk in {linha['id'] for linha in _ler(plataforma)[0]}
    aberto = {linha['id'] for linha in _ler(plataforma, desde=timezone.now() - timedelta(days=365))[0]}
    assert {velho.pk, novo.pk} <= aberto
    ate_ontem = {linha['id'] for linha in _ler(plataforma, desde=timezone.now() - timedelta(days=365), ate=timezone.now() - timedelta(days=30))[0]}
    assert velho.pk in ate_ontem
    assert novo.pk not in ate_ontem


def test_janela_padrao_comeca_a_meia_noite_de_90_dias_atras(cenario, plataforma):
    """A tela e a API cortam no mesmo ponto: o início é o dia inteiro (o link "Mais antigos" só leva data)."""
    inicio = inicio_do_dia(data_da_janela_padrao(timezone.now()))
    dentro, antes = _evento(empresa=cenario.x), _evento(empresa=cenario.x)
    EventoAuditoria.objects.filter(pk=dentro.pk).update(hora_servidor=inicio + timedelta(minutes=1))
    EventoAuditoria.objects.filter(pk=antes.pk).update(hora_servidor=inicio - timedelta(minutes=1))
    ids = {linha['id'] for linha in _ler(plataforma)[0]}
    assert dentro.pk in ids
    assert antes.pk not in ids


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
    assert de_outra.pk not in achados
    assert homonimo.pk not in achados


def test_cursor_pagina_do_mais_recente_ao_mais_antigo_sem_repetir(cenario, plataforma):
    criados = [_evento('fazenda_criada', empresa=cenario.x).pk for _ in range(5)]
    primeira, mais = _ler(plataforma, acao='fazenda_criada', limite=2)
    assert [linha['id'] for linha in primeira] == [criados[4], criados[3]]
    assert mais is True
    segunda, mais = _ler(plataforma, acao='fazenda_criada', limite=2, depois=primeira[-1]['id'])
    assert [linha['id'] for linha in segunda] == [criados[2], criados[1]]
    assert mais is True
    ultima, mais = _ler(plataforma, acao='fazenda_criada', limite=2, depois=segunda[-1]['id'])
    assert [linha['id'] for linha in ultima] == [criados[0]]
    assert mais is False


def test_abrir_a_lista_grava_uma_consulta_e_paginar_nao_grava(cenario, plataforma):
    for _ in range(3):
        _evento('fazenda_criada', empresa=cenario.x)
    antes = _contagem_de_consultas()
    primeira, _ = _ler(plataforma, acao='fazenda_criada', limite=2)
    assert _contagem_de_consultas() == antes + 1
    _ler(plataforma, acao='fazenda_criada', limite=2, depois=primeira[-1]['id'])
    assert _contagem_de_consultas() == antes + 1
    consulta = EventoAuditoria.objects.filter(acao='auditoria_consultada').latest('pk')
    assert consulta.pessoa_id == plataforma.pk
    assert consulta.detalhes == {'acao': 'fazenda_criada'}


def test_consulta_do_administrador_de_empresa_fica_na_empresa_dele_e_sem_cpf(cenario, conceder_direto, cpf_novo):
    cpf = cpf_novo()
    admin_x = Pessoa.objects.criar(nome='Admin', email='admin@exemplo.test', cpf=cpf)
    conceder_direto(admin_x, cenario.cargos_x['administrador'], cenario.x)
    _ler(admin_x)
    consulta = EventoAuditoria.objects.filter(acao='auditoria_consultada').latest('pk')
    assert (consulta.pessoa_id, consulta.empresa_id) == (admin_x.pk, cenario.x.pk)
    assert cpf not in str(consulta.detalhes)


def test_administrador_de_varias_empresas_deixa_uma_consulta_em_cada_uma(cenario, fabrica_pessoa, conceder_direto):
    """Qodo (PR #55): sem empresa o evento sumiria para todos os leitores que não são da plataforma, ele inclusive."""
    admin = fabrica_pessoa('Admin das Duas')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    conceder_direto(admin, cenario.cargos_y['administrador'], cenario.y)
    _ler(admin)
    consultas = EventoAuditoria.objects.filter(acao='auditoria_consultada', pessoa_id=admin.pk)
    assert sorted(consultas.values_list('empresa_id', flat=True)) == sorted([cenario.x.pk, cenario.y.pk])
    esquecer(admin)
    with com_permissao(admin, 'ver_auditoria'):
        vistas, _ = consultar(admin, acao='auditoria_consultada')
    assert {linha['empresa'] for linha in vistas} == {'Empresa X', 'Empresa Y'}


def test_plataforma_sem_filtro_grava_consulta_sem_empresa_e_com_filtro_na_empresa(cenario, plataforma):
    _ler(plataforma)
    _ler(plataforma, empresa_id=cenario.y.pk)
    empresas = list(EventoAuditoria.objects.filter(acao='auditoria_consultada').order_by('pk').values_list('empresa_id', flat=True))
    assert empresas == [None, cenario.y.pk]


def test_pessoas_citadas_traz_ex_colaborador_sem_concessao_e_o_filtro_devolve_o_historico(cenario, fabrica_pessoa, conceder_direto):
    """Greptile P1, Codex P2 e Sourcery (PR #63): quem saiu não some do filtro, e o filtro traz o histórico dele."""
    admin_x = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    ex = fabrica_pessoa('Ex Colaboradora')
    evento = _evento('fazenda_criada', ex, cenario.x, alvo=cenario.f1)
    assert (ex.pk, 'Ex Colaboradora') in _pessoas(admin_x)
    assert {linha['id'] for linha in _ler(admin_x, pessoa_id=ex.pk)[0]} == {evento.pk}


def test_pessoas_citadas_nao_traz_quem_so_tem_concessao_sem_evento(cenario, fabrica_pessoa, conceder_direto):
    admin_x = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['tecnico'], cenario.x, 'So Diretorio')
    assert 'So Diretorio' not in [rotulo for _, rotulo in _pessoas(admin_x)]


def test_pessoas_citadas_nao_traz_pessoa_de_outra_empresa(cenario, plataforma, fabrica_pessoa, conceder_direto):
    admin_x = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alheia = fabrica_pessoa('Alheia')
    _evento('fazenda_criada', alheia, cenario.y, alvo=cenario.fy)
    assert alheia.pk not in {pk for pk, _ in _pessoas(admin_x)}
    assert alheia.pk in {pk for pk, _ in _pessoas(plataforma)}


def test_pessoas_citadas_diferencia_homonimos_com_origem_ou_id(cenario, plataforma, fabrica_pessoa, conceder_direto):
    admin_x = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    de_x = fabrica_pessoa('Ana', empresa_origem=cenario.x)
    de_y = fabrica_pessoa('Ana', empresa_origem=cenario.y)
    _evento('fazenda_criada', de_x, cenario.x, alvo=cenario.f1)
    _evento('fazenda_criada', de_y, cenario.x, alvo=cenario.f2)  # de_y age em X, mas a origem dela é Y: invisível a quem olha X
    assert dict(_pessoas(admin_x)) == {de_x.pk: 'Ana (Empresa X)', de_y.pk: f'Ana (#{de_y.pk})'}
    _evento('fazenda_criada', de_y, cenario.y, alvo=cenario.fy)
    rotulos = dict(_pessoas(plataforma))
    assert (rotulos[de_x.pk], rotulos[de_y.pk]) == ('Ana (Empresa X)', 'Ana (Empresa Y)')


def test_pessoas_citadas_nao_traz_convidada_sem_vinculo_e_traz_quem_aceitou(cenario, plataforma, fabrica_pessoa):
    """R24 da 003: convite a conta existente não revela a pessoa, nem por recusa; o aceite já tem vínculo."""
    convidada, aceitou = fabrica_pessoa('Conta Existente'), fabrica_pessoa('Quem Aceitou')
    _evento('convite_criado', plataforma, cenario.x, detalhes={'pessoa_id': convidada.pk}, alvo_tipo='Convite', alvo_id=1)
    _evento('convite_recusado', convidada, cenario.x, detalhes={'pessoa_id': convidada.pk}, alvo_tipo='Convite', alvo_id=1)
    _evento('convite_aceito', aceitou, cenario.x, detalhes={'pessoa_id': aceitou.pk}, alvo_tipo='Convite', alvo_id=1)
    pessoas = {pk for pk, _ in _pessoas(plataforma)}
    assert convidada.pk not in pessoas
    assert aceitou.pk in pessoas


def test_pessoas_citadas_nao_traz_o_registro_de_consulta_como_pessoa_afetada(cenario, fabrica_pessoa, conceder_direto):
    """Sem a exclusão de `auditoria_consultada`, um filtro forjado por id alheio viraria opção do select."""
    admin_x = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alheia = fabrica_pessoa('Alheia Forjada')
    _evento('auditoria_consultada', admin_x, cenario.x, detalhes={'pessoa_id': alheia.pk})
    assert alheia.pk not in {pk for pk, _ in _pessoas(admin_x)}


def test_pessoas_citadas_ignora_pessoa_apagada_e_detalhe_hostil_sem_erro(cenario, plataforma):
    _evento('pessoa_criada', pessoa=987654, empresa=cenario.x)
    _evento('concessao_revogada', empresa=cenario.x, detalhes={'pessoa_id': 'abc'}, alvo_tipo='Concessao', alvo_id=1)
    assert _pessoas(plataforma) == []


def test_pessoas_citadas_nega_quem_nao_le_a_auditoria(cenario, fabrica_pessoa, conceder_direto):
    curador = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.x)
    with pytest.raises(ObjectDoesNotExist):
        _pessoas(curador)


def test_consulta_negada_nao_grava_nada(cenario, fabrica_pessoa, conceder_direto):
    curador = _admin(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.x)
    antes = _contagem_de_consultas()
    with pytest.raises(ObjectDoesNotExist):
        _ler(curador)
    with pytest.raises(ObjectDoesNotExist):
        _ler(curador, empresa_id=cenario.y.pk)
    assert _contagem_de_consultas() == antes
