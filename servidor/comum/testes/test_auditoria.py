"""Auditoria só de acréscimo (R16, A13): cada ação listada gera um evento, e o papel `app` não altera nem apaga."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import ProgrammingError, connections, transaction

from comum.auditoria import ACOES, auditar
from comum.models import EventoAuditoria
from identidade import login, redefinicao
from identidade.models import Pessoa
from permissao.models import Cargo
from permissao.delegacao import conceder, convidar, revogar_concessao, transferir_titularidade
from territorio.cadastro import criar_empresa, criar_fazenda, criar_sub_area

pytestmark = pytest.mark.django_db
SENHA = 'uma senha longa e unica 2026'
CPF = '529.982.247-25'


def _eventos(acao):
    return list(EventoAuditoria.objects.filter(acao=acao).order_by('pk'))


def test_acoes_de_auditoria_sao_as_do_r16():
    assert ACOES == {
        'empresa_criada', 'fazenda_criada', 'sub_area_criada', 'pessoa_criada', 'concessao_criada',
        'concessao_revogada', 'titularidade_transferida', 'redefinicao_pedida', 'redefinicao_confirmada', 'conta_bloqueada',
        'acesso_reutilizado',
    }


def test_acao_desconhecida_levanta_erro():
    with pytest.raises(ValueError, match='desconhecida'):
        auditar('acao_inventada')


def test_evento_guarda_pessoa_acao_alvo_empresa_e_hora_do_servidor(cenario, plataforma):
    evento = auditar('fazenda_criada', plataforma, cenario.f1, cenario.x.pk, {'nome': 'F1'})
    evento.refresh_from_db()
    assert (evento.pessoa_id, evento.acao, evento.alvo_tipo, evento.alvo_id, evento.empresa_id) == (
        plataforma.pk, 'fazenda_criada', 'Fazenda', cenario.f1.pk, cenario.x.pk,
    )
    assert evento.detalhes == {'nome': 'F1'}
    assert evento.hora_servidor is not None


def test_evento_do_sistema_nao_tem_pessoa_nem_alvo():
    evento = auditar('conta_bloqueada')
    assert (evento.pessoa_id, evento.alvo_tipo, evento.alvo_id, evento.empresa_id, evento.detalhes) == (None, '', None, None, {})


def test_criar_empresa_audita_empresa_pessoa_e_concessao(plataforma, cpf_novo):
    empresa, administrador, _ = criar_empresa(plataforma, 'Empresa Nova', 'Ana', 'ana@exemplo.test', cpf_novo())
    assert [(e.pessoa_id, e.alvo_id, e.empresa_id) for e in _eventos('empresa_criada')] == [(plataforma.pk, empresa.pk, empresa.pk)]
    assert [(e.pessoa_id, e.alvo_id) for e in _eventos('pessoa_criada')] == [(plataforma.pk, administrador.pk)]
    (concessao,) = _eventos('concessao_criada')
    assert concessao.detalhes['pessoa_id'] == administrador.pk


def test_criar_fazenda_e_sub_area_auditam(plataforma, cenario):
    fazenda = criar_fazenda(plataforma, cenario.x, 'F9')
    sub_area = criar_sub_area(plataforma, fazenda, 'G9')
    assert [(e.pessoa_id, e.alvo_tipo, e.alvo_id) for e in _eventos('fazenda_criada')] == [(plataforma.pk, 'Fazenda', fazenda.pk)]
    assert [(e.alvo_tipo, e.alvo_id, e.empresa_id) for e in _eventos('sub_area_criada')] == [('SubArea', sub_area.pk, cenario.x.pk)]


def test_convidar_audita_a_pessoa_e_a_concessao(plataforma, cenario, cpf_novo):
    pessoa, _ = convidar(plataforma, 'Bia', 'bia@exemplo.test', cpf_novo(), cenario.cargos_x['usuario'], cenario.f1)
    assert [e.alvo_id for e in _eventos('pessoa_criada')] == [pessoa.pk]
    (concessao,) = _eventos('concessao_criada')
    assert concessao.detalhes == {
        'pessoa_id': pessoa.pk, 'cargo_id': cenario.cargos_x['usuario'].pk, 'fazenda_id': cenario.f1.pk, 'sub_area_id': None,
    }


def test_conceder_e_revogar_auditam(plataforma, cenario, fabrica_pessoa):
    pessoa = fabrica_pessoa('Caio')
    concessao = conceder(plataforma, pessoa, cenario.cargos_x['usuario'], cenario.f1)
    revogar_concessao(plataforma, concessao)
    assert [(e.pessoa_id, e.alvo_id) for e in _eventos('concessao_criada')] == [(plataforma.pk, concessao.pk)]
    assert [(e.pessoa_id, e.alvo_id, e.detalhes) for e in _eventos('concessao_revogada')] == [
        (plataforma.pk, concessao.pk, {'pessoa_id': pessoa.pk})
    ]


def test_transferir_titularidade_audita_de_e_para(plataforma, cpf_novo):
    empresa, titular, _ = criar_empresa(plataforma, 'Empresa T', 'Tito', 'tito@exemplo.test', cpf_novo())
    cargo = Cargo.objects.get(empresa=empresa, base='administrador')
    novo, _ = convidar(plataforma, 'Nina', 'nina@exemplo.test', cpf_novo(), cargo, empresa)
    transferir_titularidade(plataforma, empresa, novo)
    assert [(e.pessoa_id, e.alvo_id, e.detalhes) for e in _eventos('titularidade_transferida')] == [
        (plataforma.pk, empresa.pk, {'de': titular.pk, 'para': novo.pk})
    ]


def test_acao_negada_nao_deixa_evento(cenario, fabrica_pessoa, cpf_novo):
    intruso = fabrica_pessoa('Intruso')
    cpf = cpf_novo()
    with pytest.raises(PermissionDenied):
        criar_fazenda(intruso, cenario.x, 'F9')
    with pytest.raises(PermissionDenied):
        criar_empresa(intruso, 'Empresa Intrusa', 'Ivo', 'ivo@exemplo.test', cpf)
    assert EventoAuditoria.objects.count() == 0


def test_acao_que_falha_depois_desfaz_o_evento(plataforma, cpf_novo, monkeypatch):
    def falha(*_):
        raise OSError('smtp fora')

    monkeypatch.setattr('identidade.email.enviar_senha_temporaria', falha)
    cpf = cpf_novo()
    with pytest.raises(OSError):
        criar_empresa(plataforma, 'Empresa Falha', 'Fabio', 'fabio@exemplo.test', cpf)
    assert EventoAuditoria.objects.count() == 0


@pytest.fixture
def pessoa_com_senha():
    pessoa = Pessoa.objects.criar(nome='Ana Souza', email='ana@exemplo.test', cpf=CPF)
    pessoa.set_password(SENHA)
    pessoa.save()
    return pessoa


def test_redefinicao_audita_pedido_e_confirmacao_sem_o_segredo(pessoa_com_senha, mailoutbox):
    redefinicao.pedir_redefinicao(CPF)
    segredo = mailoutbox[0].body.split('segredo=')[1].split()[0]
    redefinicao.confirmar_redefinicao(segredo, 'outra senha longa e unica 2026')
    (pedido,) = _eventos('redefinicao_pedida')
    (confirmacao,) = _eventos('redefinicao_confirmada')
    # Pedido anônimo (sem sessão): o ator fica vazio, não vira o dono da conta.
    assert (pedido.pessoa_id, pedido.alvo_id) == (None, pessoa_com_senha.pk)
    assert (confirmacao.pessoa_id, confirmacao.alvo_id) == (None, pessoa_com_senha.pk)
    assert segredo not in str([(e.detalhes, e.alvo_tipo) for e in (pedido, confirmacao)])


def test_senha_recusada_na_redefinicao_nao_audita_confirmacao(pessoa_com_senha, mailoutbox):
    redefinicao.pedir_redefinicao(CPF)
    segredo = mailoutbox[0].body.split('segredo=')[1].split()[0]
    with pytest.raises(ValidationError) as recusa:
        redefinicao.confirmar_redefinicao(segredo, 'curta')
    assert recusa.value.code == 'senha_curta'
    assert _eventos('redefinicao_confirmada') == []


def test_bloqueio_de_conta_audita_com_a_duracao(pessoa_com_senha):
    for _ in range(4):
        login.autenticar(CPF, 'errada errada errada')
    assert _eventos('conta_bloqueada') == []
    login.autenticar(CPF, 'errada errada errada')
    (evento,) = _eventos('conta_bloqueada')
    assert (evento.pessoa_id, evento.alvo_id, evento.detalhes) == (None, pessoa_com_senha.pk, {'segundos': 30})


def _executar_como_app(comando):
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        consulta.execute(comando)


@pytest.mark.django_db(databases=['default', 'app'])
@pytest.mark.parametrize('comando', ["UPDATE evento_auditoria SET acao = 'x'", 'DELETE FROM evento_auditoria', 'TRUNCATE evento_auditoria'])
def test_papel_app_nao_altera_nem_apaga_a_auditoria(comando):
    with pytest.raises(ProgrammingError, match='permission denied'):
        _executar_como_app(comando)


@pytest.mark.django_db(databases=['default', 'app'])
def test_papel_app_insere_e_le_a_auditoria():
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        consulta.execute("INSERT INTO evento_auditoria (acao, alvo_tipo, detalhes) VALUES ('fazenda_criada', '', '{}')")
        consulta.execute('SELECT count(*) FROM evento_auditoria')
        assert consulta.fetchone()[0] >= 1
        transaction.set_rollback(True)
