"""A5, A14 (R5, R15): redefinição de senha por link.

O ramo do Administrador de empresa (origem ou concessão ativa) fecha na Fase 3 (T3.4a): depende de cargo e concessão.
"""

import re
import threading
from pathlib import Path
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import RequestFactory
from django.utils import timezone

from identidade import cpf as modulo_cpf
from identidade import email, login, redefinicao, senha, sessao
from identidade.models import PedidoRedefinicao, Pessoa
from identidade.testes.conftest import CPF, SENHA
from permissao.models import Cargo, CargoPermissao

pytestmark = pytest.mark.django_db

NOVA = 'senha-nova-bem-comprida-1'


def _em_paralelo(*funcoes):
    """Roda as funções ao mesmo tempo, cada uma na sua conexão, e relança o erro de qualquer uma."""
    largada = threading.Barrier(len(funcoes))
    erros = []

    def correr(funcao):
        largada.wait()
        try:
            funcao()
        except Exception as erro:
            erros.append(erro)

    fios = [threading.Thread(target=correr, args=(f,)) for f in funcoes]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert erros == []


def _segredo(mailoutbox):
    achado = re.search(r'segredo=(\S+)', mailoutbox[-1].body)
    assert achado is not None
    return achado.group(1)


def _agora_em(monkeypatch, instante):
    monkeypatch.setattr(timezone, 'now', lambda: instante)


@pytest.fixture
def outra_pessoa(db):
    return Pessoa.objects.criar(nome='Joana Souza', email='joana@exemplo.test', cpf='529.982.247-25')


def test_a_propria_pessoa_pede_e_recebe_o_link_montado_com_url_base(pessoa, mailoutbox):
    assert redefinicao.pedir_redefinicao(CPF) is None
    pedido = PedidoRedefinicao.objects.get()
    assert pedido.pessoa == pedido.solicitado_por == pessoa
    assert mailoutbox[0].to == [pessoa.email]
    assert f'{settings.URL_BASE}/redefinir-senha?segredo=' in mailoutbox[0].body
    segredo = _segredo(mailoutbox)
    assert pedido.hash_segredo == sessao.hash_do_segredo(segredo) != segredo


def test_resposta_e_neutra_para_cpf_inexistente_invalido_e_existente(pessoa, mailoutbox):
    resultados = {repr(redefinicao.pedir_redefinicao(c)) for c in (CPF, '999.999.999-99', 'lixo')}
    assert resultados == {'None'}
    assert len(mailoutbox) == 1
    assert PedidoRedefinicao.objects.count() == 1


def test_tecnico_nao_pede_a_redefinicao_de_outra_pessoa(pessoa, outra_pessoa, mailoutbox):
    redefinicao.pedir_redefinicao(CPF, solicitante=outra_pessoa)
    assert PedidoRedefinicao.objects.count() == 0
    assert mailoutbox == []


def test_administrador_da_plataforma_inicia_e_fica_registrado(pessoa, outra_pessoa, mailoutbox):
    outra_pessoa.administrador_plataforma = True
    outra_pessoa.save()
    redefinicao.pedir_redefinicao(CPF, solicitante=outra_pessoa)
    pedido = PedidoRedefinicao.objects.get()
    assert pedido.pessoa == pessoa
    assert pedido.solicitado_por == outra_pessoa
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [pessoa.email]


def test_pedido_nao_conta_falha_nem_bloqueia(pessoa, monkeypatch):
    pessoa.falhas_consecutivas = 2
    pessoa.save()
    t0 = timezone.now()
    for i in range(10):
        _agora_em(monkeypatch, t0 + timedelta(minutes=2 * i))
        redefinicao.pedir_redefinicao(CPF)
    pessoa.refresh_from_db()
    assert pessoa.falhas_consecutivas == 2
    assert pessoa.bloqueada_ate is None


def test_pedidos_em_sequencia_dentro_de_1_minuto_nao_enchem_a_caixa(pessoa, mailoutbox, monkeypatch):
    # Achado do Qodo (PR #9): cada pedido mandava e-mail e derrubava o link anterior, sem limite.
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    for _ in range(5):
        redefinicao.pedir_redefinicao(CPF)
    assert len(mailoutbox) == 1
    assert PedidoRedefinicao.objects.count() == 1
    _agora_em(monkeypatch, t0 + timedelta(minutes=1))
    redefinicao.pedir_redefinicao(CPF)
    assert len(mailoutbox) == 2
    assert PedidoRedefinicao.objects.count() == 2


def test_pedido_trava_a_pessoa_para_nao_deixar_dois_links_validos(pessoa):
    # Achado do Qodo (PR #9): sem a trava, dois pedidos simultâneos deixariam dois links de pé.
    with CaptureQueriesContext(connection) as consultas:
        redefinicao.pedir_redefinicao(CPF)
    assert any('FOR UPDATE' in c['sql'] and '"pessoa"' in c['sql'] for c in consultas)


def test_falha_do_smtp_desfaz_o_pedido_e_mantem_o_link_anterior(pessoa, mailoutbox, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    redefinicao.pedir_redefinicao(CPF)
    anterior = _segredo(mailoutbox)
    _agora_em(monkeypatch, t0 + timedelta(minutes=2))

    def falha(*_):
        raise OSError('smtp fora')

    monkeypatch.setattr(email, 'enviar_link_de_redefinicao', falha)
    with pytest.raises(OSError):
        redefinicao.pedir_redefinicao(CPF)
    assert PedidoRedefinicao.objects.count() == 1
    redefinicao.confirmar_redefinicao(anterior, NOVA)


def test_apagar_pessoa_que_pediu_a_propria_redefinicao_funciona(pessoa):
    # Achado do Qodo (PR #9): PROTECT em solicitado_por travava a exclusão.
    redefinicao.pedir_redefinicao(CPF)
    pessoa.delete()
    assert PedidoRedefinicao.objects.count() == 0


def test_apagar_o_administrador_que_pediu_preserva_o_pedido(pessoa, outra_pessoa):
    outra_pessoa.administrador_plataforma = True
    outra_pessoa.save()
    redefinicao.pedir_redefinicao(CPF, solicitante=outra_pessoa)
    outra_pessoa.delete()
    assert PedidoRedefinicao.objects.get().solicitado_por is None


def test_cpf_ausente_nao_derruba_o_pedido(pessoa):
    assert redefinicao.pedir_redefinicao(None) is None


def test_pedido_novo_invalida_o_anterior(pessoa, mailoutbox, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    redefinicao.pedir_redefinicao(CPF)
    antigo = _segredo(mailoutbox)
    _agora_em(monkeypatch, t0 + timedelta(minutes=2))
    redefinicao.pedir_redefinicao(CPF)
    with pytest.raises(ValidationError) as erro:
        redefinicao.confirmar_redefinicao(antigo, NOVA)
    assert erro.value.code == 'link_invalido'


def test_confirmar_troca_a_senha_uma_vez_e_nao_abre_sessao(pessoa, mailoutbox):
    redefinicao.pedir_redefinicao(CPF)
    segredo = _segredo(mailoutbox)
    assert redefinicao.confirmar_redefinicao(segredo, NOVA) is None
    assert login.autenticar(CPF, NOVA) == pessoa
    assert login.autenticar(CPF, SENHA) is None
    assert len(mailoutbox) == 2
    assert 'alterada' in mailoutbox[1].body
    with pytest.raises(ValidationError) as erro:
        redefinicao.confirmar_redefinicao(segredo, NOVA)
    assert erro.value.code == 'link_invalido'


def test_link_vence_aos_10_minutos(pessoa, mailoutbox, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    redefinicao.pedir_redefinicao(CPF)
    segredo = _segredo(mailoutbox)
    _agora_em(monkeypatch, t0 + timedelta(minutes=10))
    with pytest.raises(ValidationError) as erro:
        redefinicao.confirmar_redefinicao(segredo, NOVA)
    assert erro.value.code == 'link_invalido'
    _agora_em(monkeypatch, t0 + timedelta(minutes=9, seconds=59))
    redefinicao.confirmar_redefinicao(segredo, NOVA)


def test_segredo_de_um_pedido_nao_vale_para_outra_pessoa(pessoa, outra_pessoa, mailoutbox):
    redefinicao.pedir_redefinicao('529.982.247-25')
    segredo_da_joana = _segredo(mailoutbox)
    redefinicao.confirmar_redefinicao(segredo_da_joana, NOVA)
    pessoa.refresh_from_db()
    assert pessoa.check_password(SENHA)
    assert not pessoa.check_password(NOVA)
    with pytest.raises(ValidationError):
        redefinicao.confirmar_redefinicao('segredo-inventado', NOVA)


def test_cinco_tentativas_por_pedido(pessoa, mailoutbox):
    redefinicao.pedir_redefinicao(CPF)
    segredo = _segredo(mailoutbox)
    for _ in range(5):
        with pytest.raises(ValidationError) as erro:
            redefinicao.confirmar_redefinicao(segredo, 'curta')
        assert erro.value.code == 'senha_curta'
    with pytest.raises(ValidationError) as erro:
        redefinicao.confirmar_redefinicao(segredo, NOVA)
    assert erro.value.code == 'link_invalido'
    pessoa.refresh_from_db()
    assert pessoa.check_password(SENHA)


def test_redefinicao_derruba_sessao_aberta_e_acesso_do_aplicativo(pessoa, mailoutbox):
    requisicao = RequestFactory().get('/')
    requisicao.session = SessionStore()
    sessao.iniciar_sessao(requisicao, pessoa)
    acesso = sessao.emitir_acesso(pessoa, 'celular')
    redefinicao.pedir_redefinicao(CPF)
    redefinicao.confirmar_redefinicao(_segredo(mailoutbox), NOVA)
    assert not get_user(requisicao).is_authenticated
    assert sessao.renovar_acesso(acesso) is None


def test_trocar_a_senha_invalida_o_link_pendente(pessoa, mailoutbox):
    # Achado do Codex (PR #9): link pedido antes da troca não pode sobrescrever a senha nova.
    redefinicao.pedir_redefinicao(CPF)
    segredo = _segredo(mailoutbox)
    senha.trocar_senha(pessoa, SENHA, NOVA)
    with pytest.raises(ValidationError) as erro:
        redefinicao.confirmar_redefinicao(segredo, 'terceira-senha-bem-longa')
    assert erro.value.code == 'link_invalido'


def test_nova_senha_temporaria_invalida_o_link_pendente(pessoa, mailoutbox):
    redefinicao.pedir_redefinicao(CPF)
    segredo = _segredo(mailoutbox)
    senha.emitir_senha_temporaria(pessoa)
    with pytest.raises(ValidationError) as erro:
        redefinicao.confirmar_redefinicao(segredo, NOVA)
    assert erro.value.code == 'link_invalido'


def test_redefinicao_encerra_bloqueio_e_troca_obrigatoria(pessoa, mailoutbox):
    pessoa.falhas_consecutivas = 7
    pessoa.bloqueada_ate = timezone.now() + timedelta(minutes=5)
    pessoa.deve_trocar_senha = True
    pessoa.save()
    redefinicao.pedir_redefinicao(CPF)
    redefinicao.confirmar_redefinicao(_segredo(mailoutbox), NOVA)
    pessoa.refresh_from_db()
    assert (pessoa.falhas_consecutivas, pessoa.bloqueada_ate, pessoa.deve_trocar_senha) == (0, None, False)


def test_pedidos_vencidos_da_pessoa_sao_apagados_no_pedido_seguinte(pessoa, monkeypatch):
    # Achado do Qodo (PR #9): sem retenção, a tabela só cresce.
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    redefinicao.pedir_redefinicao(CPF)
    _agora_em(monkeypatch, t0 + timedelta(minutes=11))
    redefinicao.pedir_redefinicao(CPF)
    assert PedidoRedefinicao.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_dois_pedidos_simultaneos_deixam_um_link_de_pe(pessoa, mailoutbox):
    # Achados do Qodo, Sourcery e Greptile (PR #9): sem a trava na pessoa, os dois criavam link.
    def pedir():
        try:
            redefinicao.pedir_redefinicao(CPF)
        finally:
            connection.close()

    _em_paralelo(pedir, pedir)
    assert PedidoRedefinicao.objects.filter(usado_em__isnull=True).count() == 1
    assert len(mailoutbox) == 1


def _troca_normal(pessoa):
    senha.trocar_senha(Pessoa.objects.get(pk=pessoa.pk), SENHA, 'senha-vinda-da-troca-normal')


def _senha_temporaria(pessoa):
    senha.emitir_senha_temporaria(Pessoa.objects.get(pk=pessoa.pk))


def _novo_pedido(pessoa):
    redefinicao.pedir_redefinicao(CPF)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('concorrente', [_troca_normal, _senha_temporaria, _novo_pedido])
def test_confirmacao_simultanea_a_outra_operacao_da_pessoa_nao_da_deadlock(pessoa, concorrente):
    # Achados do Greptile e do Codex (PR #9): a confirmação travava pedido e depois pessoa; as outras operações,
    # o inverso.
    for rodada in range(8):
        Pessoa.objects.filter(pk=pessoa.pk).update(password=make_password(SENHA))
        segredo = f'segredo-da-rodada-{rodada}'
        PedidoRedefinicao.objects.create(
            pessoa=pessoa,
            hash_segredo=sessao.hash_do_segredo(segredo),
            solicitado_por=pessoa,
            expira_em=timezone.now() + timedelta(minutes=10),
        )
        resultados = []
        largada = threading.Barrier(2)

        def correr(funcao):
            largada.wait()
            try:
                funcao()
                resultados.append('ok')
            except ValidationError as erro:
                resultados.append(erro.code)
            except Exception as erro:
                resultados.append(f'erro {type(erro).__name__}')
            finally:
                connection.close()

        def confirmar():
            redefinicao.confirmar_redefinicao(segredo, 'senha-vinda-da-confirmacao')

        def outra():
            concorrente(pessoa)

        fios = [threading.Thread(target=correr, args=(f,)) for f in (confirmar, outra)]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join()
        assert [r for r in resultados if r.startswith('erro')] == []
        assert len(resultados) == 2


# --- T3.4a (R5, A5): o Administrador de empresa inicia a redefinição de quem tem vínculo com a empresa dele ---


@pytest.fixture
def vinculos(cenario, fabrica_pessoa, conceder_direto):
    """Administrador de X e de Y; `da_x` tem origem em X; `externo` tem origem em Y e concessão em X."""
    admin_x, admin_y = fabrica_pessoa('Admin da X'), fabrica_pessoa('Admin da Y')
    conceder_direto(admin_x, cenario.cargos_x['administrador'], cenario.x)
    conceder_direto(admin_y, cenario.cargos_y['administrador'], cenario.y)
    da_x = fabrica_pessoa('Pessoa da X', empresa_origem=cenario.x)
    externo = fabrica_pessoa('Colaborador Externo', empresa_origem=cenario.y)
    concessao = conceder_direto(externo, cenario.cargos_x['usuario'], cenario.f1)
    return type('Vinculos', (), {'admin_x': admin_x, 'admin_y': admin_y, 'da_x': da_x, 'externo': externo, 'concessao': concessao})


def test_administrador_da_empresa_de_origem_inicia(vinculos):
    assert redefinicao.pode_iniciar_redefinicao(vinculos.admin_x, vinculos.da_x) is True


def test_administrador_da_empresa_com_concessao_ativa_do_colaborador_externo_inicia(vinculos):
    assert redefinicao.pode_iniciar_redefinicao(vinculos.admin_x, vinculos.externo) is True
    assert redefinicao.pode_iniciar_redefinicao(vinculos.admin_y, vinculos.externo) is True  # a de origem dele


def test_administrador_de_empresa_sem_vinculo_nao_inicia(vinculos):
    assert redefinicao.pode_iniciar_redefinicao(vinculos.admin_y, vinculos.da_x) is False


def test_concessao_revogada_ou_vencida_nao_da_vinculo(vinculos, cenario, fabrica_pessoa, conceder_direto, monkeypatch):
    revogador = fabrica_pessoa('Quem Revoga')
    concessao = vinculos.concessao
    concessao.revogada_em = timezone.now()
    concessao.revogada_por = revogador
    concessao.save()
    so_em_x = fabrica_pessoa('Só com concessão em X')
    vencida = conceder_direto(
        so_em_x, cenario.cargos_x['usuario'], cenario.f1,
        inicio=timezone.now() - timedelta(days=2), fim=timezone.now() - timedelta(days=1),
    )  # fmt: skip
    assert vencida.pk is not None
    # `externo` mantém a origem em Y: o Administrador de X perdeu o vínculo, o de Y não.
    assert redefinicao.pode_iniciar_redefinicao(vinculos.admin_x, vinculos.externo) is False
    assert redefinicao.pode_iniciar_redefinicao(vinculos.admin_y, vinculos.externo) is True
    assert redefinicao.pode_iniciar_redefinicao(vinculos.admin_x, so_em_x) is False


def test_concessao_com_inicio_no_futuro_nao_da_vinculo(vinculos, cenario, fabrica_pessoa, conceder_direto):
    futuro = fabrica_pessoa('Começa Amanhã')
    conceder_direto(futuro, cenario.cargos_x['usuario'], cenario.f1, inicio=timezone.now() + timedelta(days=1))
    assert redefinicao.pode_iniciar_redefinicao(vinculos.admin_x, futuro) is False


def test_tecnico_e_curador_da_empresa_nao_iniciam(vinculos, cenario, fabrica_pessoa, conceder_direto):
    for base in ('tecnico', 'curador'):
        quem = fabrica_pessoa(f'Pessoa {base}')
        conceder_direto(quem, cenario.cargos_x[base], cenario.x)
        assert redefinicao.pode_iniciar_redefinicao(quem, vinculos.da_x) is False


def test_administrador_so_de_fazenda_nao_inicia(vinculos, cenario, fabrica_pessoa, conceder_direto):
    na_fazenda = fabrica_pessoa('Admin da F1')
    conceder_direto(na_fazenda, cenario.cargos_x['administrador'], cenario.f1)
    assert redefinicao.pode_iniciar_redefinicao(na_fazenda, vinculos.da_x) is False


def test_administrador_sem_redefinir_senha_no_cargo_nao_inicia(vinculos, cenario, fabrica_pessoa, conceder_direto):
    capado = Cargo.objects.create(empresa=cenario.x, nome='Admin sem redefinir', base='administrador')
    CargoPermissao.objects.create(cargo=capado, permissao_id='ver')
    quem = fabrica_pessoa('Admin Capado')
    conceder_direto(quem, capado, cenario.x)
    assert redefinicao.pode_iniciar_redefinicao(quem, vinculos.da_x) is False


def test_administrador_de_empresa_nunca_escolhe_a_senha_e_o_link_vai_para_a_pessoa(vinculos, cenario, mailoutbox):
    redefinicao.pedir_redefinicao('', solicitante=vinculos.admin_x)  # CPF inválido: resposta neutra
    assert mailoutbox == []
    pessoa_alvo = Pessoa.objects.get(pk=vinculos.da_x.pk)
    cpf_alvo = modulo_cpf.decifrar(pessoa_alvo.cpf_cifrado)
    redefinicao.pedir_redefinicao(cpf_alvo, solicitante=vinculos.admin_x)
    assert mailoutbox[0].to == [pessoa_alvo.email]
    assert PedidoRedefinicao.objects.get().solicitado_por == vinculos.admin_x


def test_administrador_sem_vinculo_pedindo_nao_envia_nem_registra(vinculos, mailoutbox):
    cpf_alvo = modulo_cpf.decifrar(Pessoa.objects.get(pk=vinculos.da_x.pk).cpf_cifrado)
    assert redefinicao.pedir_redefinicao(cpf_alvo, solicitante=vinculos.admin_y) is None
    assert PedidoRedefinicao.objects.count() == 0
    assert mailoutbox == []


def test_o_atalho_da_fase_2_saiu_do_codigo():
    assert 'shortcut:' not in Path(redefinicao.__file__).read_text(encoding='utf-8')
