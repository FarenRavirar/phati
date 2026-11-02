"""Telas de pessoas (003 R13 a R17, R28, R33; A26): caso feliz, validação, acesso negado por URL direta e escape de HTML."""

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from django.test import Client
from django.utils import timezone

from comum.models import EventoAuditoria
from identidade.models import PedidoRedefinicao, Pessoa
from permissao.models import Cargo, CargoPermissao, Concessao, Convite

TRECHO_HTML = '<script>alert(1)</script>'


def _sem_nonce(html):
    """O `nonce` da política de conteúdo é aleatório e pode conter 'F2' ou 'FY': tira antes de procurar texto que não deve existir."""
    return re.sub(r' nonce="[^"]*"', '', html)


def _casa(cenario):
    return f'/empresa/{cenario.x.pk}/'


def _telas(cenario, pessoa_id=1, concessao_id=1, convite_id=1):
    """As telas e a ação que cada uma exige: o mesmo laço prova o negado de todas por URL direta (R17)."""
    base = _casa(cenario)
    return {
        'pessoas': base + 'pessoas/',
        'pessoas_convidar': base + 'pessoas/convidar',
        'pessoas_convites': base + 'pessoas/convites',
        'convite_cancelar': base + f'pessoas/convites/{convite_id}/cancelar',
        'convite_reenviar': base + f'pessoas/convites/{convite_id}/reenviar',
        'pessoa_revogar': base + f'pessoa/{pessoa_id}/revogar/{concessao_id}',
        'pessoa_redefinir_senha': base + f'pessoa/{pessoa_id}/redefinir-senha',
        'pessoa_conceder': base + f'pessoa/{pessoa_id}/conceder',
        'titularidade': base + 'titularidade',
    }


@pytest.fixture
def administradora(conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    return conta.pessoa


@pytest.fixture
def titular(administradora, cenario):
    cenario.x.titular = administradora
    cenario.x.save(update_fields=['titular'])
    return administradora


@pytest.fixture
def alvo(cenario, fabrica_pessoa, conceder_direto):
    """Técnico da F1 de X: a pessoa que as telas listam, revogam e redefinem."""
    pessoa = fabrica_pessoa('Alvo Tecnico')
    return pessoa, conceder_direto(pessoa, cenario.cargos_x['tecnico'], cenario.f1)


def _auditoria(acao):
    return list(EventoAuditoria.objects.filter(acao=acao))


# --- acesso negado (R17) ---


def test_deslogado_e_levado_a_entrada_em_toda_tela(cenario):
    cliente = Client()
    for nome, caminho in _telas(cenario).items():
        resposta = cliente.get(caminho)
        assert (nome, resposta.status_code, resposta['Location'].startswith('/entrar')) == (nome, 302, True)
        assert (nome, cliente.post(caminho).status_code) == (nome, 302)


def test_sem_alcance_ou_de_outra_empresa_e_404_em_toda_tela(cliente_logado, conta, cenario, conceder_direto):
    telas = _telas(cenario)
    for nome, caminho in telas.items():
        assert (nome, cliente_logado.get(caminho).status_code) == (nome, 404)
    conceder_direto(conta.pessoa, cenario.cargos_y['administrador'], cenario.y)
    for nome, caminho in telas.items():
        assert (nome, cliente_logado.get(caminho).status_code) == (nome, 404)
        assert (nome, cliente_logado.post(caminho, {'nome': 'Invasora'}).status_code) == (nome, 404)
    assert not Pessoa.objects.filter(nome='Invasora').exists()


def test_tecnico_e_usuario_com_alcance_recebem_403_em_toda_tela(cliente_logado, conta, cenario, conceder_direto, alvo):
    pessoa, concessao = alvo
    telas = _telas(cenario, pessoa.pk, concessao.pk)
    for base in ('tecnico', 'usuario'):
        da_conta = conceder_direto(conta.pessoa, cenario.cargos_x[base], cenario.x)
        for nome, caminho in telas.items():
            assert (base, nome, cliente_logado.get(caminho).status_code) == (base, nome, 403)
            assert (base, nome, cliente_logado.post(caminho, {'nome': 'Invasora'}).status_code) == (base, nome, 403)
        da_conta.delete()
    concessao.refresh_from_db()
    assert concessao.revogada_em is None
    assert not PedidoRedefinicao.objects.exists()


def test_curador_e_administrador_nao_titular_nao_transferem(cliente_logado, conta, cenario, conceder_direto, fabrica_pessoa):
    titular_de_fato = fabrica_pessoa('Titular de fato')
    conceder_direto(titular_de_fato, cenario.cargos_x['administrador'], cenario.x)
    cenario.x.titular = titular_de_fato
    cenario.x.save(update_fields=['titular'])
    caminho = _casa(cenario) + 'titularidade'
    for base in ('curador', 'administrador'):
        da_conta = conceder_direto(conta.pessoa, cenario.cargos_x[base], cenario.x)
        assert (base, cliente_logado.get(caminho).status_code) == (base, 403)
        for etapa in ('1', '2'):
            resposta = cliente_logado.post(caminho, {'etapa': etapa, 'novo_titular': conta.pessoa.pk, 'justificativa': 'Quero.', 'confirmacao': cenario.x.nome})
            assert (base, etapa, resposta.status_code) == (base, etapa, 403)
        da_conta.delete()
    cenario.x.refresh_from_db()
    assert cenario.x.titular == titular_de_fato
    assert _auditoria('titularidade_transferida') == []


def test_views_de_pagina_nao_decidem_permissao():
    # A26: a regra e `pode()` ficam na função de serviço; a view só pergunta o alcance e chama o serviço.
    for arquivo in Path(__file__).resolve().parent.parent.glob('*_paginas.py'):
        assert re.search(r'\bpode\(', arquivo.read_text(encoding='utf-8')) is None, arquivo.name


# --- lista (R13) ---


def test_administradora_ve_as_pessoas_da_empresa_com_cargo_e_sem_cpf_e_nao_ve_as_de_outra(cliente_logado, administradora, cenario, alvo, fabrica_pessoa, conceder_direto):
    de_y = fabrica_pessoa('Pessoa da Y')
    conceder_direto(de_y, cenario.cargos_y['administrador'], cenario.y)
    resposta = cliente_logado.get(_casa(cenario) + 'pessoas/')
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert 'Alvo Tecnico' in html
    assert 'Técnico' in html
    assert 'F1' in html
    assert 'Pessoa da Y' not in html
    assert 'Revogar' in html
    assert 'Redefinir senha' in html
    assert re.search(r'\d{3}\.?\d{3}\.?\d{3}-?\d{2}', html) is None  # nenhum CPF na lista


def test_nome_com_html_e_escapado_na_lista(cliente_logado, administradora, cenario, fabrica_pessoa, conceder_direto):
    conceder_direto(fabrica_pessoa(TRECHO_HTML), cenario.cargos_x['usuario'], cenario.f1)
    html = cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode()
    assert TRECHO_HTML not in html
    assert '&lt;script&gt;' in html


def test_curador_da_fazenda_ve_so_a_fazenda_dele_e_nao_ve_redefinir_nem_transferir(cliente_logado, conta, cenario, conceder_direto, alvo, fabrica_pessoa):
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.f1)
    de_f2 = fabrica_pessoa('Usuario da F2')
    conceder_direto(de_f2, cenario.cargos_x['usuario'], cenario.f2)
    html = cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode()
    assert 'Alvo Tecnico' in html
    assert 'Usuario da F2' not in html
    assert 'Redefinir senha' not in html
    assert 'Transferir a titularidade' not in html
    assert 'Convidar pessoa' in html


def test_empresa_sem_pessoas_mostra_o_vazio_com_a_acao_de_convidar(cliente_logado, conta, cenario):
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    html = cliente_logado.get(f'/empresa/{cenario.y.pk}/pessoas/').content.decode()
    assert 'Nenhuma pessoa com acesso a esta empresa.' in html
    assert f'/empresa/{cenario.y.pk}/pessoas/convidar' in html


def test_empresa_arquivada_segue_listando_e_nao_oferece_convidar(cliente_logado, administradora, cenario, alvo):
    from territorio.cadastro import arquivar, efeitos_do_arquivamento

    arquivar(administradora, cenario.x, efeitos_do_arquivamento(cenario.x))
    resposta = cliente_logado.get(_casa(cenario) + 'pessoas/')
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert 'Alvo Tecnico' in html
    assert 'Convidar pessoa' not in html
    assert 'Revogar' in html
    assert 'Redefinir senha' in html
    assert cliente_logado.get(_casa(cenario) + 'pessoas/convidar').status_code == 403


# --- convidar (R13) ---


def _dados(cenario, cpf, /, **mudanca):
    dados = {
        'nome': 'Pessoa Convidada', 'email': 'convidada@exemplo.test', 'cpf': cpf,
        'cargo': cenario.cargos_x['usuario'].pk, 'escopo': f'fazenda-{cenario.f1.pk}',
    }
    return {**dados, **mudanca}


def test_formulario_de_convite_lista_cargos_e_lugares_da_empresa(cliente_logado, administradora, cenario):
    html = cliente_logado.get(_casa(cenario) + 'pessoas/convidar').content.decode()
    for texto in ('Administrador', 'Curador', 'Técnico', 'Usuário', 'Empresa inteira', 'F1', 'F2', 'Escolher uma sub-área'):
        assert texto in html
    assert 'G1' not in _sem_nonce(html)  # a sub-área não vai no select: tem tela própria
    html = _sem_nonce(html)
    assert 'Empresa Y' not in html
    assert 'FY' not in html


def test_convidar_cpf_novo_cria_a_pessoa_e_a_senha_aparece_uma_vez_sem_cache_log_sessao_nem_auditoria(cliente_logado, administradora, cenario, cpf_novo, caplog, mailoutbox):
    caplog.set_level('DEBUG')
    resposta = cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf_novo()))
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert 'no-store' in resposta['Cache-Control']
    achada = re.search(r'class="senha-temporaria" translate="no">([^<]+)<', html)
    assert achada is not None
    temporaria = achada.group(1)
    pessoa = Pessoa.objects.get(nome='Pessoa Convidada')
    concessao = Concessao.objects.get(pessoa=pessoa)
    assert (concessao.cargo, concessao.fazenda) == (cenario.cargos_x['usuario'], cenario.f1)
    assert pessoa.check_password(temporaria)
    assert temporaria not in caplog.text
    assert temporaria not in str(dict(cliente_logado.session))
    assert all(temporaria not in str(evento.detalhes) for evento in EventoAuditoria.objects.all())
    # Recarregar não repete a senha: é outra tela.
    assert temporaria not in cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode()
    assert temporaria not in cliente_logado.get(_casa(cenario) + 'pessoas/convidar').content.decode()


def test_convidar_cpf_que_ja_existe_grava_convite_pendente_sem_senha_e_sem_dado_da_pessoa(cliente_logado, administradora, cenario, cpf_novo):
    cpf = cpf_novo()
    existente = Pessoa.objects.criar(nome='Ja Cadastrada', email='ja@exemplo.test', cpf=cpf)
    resposta = cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf))
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert 'senha-temporaria' not in html
    assert 'Ja Cadastrada' not in html
    assert Convite.objects.get(pessoa=existente).fazenda_id == cenario.f1.pk
    assert not Concessao.objects.filter(pessoa=existente).exists()  # a concessão nasce no aceite


@pytest.mark.parametrize('mudanca, texto', [
    ({'nome': '   '}, 'Informe um nome'),
    ({'email': 'sem-arroba'}, 'e-mail válido'),
    ({'cpf': '123'}, None),
    ({'cargo': '999999'}, 'Escolha um cargo'),
    ({'escopo': 'fazenda-999999'}, 'Escolha onde'),
    ({'inicio': '2026-02-30'}, 'data válida'),
    ({'inicio': '2026-05-10', 'fim': '2026-05-01'}, 'depois do início'),
])
def test_convidar_com_dado_invalido_volta_ao_formulario_com_o_erro_e_nao_cria_nada(cliente_logado, administradora, cenario, cpf_novo, mudanca, texto):
    antes = Pessoa.objects.count()
    resposta = cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf_novo(), **mudanca))
    assert resposta.status_code == 400
    if texto:
        assert texto in resposta.content.decode()
    assert Pessoa.objects.count() == antes
    assert not Convite.objects.exists()


def test_cargo_de_outra_empresa_e_recusado_e_nada_e_criado(cliente_logado, administradora, cenario, cpf_novo):
    resposta = cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf_novo(), cargo=cenario.cargos_y['usuario'].pk))
    assert resposta.status_code == 400
    assert not Pessoa.objects.filter(nome='Pessoa Convidada').exists()


def test_periodo_com_fim_vale_ate_o_fim_do_dia(cliente_logado, administradora, cenario, cpf_novo):
    fim = (timezone.localdate() + timedelta(days=10)).isoformat()
    cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf_novo(), fim=fim))
    concessao = Concessao.objects.get(pessoa__nome='Pessoa Convidada')
    assert concessao.fim is not None
    assert concessao.fim.astimezone(timezone.get_current_timezone()).date().isoformat() == (timezone.localdate() + timedelta(days=11)).isoformat()


def test_curador_convida_inclusive_com_cargo_personalizado_sem_a_acao_e_nao_concede_administrador(cliente_logado, conta, cenario, conceder_direto, cpf_novo):
    personalizado = Cargo.objects.create(empresa=cenario.x, nome='Gerente da F1', base='curador')  # as do Curador base, sem `convidar_pessoa` nem `revogar_acesso` (D073)
    for codigo in cenario.cargos_x['curador'].permissoes.exclude(codigo__in=('convidar_pessoa', 'revogar_acesso')).values_list('codigo', flat=True):
        CargoPermissao.objects.create(cargo=personalizado, permissao_id=codigo)
    conceder_direto(conta.pessoa, personalizado, cenario.f1)
    caminho = _casa(cenario) + 'pessoas/convidar'
    assert cliente_logado.get(caminho).status_code == 200
    assert cliente_logado.post(caminho, _dados(cenario, cpf_novo())).status_code == 200
    antes = Pessoa.objects.count()
    resposta = cliente_logado.post(caminho, _dados(cenario, cpf_novo(), nome='Outra', cargo=cenario.cargos_x['administrador'].pk))
    assert resposta.status_code == 403
    assert 'Você não pode conceder este cargo neste lugar.' in resposta.content.decode()
    assert Pessoa.objects.count() == antes
    # O Curador da F1 não oferece nem aceita a empresa inteira nem a F2.
    html = cliente_logado.get(caminho).content.decode()
    assert 'Empresa inteira' not in html
    assert f'value="fazenda-{cenario.f2.pk}"' not in html
    resposta = cliente_logado.post(caminho, _dados(cenario, cpf_novo(), nome='Fora', escopo=f'fazenda-{cenario.f2.pk}'))
    assert resposta.status_code == 400
    assert not Pessoa.objects.filter(nome='Fora').exists()


# --- convites enviados (R13) ---


@pytest.fixture
def convite_enviado(cliente_logado, administradora, cenario, cpf_novo):
    cpf = cpf_novo()
    Pessoa.objects.criar(nome='Ja Cadastrada', email='ja@exemplo.test', cpf=cpf)
    cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf))
    return Convite.objects.get()


def test_convites_enviados_lista_so_os_da_empresa_e_nao_mostra_a_pessoa(cliente_logado, convite_enviado, cenario):
    html = cliente_logado.get(_casa(cenario) + 'pessoas/convites').content.decode()
    assert 'Usuário' in html
    assert 'F1' in html
    assert 'Reenviar' in html
    assert 'Cancelar' in html
    assert 'Ja Cadastrada' not in html


def test_cancelar_convite_marca_o_cancelamento_e_audita(cliente_logado, convite_enviado, cenario):
    caminho = _casa(cenario) + f'pessoas/convites/{convite_enviado.pk}/cancelar'
    assert cliente_logado.get(caminho)['Location'].endswith('/pessoas/convites')  # GET não cancela
    convite_enviado.refresh_from_db()
    assert convite_enviado.cancelado_em is None
    resposta = cliente_logado.post(caminho)
    assert resposta.status_code == 302
    assert resposta['Location'].endswith('?feito=cancelado')
    convite_enviado.refresh_from_db()
    assert convite_enviado.cancelado_em is not None
    assert len(_auditoria('convite_cancelado')) == 1
    assert 'Convite cancelado.' in cliente_logado.get(resposta['Location']).content.decode()
    assert cliente_logado.post(caminho).status_code == 400  # já respondido: a regra do serviço volta como erro


def test_reenviar_respeita_o_intervalo_e_depois_renova(cliente_logado, convite_enviado, cenario):
    caminho = _casa(cenario) + f'pessoas/convites/{convite_enviado.pk}/reenviar'
    resposta = cliente_logado.post(caminho)
    assert resposta.status_code == 400
    assert 'Aguarde antes de reenviar.' in resposta.content.decode()
    Convite.objects.filter(pk=convite_enviado.pk).update(enviado_em=timezone.now() - timedelta(minutes=5))
    resposta = cliente_logado.post(caminho)
    assert resposta.status_code == 302
    assert resposta['Location'].endswith('?feito=reenviado')
    convite_enviado.refresh_from_db()
    assert convite_enviado.envios == 2


def test_convite_de_outra_pessoa_e_404_e_nao_muda(cliente_logado, convite_enviado, cenario, conceder_direto, cpf_novo):
    cpf = cpf_novo()
    segunda_administradora = Pessoa.objects.criar('Admin 2', 'segunda_administradora@exemplo.test', cpf)
    segunda_administradora.set_password('cavalo azul sobe o morro')
    segunda_administradora.save()
    conceder_direto(segunda_administradora, cenario.cargos_x['administrador'], cenario.x)
    outro = Client()
    assert outro.post('/entrar', {'cpf': cpf, 'senha': 'cavalo azul sobe o morro'}).status_code == 302
    for acao in ('cancelar', 'reenviar'):
        assert outro.post(_casa(cenario) + f'pessoas/convites/{convite_enviado.pk}/{acao}').status_code == 404
    convite_enviado.refresh_from_db()
    assert convite_enviado.cancelado_em is None
    assert convite_enviado.envios == 1


# --- revogar (R14) ---


def test_confirmacao_de_revogar_diz_que_a_linha_fica_e_revogar_grava_sem_apagar(cliente_logado, administradora, cenario, alvo):
    pessoa, concessao = alvo
    caminho = _casa(cenario) + f'pessoa/{pessoa.pk}/revogar/{concessao.pk}'
    pagina = cliente_logado.get(caminho)
    assert pagina.status_code == 200
    texto = pagina.content.decode()
    assert 'não é apagada' in texto
    assert 'Alvo Tecnico' in texto
    concessao.refresh_from_db()
    assert concessao.revogada_em is None  # GET não revoga
    resposta = cliente_logado.post(caminho)
    assert resposta.status_code == 302
    assert resposta['Location'].endswith('?feito=revogado')
    concessao.refresh_from_db()
    assert concessao.revogada_em is not None
    assert concessao.revogada_por == administradora
    assert Concessao.objects.filter(pk=concessao.pk).exists()  # a linha fica
    assert [e.alvo_id for e in _auditoria('concessao_revogada')] == [concessao.pk]
    assert 'Acesso revogado.' in cliente_logado.get(resposta['Location']).content.decode()


def test_titular_nao_e_revogado_e_a_tela_mostra_a_recusa_do_servico(cliente_logado, titular, cenario, conceder_direto, fabrica_pessoa):
    outro = fabrica_pessoa('Outro Admin')
    conceder_direto(outro, cenario.cargos_x['administrador'], cenario.x)
    cenario.x.titular = outro
    cenario.x.save(update_fields=['titular'])
    de_outro = Concessao.objects.get(pessoa=outro)
    resposta = cliente_logado.post(_casa(cenario) + f'pessoa/{outro.pk}/revogar/{de_outro.pk}')
    assert resposta.status_code == 400
    assert 'O Administrador titular só sai por transferência de titularidade.' in resposta.content.decode()
    de_outro.refresh_from_db()
    assert de_outro.revogada_em is None


def test_curador_revoga_abaixo_dele_e_nao_revoga_administrador(cliente_logado, conta, cenario, conceder_direto, alvo, fabrica_pessoa):
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.f1)
    administrador_da_f1 = fabrica_pessoa('Admin da F1')
    de_admin = conceder_direto(administrador_da_f1, cenario.cargos_x['administrador'], cenario.f1)
    pessoa, concessao = alvo
    assert cliente_logado.post(_casa(cenario) + f'pessoa/{administrador_da_f1.pk}/revogar/{de_admin.pk}').status_code == 403
    de_admin.refresh_from_db()
    assert de_admin.revogada_em is None
    assert cliente_logado.post(_casa(cenario) + f'pessoa/{pessoa.pk}/revogar/{concessao.pk}').status_code == 302
    concessao.refresh_from_db()
    assert concessao.revogada_em is not None


def test_concessao_de_outra_pessoa_ou_empresa_na_url_e_404(cliente_logado, administradora, cenario, alvo, fabrica_pessoa, conceder_direto):
    pessoa, concessao = alvo
    de_y = fabrica_pessoa('Pessoa da Y')
    concessao_y = conceder_direto(de_y, cenario.cargos_y['administrador'], cenario.y)
    base = _casa(cenario)
    for caminho in (
        base + f'pessoa/{pessoa.pk}/revogar/{concessao_y.pk}',  # concessão de outra pessoa e de outra empresa
        base + f'pessoa/{de_y.pk}/revogar/{concessao_y.pk}',  # pessoa de outra empresa
        base + f'pessoa/{administradora.pk}/revogar/{concessao.pk}',  # concessão que não é dessa pessoa
    ):
        assert (caminho, cliente_logado.post(caminho).status_code) == (caminho, 404)
    concessao_y.refresh_from_db()
    assert concessao_y.revogada_em is None


# --- redefinir senha (R15) ---


def test_redefinir_manda_o_link_por_email_e_nenhuma_senha_aparece_em_lugar_algum(cliente_logado, administradora, cenario, alvo, mailoutbox, caplog):
    caplog.set_level('DEBUG')
    pessoa, _ = alvo
    caminho = _casa(cenario) + f'pessoa/{pessoa.pk}/redefinir-senha'
    confirmacao = cliente_logado.get(caminho)
    assert confirmacao.status_code == 200
    assert 'Alvo Tecnico' in confirmacao.content.decode()
    assert not PedidoRedefinicao.objects.exists()  # GET não pede
    resposta = cliente_logado.post(caminho)
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert 'no-store' in resposta['Cache-Control']
    pedido = PedidoRedefinicao.objects.get()
    assert (pedido.pessoa, pedido.solicitado_por) == (pessoa, administradora)
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [pessoa.email]
    achado = re.search(r'segredo=([\w-]+)', mailoutbox[0].body)
    assert achado is not None
    segredo = achado.group(1)
    assert segredo not in html
    assert segredo not in caplog.text
    assert segredo not in str(dict(cliente_logado.session))
    assert all(segredo not in str(evento.detalhes) for evento in EventoAuditoria.objects.all())
    assert 'senha temporária' not in html.lower()
    assert 'senha-temporaria' not in html
    assert [e.alvo_id for e in _auditoria('redefinicao_pedida')] == [pessoa.pk]


def test_curador_nao_redefine_senha_e_pessoa_de_outra_empresa_e_404(cliente_logado, conta, cenario, conceder_direto, alvo, fabrica_pessoa):
    pessoa, _ = alvo
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.x)
    assert cliente_logado.post(_casa(cenario) + f'pessoa/{pessoa.pk}/redefinir-senha').status_code == 403
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    de_y = fabrica_pessoa('Pessoa da Y')
    conceder_direto(de_y, cenario.cargos_y['usuario'], cenario.y)
    assert cliente_logado.post(_casa(cenario) + f'pessoa/{de_y.pk}/redefinir-senha').status_code == 404
    assert not PedidoRedefinicao.objects.exists()


# --- titularidade (R16) ---


@pytest.fixture
def candidata(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Candidata Admin')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    return pessoa


def test_titularidade_em_duas_etapas_so_a_segunda_tem_efeito_e_audita_a_justificativa(cliente_logado, titular, candidata, cenario):
    caminho = _casa(cenario) + 'titularidade'
    pagina = cliente_logado.get(caminho).content.decode()
    assert 'Etapa 1 de 2' in pagina
    assert 'Candidata Admin' in pagina
    assert titular.nome not in pagina.split('Novo titular')[1].split('</select>')[0]
    etapa_1 = {'etapa': '1', 'novo_titular': candidata.pk, 'justificativa': 'Troca de gestão.'}
    resposta = cliente_logado.post(caminho, etapa_1)
    assert resposta.status_code == 200
    assert 'Etapa 2 de 2' in resposta.content.decode()
    assert 'Empresa X' in resposta.content.decode()
    cenario.x.refresh_from_db()
    assert cenario.x.titular == titular  # a etapa 1 não muda nada
    assert _auditoria('titularidade_transferida') == []
    etapa_2 = {**etapa_1, 'etapa': '2', 'confirmacao': 'empresa x'}
    resposta = cliente_logado.post(caminho, etapa_2)  # nome digitado errado (caixa diferente)
    assert resposta.status_code == 400
    cenario.x.refresh_from_db()
    assert cenario.x.titular == titular
    resposta = cliente_logado.post(caminho, {**etapa_2, 'confirmacao': ' Empresa X '})
    assert resposta.status_code == 302
    assert resposta['Location'].endswith('?feito=titularidade')
    cenario.x.refresh_from_db()
    assert cenario.x.titular == candidata
    evento = _auditoria('titularidade_transferida')[0]
    assert evento.detalhes == {'de': titular.pk, 'para': candidata.pk, 'justificativa': 'Troca de gestão.'}


def test_etapa_2_sozinha_sem_justificativa_ou_com_candidato_invalido_nao_transfere(cliente_logado, titular, candidata, cenario, conceder_direto, fabrica_pessoa):
    caminho = _casa(cenario) + 'titularidade'
    curador = fabrica_pessoa('Curador')
    conceder_direto(curador, cenario.cargos_x['curador'], cenario.x)
    com_prazo = fabrica_pessoa('Admin com prazo')
    conceder_direto(com_prazo, cenario.cargos_x['administrador'], cenario.x, fim=timezone.now() + timedelta(days=30))
    for dados, texto in (
        ({'etapa': '2', 'novo_titular': candidata.pk, 'justificativa': '  ', 'confirmacao': 'Empresa X'}, 'Informe a justificativa'),
        ({'etapa': '2', 'novo_titular': curador.pk, 'justificativa': 'x', 'confirmacao': 'Empresa X'}, 'Escolha uma pessoa da lista'),
        ({'etapa': '2', 'novo_titular': com_prazo.pk, 'justificativa': 'x', 'confirmacao': 'Empresa X'}, 'Escolha uma pessoa da lista'),
        ({'etapa': '2', 'novo_titular': titular.pk, 'justificativa': 'x', 'confirmacao': 'Empresa X'}, 'Escolha uma pessoa da lista'),
        ({'etapa': '3', 'novo_titular': candidata.pk, 'justificativa': 'x'}, None),
    ):
        resposta = cliente_logado.post(caminho, dados)
        assert (dados, resposta.status_code) == (dados, 400)
        if texto:
            assert texto in resposta.content.decode()
    cenario.x.refresh_from_db()
    assert cenario.x.titular == titular


def test_plataforma_transfere(cliente_logado, conta, cenario, candidata, conceder_direto, fabrica_pessoa):
    titular_de_fato = fabrica_pessoa('Titular de fato')
    conceder_direto(titular_de_fato, cenario.cargos_x['administrador'], cenario.x)
    cenario.x.titular = titular_de_fato
    cenario.x.save(update_fields=['titular'])
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    caminho = _casa(cenario) + 'titularidade'
    assert cliente_logado.get(caminho).status_code == 200
    resposta = cliente_logado.post(caminho, {'etapa': '2', 'novo_titular': candidata.pk, 'justificativa': 'Decisão da plataforma.', 'confirmacao': 'Empresa X'})
    assert resposta.status_code == 302
    cenario.x.refresh_from_db()
    assert cenario.x.titular == candidata


# --- idioma e texto hostil (R31, R33; A20, A27) ---


def test_nenhuma_tela_de_pessoas_tem_texto_herdado_do_admin_em_ingles(cliente_logado, titular, candidata, alvo, cenario):
    pessoa, concessao = alvo
    telas = _telas(cenario, pessoa.pk, concessao.pk)
    for nome in ('pessoas', 'pessoas_convidar', 'pessoas_convites', 'pessoa_revogar', 'pessoa_redefinir_senha', 'titularidade'):
        resposta = cliente_logado.get(telas[nome])
        assert (nome, resposta.status_code) == (nome, 200)
        assert re.search(r'Select an option|object \(|foi adicionado', resposta.content.decode(), re.IGNORECASE) is None, nome


def test_nome_e_justificativa_com_html_saem_escapados_e_o_banco_guarda_o_digitado(cliente_logado, titular, candidata, cenario, conceder_direto, fabrica_pessoa):
    hostil = fabrica_pessoa(TRECHO_HTML)
    concessao = conceder_direto(hostil, cenario.cargos_x['usuario'], cenario.f1)
    for caminho in (f'pessoa/{hostil.pk}/revogar/{concessao.pk}', f'pessoa/{hostil.pk}/redefinir-senha'):
        html = cliente_logado.get(_casa(cenario) + caminho).content.decode()
        assert TRECHO_HTML not in html, caminho
        assert '&lt;script&gt;' in html, caminho
    assert Pessoa.objects.get(pk=hostil.pk).nome == TRECHO_HTML
    resposta = cliente_logado.post(_casa(cenario) + 'titularidade', {'etapa': '1', 'novo_titular': candidata.pk, 'justificativa': TRECHO_HTML})
    assert TRECHO_HTML not in resposta.content.decode()
    assert '&lt;script&gt;' in resposta.content.decode()
    cliente_logado.post(_casa(cenario) + 'titularidade', {'etapa': '2', 'novo_titular': candidata.pk, 'justificativa': TRECHO_HTML, 'confirmacao': cenario.x.nome})
    assert _auditoria('titularidade_transferida')[0].detalhes['justificativa'] == TRECHO_HTML


# --- convite por sub-área ---


def test_convidar_para_sub_area_grava_a_concessao_no_lugar_estreito_e_a_lista_mostra_a_trilha(cliente_logado, administradora, cenario, cpf_novo):
    resposta = cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf_novo(), escopo=f'sub-area-{cenario.t1.pk}'))
    assert resposta.status_code == 200
    concessao = Concessao.objects.get(pessoa__nome='Pessoa Convidada')
    assert (concessao.fazenda_id, concessao.sub_area_id) == (cenario.f1.pk, cenario.t1.pk)
    assert 'F1 › T1' in cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode()


def test_convite_de_cpf_existente_para_sub_area_aparece_com_a_trilha_nos_enviados(cliente_logado, administradora, cenario, cpf_novo):
    cpf = cpf_novo()
    Pessoa.objects.criar(nome='Ja Cadastrada', email='ja@exemplo.test', cpf=cpf)
    cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf, escopo=f'sub-area-{cenario.g1.pk}'))
    assert Convite.objects.get().sub_area_id == cenario.g1.pk
    assert 'F1 › G1' in cliente_logado.get(_casa(cenario) + 'pessoas/convites').content.decode()


def test_curador_de_sub_area_so_convida_dentro_dela(cliente_logado, conta, cenario, conceder_direto, cpf_novo):
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.g1)
    caminho = _casa(cenario) + 'pessoas/convidar'
    html = cliente_logado.get(caminho).content.decode()
    assert 'Empresa inteira' not in html
    assert 'Escolher uma sub-área' in html
    fazendas = cliente_logado.get(caminho + '/sub-area/').content.decode()
    assert f'/sub-area/{cenario.f1.pk}/' in fazendas
    assert f'/sub-area/{cenario.f2.pk}/' not in fazendas
    sub_areas = _sem_nonce(cliente_logado.get(caminho + f'/sub-area/{cenario.f1.pk}/').content.decode())
    assert 'G1' in sub_areas
    assert 'T1' in sub_areas
    assert 'G2' not in sub_areas
    assert cliente_logado.get(caminho + f'/sub-area/{cenario.f2.pk}/').status_code == 404  # fora do alcance dele: some, como no resto
    assert cliente_logado.post(caminho, _dados(cenario, cpf_novo(), nome='Dentro', escopo=f'sub-area-{cenario.t1.pk}')).status_code == 200
    for fora in (f'sub-area-{cenario.g2.pk}', f'fazenda-{cenario.f1.pk}', 'empresa'):
        resposta = cliente_logado.post(caminho, _dados(cenario, cpf_novo(), nome='Fora', escopo=fora))
        assert (fora, resposta.status_code) == (fora, 400)
    assert not Pessoa.objects.filter(nome='Fora').exists()


# --- escolher a sub-área do convite (duas etapas) ---


def test_escolher_sub_area_em_duas_etapas_leva_ao_formulario_com_o_lugar_escolhido(cliente_logado, administradora, cenario):
    base = _casa(cenario) + 'pessoas/convidar'
    etapa_1 = cliente_logado.get(base + '/sub-area/')
    assert etapa_1.status_code == 200
    assert f'/sub-area/{cenario.f1.pk}/' in etapa_1.content.decode()
    assert f'/sub-area/{cenario.fy.pk}/' not in etapa_1.content.decode()
    etapa_2 = cliente_logado.get(base + f'/sub-area/{cenario.f1.pk}/').content.decode()
    ordem = [etapa_2.index(nome) for nome in ('F1 › G1<', 'F1 › G2<', 'F1 › G1 › T1<')]
    assert ordem == sorted(ordem)  # por nível e nome, cada item com a trilha dos pais
    formulario_pronto = cliente_logado.get(base + f'?escopo=sub-area-{cenario.t1.pk}').content.decode()
    assert re.search(r'<option value="sub-area-%d" selected>F1 › G1 › T1</option>' % cenario.t1.pk, formulario_pronto)


def test_filtro_da_sub_area_mostra_a_trilha_e_filtra_pelo_texto(cliente_logado, administradora, cenario):
    caminho = _casa(cenario) + f'pessoas/convidar/sub-area/{cenario.f1.pk}/'
    html = _sem_nonce(cliente_logado.get(caminho + '?q=t1').content.decode())
    assert 'F1 › G1 › T1' in html
    assert 'G2' not in html
    assert 'Nenhuma sub-área com esse texto.' in cliente_logado.get(caminho + '?q=nada').content.decode()
    hostil = cliente_logado.get(caminho + '?q=' + TRECHO_HTML).content.decode()
    assert TRECHO_HTML not in hostil


def test_seletor_de_sub_area_pagina_e_guarda_o_filtro_nos_links(cliente_logado, administradora, cenario, monkeypatch):
    from projeto import pessoas_paginas
    from territorio.models import SubArea

    monkeypatch.setattr(pessoas_paginas, 'POR_PAGINA_DO_SELETOR', 2)
    for n in range(4):
        SubArea.objects.create(empresa=cenario.x, fazenda=cenario.f1, nivel=1, nome=f'Lote {n}')
    caminho = _casa(cenario) + f'pessoas/convidar/sub-area/{cenario.f1.pk}/'
    html = cliente_logado.get(caminho + '?q=lote').content.decode()
    assert 'Página 1 de 2' in html
    assert 'q=lote&amp;pagina=2' in html
    assert 'Lote 3' in cliente_logado.get(caminho + '?q=lote&pagina=2').content.decode()


def test_sub_area_pedida_que_a_pessoa_nao_alcanca_ou_e_de_outra_empresa_e_ignorada(cliente_logado, administradora, cenario, conceder_direto, fabrica_pessoa):
    from territorio.models import SubArea

    de_y = SubArea.objects.create(empresa=cenario.y, fazenda=cenario.fy, nivel=1, nome='Sub da Y')
    base = _casa(cenario) + 'pessoas/convidar'
    for chave in (f'sub-area-{de_y.pk}', 'sub-area-999999', 'sub-area-abc', 'sub-area-', 'empresa'):
        html = cliente_logado.get(base + f'?escopo={chave}').content.decode()
        assert (chave, 'Sub da Y' in html, '<option value="sub-area-' in html) == (chave, False, False)
    assert cliente_logado.get(_casa(cenario) + f'pessoas/convidar/sub-area/{cenario.fy.pk}/').status_code == 404


def test_tecnico_nao_abre_o_seletor_de_sub_area(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['tecnico'], cenario.x)
    base = _casa(cenario) + 'pessoas/convidar/sub-area/'
    assert cliente_logado.get(base).status_code == 403
    assert cliente_logado.get(base + f'{cenario.f1.pk}/').status_code == 403

# --- achados da revisão da PR #30 ---


def test_curador_de_sub_area_nao_ve_o_acesso_da_mesma_pessoa_em_outros_lugares(cliente_logado, conta, cenario, conceder_direto, fabrica_pessoa):
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.g1)
    pessoa = fabrica_pessoa('Pessoa com dois acessos')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.g1)  # dentro do alcance de quem olha
    conceder_direto(pessoa, cenario.cargos_x['tecnico'], cenario.g2, fim=timezone.now() + timedelta(days=30))  # sub-área irmã
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)  # empresa inteira
    html = _sem_nonce(cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode())
    assert 'Pessoa com dois acessos' in html
    assert 'Usuário · F1 › G1' in html
    for fora in ('Técnico', 'G2', 'Administrador · Empresa inteira'):
        assert fora not in html, fora


def test_plataforma_ve_todos_os_acessos_da_pessoa_na_empresa(cliente_logado, conta, cenario, conceder_direto, fabrica_pessoa):
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    pessoa = fabrica_pessoa('Pessoa com dois acessos')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.g1)
    conceder_direto(pessoa, cenario.cargos_x['tecnico'], cenario.g2)
    html = cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode()
    assert 'F1 › G1' in html
    assert 'F1 › G2' in html


def test_titularidade_de_empresa_arquivada_e_recusada_ate_para_a_plataforma(cliente_logado, conta, cenario, candidata, conceder_direto, fabrica_pessoa):
    from territorio.cadastro import arquivar, efeitos_do_arquivamento

    titular_de_fato = fabrica_pessoa('Titular de fato')
    conceder_direto(titular_de_fato, cenario.cargos_x['administrador'], cenario.x)
    cenario.x.titular = titular_de_fato
    cenario.x.save(update_fields=['titular'])
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    arquivar(conta.pessoa, cenario.x, efeitos_do_arquivamento(cenario.x))
    caminho = _casa(cenario) + 'titularidade'
    assert cliente_logado.get(caminho).status_code == 403
    dados = {'etapa': '2', 'novo_titular': candidata.pk, 'justificativa': 'Teste.', 'confirmacao': 'Empresa X'}
    assert cliente_logado.post(caminho, dados).status_code == 403
    cenario.x.refresh_from_db()
    assert cenario.x.titular == titular_de_fato


def test_email_acima_do_limite_do_banco_volta_ao_formulario_e_nao_cria_a_pessoa(cliente_logado, administradora, cenario, cpf_novo):
    longo = 'a' * 250 + '@exemplo.test'
    resposta = cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf_novo(), email=longo))
    assert resposta.status_code == 400
    assert 'até 254 caracteres' in resposta.content.decode()
    assert not Pessoa.objects.filter(nome='Pessoa Convidada').exists()


def test_fim_no_ultimo_dia_do_calendario_volta_ao_formulario_em_vez_de_estourar(cliente_logado, administradora, cenario, cpf_novo):
    resposta = cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf_novo(), fim='9999-12-31'))
    assert resposta.status_code == 400
    assert 'Use uma data válida.' in resposta.content.decode()
    assert not Pessoa.objects.filter(nome='Pessoa Convidada').exists()


def test_convites_enviados_tem_paginas_e_so_traz_os_da_empresa(cliente_logado, administradora, cenario, cpf_novo, monkeypatch):
    from projeto import pessoas_paginas

    monkeypatch.setattr(pessoas_paginas, 'ITENS_POR_PAGINA', 1)
    for _ in range(2):
        cpf = cpf_novo()
        Pessoa.objects.criar(nome='Ja Cadastrada', email='ja@exemplo.test', cpf=cpf)
        cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf))
    caminho = _casa(cenario) + 'pessoas/convites'
    primeira = cliente_logado.get(caminho).content.decode()
    assert 'Página 1 de 2' in primeira
    assert primeira.count('Reenviar o convite') == 1
    segunda = cliente_logado.get(caminho + '?pagina=2').content.decode()
    assert 'Página 2 de 2' in segunda
    assert segunda.count('Reenviar o convite') == 1


# --- terceiro lote de revisão da PR #30 ---


def test_acesso_futuro_aparece_na_lista_com_a_data_e_da_para_revogar_antes_de_comecar(cliente_logado, administradora, cenario, conceder_direto, fabrica_pessoa):
    pessoa = fabrica_pessoa('Pessoa com acesso futuro')
    concessao = conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1, inicio=timezone.now() + timedelta(days=10))
    revogar = _casa(cenario) + f'pessoa/{pessoa.pk}/revogar/{concessao.pk}'
    html = cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode()
    assert 'Pessoa com acesso futuro' in html
    assert 'começa em' in html
    assert revogar in html
    assert cliente_logado.post(revogar).status_code == 302
    concessao.refresh_from_db()
    assert concessao.revogada_em is not None


def test_acesso_revogado_ou_vencido_nao_aparece_como_acesso_da_pessoa(cliente_logado, administradora, cenario, conceder_direto, fabrica_pessoa):
    pessoa = fabrica_pessoa('Pessoa sem acesso vigente')
    vencida = conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1, inicio=timezone.now() - timedelta(days=9), fim=timezone.now() - timedelta(days=1))
    revogada = conceder_direto(pessoa, cenario.cargos_x['tecnico'], cenario.f2, revogada_em=timezone.now(), revogada_por=administradora)
    html = _sem_nonce(cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode())
    assert f'/revogar/{vencida.pk}' not in html
    assert f'/revogar/{revogada.pk}' not in html


def test_lista_mostra_o_ultimo_dia_de_acesso_e_nao_o_dia_seguinte(cliente_logado, administradora, cenario, cpf_novo):
    ultimo = timezone.localdate() + timedelta(days=5)
    cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf_novo(), fim=ultimo.isoformat()))
    html = cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode()
    assert f'até {ultimo:%d/%m/%Y}' in html
    assert f'até {ultimo + timedelta(days=1):%d/%m/%Y}' not in html


def test_curador_so_recebe_link_de_revogar_do_que_o_servico_aceitaria(cliente_logado, conta, cenario, conceder_direto, alvo, fabrica_pessoa):
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.f1)
    administrador_da_f1 = fabrica_pessoa('Admin da F1')
    de_admin = conceder_direto(administrador_da_f1, cenario.cargos_x['administrador'], cenario.f1)
    pessoa, concessao = alvo
    html = cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode()
    assert f'/pessoa/{pessoa.pk}/revogar/{concessao.pk}' in html
    assert f'/revogar/{de_admin.pk}' not in html


def test_confirmacao_de_redefinir_nao_aparece_a_cargo_personalizado_que_o_servico_recusaria(cliente_logado, conta, cenario, conceder_direto, alvo):
    personalizado = Cargo.objects.create(empresa=cenario.x, nome='Curador com redefinir', base='curador')
    for codigo in (*cenario.cargos_x['curador'].permissoes.values_list('codigo', flat=True), 'redefinir_senha'):
        CargoPermissao.objects.create(cargo=personalizado, permissao_id=codigo)
    conceder_direto(conta.pessoa, personalizado, cenario.x)
    pessoa, _ = alvo
    caminho = _casa(cenario) + f'pessoa/{pessoa.pk}/redefinir-senha'
    assert cliente_logado.get(caminho).status_code == 403
    assert cliente_logado.post(caminho).status_code == 403
    assert not PedidoRedefinicao.objects.exists()


def test_cargo_so_com_revogar_acesso_ganha_o_link_para_as_pessoas_na_empresa_e_na_fazenda(cliente_logado, conta, cenario, conceder_direto):
    personalizado = Cargo.objects.create(empresa=cenario.x, nome='So revoga', base='tecnico')
    for codigo in ('ver', 'revogar_acesso'):
        CargoPermissao.objects.create(cargo=personalizado, permissao_id=codigo)
    conceder_direto(conta.pessoa, personalizado, cenario.x)
    pessoas = _casa(cenario) + 'pessoas/'
    assert f'href="{pessoas}"' in cliente_logado.get(_casa(cenario)).content.decode()
    assert f'href="{pessoas}"' in cliente_logado.get(_casa(cenario) + f'fazenda/{cenario.f1.pk}/').content.decode()
    assert cliente_logado.get(pessoas).status_code == 200


def test_repetir_o_convite_de_cpf_novo_nao_cria_convite_nem_segunda_concessao(cliente_logado, administradora, cenario, cpf_novo):
    dados = _dados(cenario, cpf_novo())
    assert cliente_logado.post(_casa(cenario) + 'pessoas/convidar', dados).status_code == 200
    assert cliente_logado.post(_casa(cenario) + 'pessoas/convidar', dados).status_code == 200  # a resposta se perdeu e a pessoa tentou de novo
    pessoa = Pessoa.objects.get(nome='Pessoa Convidada')
    assert Concessao.objects.filter(pessoa=pessoa).count() == 1
    assert not Convite.objects.exists()


def test_seletor_de_sub_area_tem_o_mesmo_numero_de_consultas_com_20_ou_220_sub_areas(cliente_logado, administradora, cenario):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from territorio.models import SubArea

    caminho = _casa(cenario) + f'pessoas/convidar/sub-area/{cenario.f1.pk}/?q=lote'

    def consultas(corta_no_banco=False):
        with CaptureQueriesContext(connection) as capturadas:
            assert cliente_logado.get(caminho).status_code == 200
        if corta_no_banco:
            assert any(' LIMIT 50' in consulta['sql'] for consulta in capturadas.captured_queries)  # só a página sai do banco
        return len(capturadas)

    SubArea.objects.bulk_create([SubArea(empresa=cenario.x, fazenda=cenario.f1, nivel=1, nome=f'Lote {n}') for n in range(20)])
    poucas = consultas()
    SubArea.objects.bulk_create([SubArea(empresa=cenario.x, fazenda=cenario.f1, nivel=1, nome=f'Lote B{n}') for n in range(200)])
    assert consultas(corta_no_banco=True) == poucas
    pagina_2 = cliente_logado.get(caminho + '&pagina=2').content.decode()
    assert 'Página 2 de 5' in pagina_2


def test_trilha_do_seletor_nao_mostra_ancestral_fora_do_alcance(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.t1)  # só a talhão, filha da G1
    html = _sem_nonce(cliente_logado.get(_casa(cenario) + f'pessoas/convidar/sub-area/{cenario.f1.pk}/').content.decode())
    assert 'F1 › T1' in html
    assert 'G1' not in html


def test_administrador_de_outra_empresa_nao_ve_a_pessoa_pelo_acesso_dela_fora_do_alcance_nesta(cliente_logado, conta, cenario, conceder_direto, cpf_novo):
    conceder_direto(conta.pessoa, cenario.cargos_y['administrador'], cenario.y)  # alcança a Y inteira
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.g1)  # e só a G1 da X
    de_y = Pessoa.objects.criar('Pessoa da Y com acesso na G2', 'y@exemplo.test', cpf_novo(), empresa_origem=cenario.y)
    com_g2 = conceder_direto(de_y, cenario.cargos_x['usuario'], cenario.g2)
    html = _sem_nonce(cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode())
    assert 'Pessoa da Y com acesso na G2' not in html
    assert cliente_logado.get(_casa(cenario) + f'pessoa/{de_y.pk}/revogar/{com_g2.pk}').status_code == 404


def test_link_pessoas_aparece_para_quem_so_alcanca_uma_sub_area(cliente_logado, conta, cenario, conceder_direto):
    personalizado = Cargo.objects.create(empresa=cenario.x, nome='So revoga na sub-area', base='tecnico')
    for codigo in ('ver', 'revogar_acesso'):
        CargoPermissao.objects.create(cargo=personalizado, permissao_id=codigo)
    conceder_direto(conta.pessoa, personalizado, cenario.g1)
    pessoas = _casa(cenario) + 'pessoas/'
    assert f'href="{pessoas}"' in cliente_logado.get(_casa(cenario)).content.decode()
    assert f'href="{pessoas}"' in cliente_logado.get(_casa(cenario) + f'fazenda/{cenario.f1.pk}/').content.decode()
    assert cliente_logado.get(pessoas).status_code == 200


def test_link_pessoas_nao_aparece_na_fazenda_de_quem_so_alcanca_outra(cliente_logado, conta, cenario, conceder_direto):
    personalizado = Cargo.objects.create(empresa=cenario.x, nome='So revoga na F2', base='tecnico')
    for codigo in ('ver', 'revogar_acesso'):
        CargoPermissao.objects.create(cargo=personalizado, permissao_id=codigo)
    conceder_direto(conta.pessoa, personalizado, cenario.f2)
    pessoas = _casa(cenario) + 'pessoas/'
    assert f'href="{pessoas}"' in cliente_logado.get(_casa(cenario) + f'fazenda/{cenario.f2.pk}/').content.decode()
    assert cliente_logado.get(_casa(cenario) + f'fazenda/{cenario.f1.pk}/').status_code == 404


# --- conceder cargo (R19, A24) ---


def _conceder(cenario, pessoa):
    return _casa(cenario) + f'pessoa/{pessoa.pk}/conceder'


def test_conceder_mostra_o_formulario_e_o_historico_com_ativas_e_revogadas(cliente_logado, administradora, cenario, alvo):
    pessoa, ativa = alvo
    revogada = Concessao.objects.create(
        pessoa=pessoa, cargo=cenario.cargos_x['usuario'], empresa=cenario.x, fazenda=cenario.f2, concedida_por=administradora,
        revogada_em=timezone.now(), revogada_por=administradora,
    )
    html = _sem_nonce(cliente_logado.get(_conceder(cenario, pessoa)).content.decode())
    assert 'Conceder cargo a Alvo Tecnico' in html
    assert 'name="cargo"' in html
    assert 'name="escopo"' in html
    assert 'Técnico · F1 · ativa' in html
    assert 'Usuário · F2 · revogada em' in html
    assert html.index('Usuário · F2') < html.index('Técnico · F1')  # da mais nova à mais antiga
    assert revogada.pk > ativa.pk
    assert not re.search(r'object \(|Select an option', html)


def test_conceder_grava_a_concessao_audita_e_volta_a_lista(cliente_logado, administradora, cenario, alvo):
    pessoa, _ = alvo
    resposta = cliente_logado.post(_conceder(cenario, pessoa), {'cargo': cenario.cargos_x['curador'].pk, 'escopo': f'fazenda-{cenario.f2.pk}'})
    assert resposta.status_code == 302
    assert resposta['Location'].endswith('/pessoas/?feito=concedido')
    nova = Concessao.objects.get(pessoa=pessoa, cargo=cenario.cargos_x['curador'])
    assert nova.fazenda_id == cenario.f2.pk
    assert nova.concedida_por == administradora
    assert len(_auditoria('concessao_criada')) == 1
    assert 'Acesso concedido.' in _sem_nonce(cliente_logado.get(resposta['Location']).content.decode())


@pytest.mark.parametrize('mudanca, campo_do_erro, texto', [
    ({'cargo': ''}, 'campo_cargo', 'Escolha um cargo da lista.'),
    ({'escopo': 'fazenda-999999'}, 'campo_escopo', 'Escolha onde o acesso vale.'),
    ({'inicio': '2026-13-45'}, 'campo_inicio', 'Use uma data válida.'),
    ({'inicio': '2030-01-02', 'fim': '2030-01-01'}, 'campo_fim', 'O fim precisa ser depois do início.'),
])
def test_conceder_com_dado_invalido_volta_com_o_erro_uma_vez_so_e_nao_grava(cliente_logado, administradora, cenario, alvo, mudanca, campo_do_erro, texto):
    pessoa, _ = alvo
    dados = {'cargo': cenario.cargos_x['curador'].pk, 'escopo': f'fazenda-{cenario.f2.pk}', **mudanca}
    resposta = cliente_logado.post(_conceder(cenario, pessoa), dados)
    html = _sem_nonce(resposta.content.decode())
    assert resposta.status_code == 400
    assert html.count(texto) == 1
    assert f'id="{campo_do_erro}-descricao"' in html
    assert Concessao.objects.filter(pessoa=pessoa).count() == 1


def test_ninguem_concede_o_que_nao_tem_e_a_recusa_aparece_uma_vez(cliente_logado, conta, cenario, conceder_direto, alvo):
    """A24 / D043: Curador de F1 não concede Administrador, nem em lugar fora do alcance dele."""
    pessoa, _ = alvo
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.f1)
    # Curador de F1 só tem a própria fazenda no seletor; F2 não aparece e o valor forjado é recusado como lugar inexistente.
    forjado = cliente_logado.post(_conceder(cenario, pessoa), {'cargo': cenario.cargos_x['tecnico'].pk, 'escopo': f'fazenda-{cenario.f2.pk}'})
    assert forjado.status_code == 400
    acima = cliente_logado.post(_conceder(cenario, pessoa), {'cargo': cenario.cargos_x['administrador'].pk, 'escopo': f'fazenda-{cenario.f1.pk}'})
    assert acima.status_code == 403
    assert _sem_nonce(acima.content.decode()).count('Você não pode conceder este cargo neste lugar.') == 1
    assert Concessao.objects.filter(pessoa=pessoa).count() == 1


def test_conceder_cargo_de_outra_empresa_e_recusado_e_nao_grava(cliente_logado, administradora, cenario, alvo):
    pessoa, _ = alvo
    resposta = cliente_logado.post(_conceder(cenario, pessoa), {'cargo': cenario.cargos_y['tecnico'].pk, 'escopo': f'fazenda-{cenario.f2.pk}'})
    assert resposta.status_code == 400
    assert Concessao.objects.filter(pessoa=pessoa).count() == 1


def test_conceder_a_pessoa_de_outra_empresa_e_404(cliente_logado, administradora, cenario, fabrica_pessoa, conceder_direto):
    de_y = fabrica_pessoa('Pessoa da Y')
    conceder_direto(de_y, cenario.cargos_y['tecnico'], cenario.fy)
    assert cliente_logado.get(_conceder(cenario, de_y)).status_code == 404
    assert cliente_logado.post(_conceder(cenario, de_y), {'cargo': cenario.cargos_x['tecnico'].pk, 'escopo': 'empresa'}).status_code == 404
    assert not Concessao.objects.filter(pessoa=de_y, empresa=cenario.x).exists()


def test_lista_de_pessoas_oferece_conceder_so_a_quem_pode(cliente_logado, conta, cenario, conceder_direto, alvo):
    pessoa, _ = alvo
    da_conta = conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    assert f'pessoa/{pessoa.pk}/conceder' in cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode()
    da_conta.delete()
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.x)
    assert f'pessoa/{pessoa.pk}/conceder' in cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode()  # o Curador convida, então concede


# --- achados de revisão da PR #31 ---


def test_historico_mostra_as_datas_no_fuso_local_e_nao_em_utc(cliente_logado, administradora, cenario, alvo, conceder_direto):
    pessoa, _ = alvo
    # Último dia 01/01/2030: o fim gravado é a meia-noite local do dia 02, que em UTC já é 02/01 03:00.
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f2, fim=timezone.make_aware(datetime(2030, 1, 2)))
    html = _sem_nonce(cliente_logado.get(_conceder(cenario, pessoa)).content.decode())
    assert 'Usuário · F2 · até 01/01/2030 · ativa' in html


def test_conceder_so_a_pessoa_que_o_convidar_alcanca_mesmo_vista_por_revogar(cliente_logado, conta, cenario, conceder_direto, fabrica_pessoa):
    """Quem convida na F1 e só revoga na F2 vê a pessoa da F2 na lista, mas não pode conceder a ela (a API responde 404)."""
    revogador = Cargo.objects.create(empresa=cenario.x, nome='Revogador', base='tecnico')  # Curador convida sempre (D073): o cargo do teste não pode ser dele
    CargoPermissao.objects.bulk_create(CargoPermissao(cargo=revogador, permissao_id=c) for c in ('ver', 'revogar_acesso'))
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.f1)
    conceder_direto(conta.pessoa, revogador, cenario.f2)
    da_f2 = fabrica_pessoa('Pessoa da F2')
    conceder_direto(da_f2, cenario.cargos_x['tecnico'], cenario.f2)
    lista = cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode()
    assert 'Pessoa da F2' in lista
    assert f'pessoa/{da_f2.pk}/conceder' not in lista  # o link só aparece onde a tela abriria
    assert cliente_logado.get(_conceder(cenario, da_f2)).status_code == 404
    assert cliente_logado.post(_conceder(cenario, da_f2), {'cargo': cenario.cargos_x['tecnico'].pk, 'escopo': f'fazenda-{cenario.f1.pk}'}).status_code == 404
    assert Concessao.objects.filter(pessoa=da_f2).count() == 1


# --- conceder com sub-área e sem duplicar (003 Fase 4) ---


def test_conceder_duas_vezes_pela_tela_grava_uma_concessao_so(cliente_logado, administradora, cenario, alvo):
    pessoa, _ = alvo
    dados = {'cargo': cenario.cargos_x['curador'].pk, 'escopo': f'fazenda-{cenario.f2.pk}'}
    assert cliente_logado.post(_conceder(cenario, pessoa), dados).status_code == 302
    assert cliente_logado.post(_conceder(cenario, pessoa), dados).status_code == 302
    assert Concessao.objects.filter(pessoa=pessoa, cargo=cenario.cargos_x['curador']).count() == 1


def test_escolha_de_sub_area_volta_para_a_tela_de_conceder_e_concede_na_sub_area(cliente_logado, administradora, cenario, alvo):
    pessoa, _ = alvo
    base = _casa(cenario) + 'pessoas/convidar/sub-area/'
    fazendas = _sem_nonce(cliente_logado.get(f'{base}?pessoa={pessoa.pk}').content.decode())
    assert f'{base}{cenario.f1.pk}/?pessoa={pessoa.pk}' in fazendas
    sub_areas = _sem_nonce(cliente_logado.get(f'{base}{cenario.f1.pk}/?pessoa={pessoa.pk}').content.decode())
    assert f'{_conceder(cenario, pessoa)}?escopo=sub-area-{cenario.g1.pk}' in sub_areas
    assert f'name="pessoa" value="{pessoa.pk}"' in sub_areas  # o filtro não perde a pessoa
    tela = _sem_nonce(cliente_logado.get(f'{_conceder(cenario, pessoa)}?escopo=sub-area-{cenario.g1.pk}').content.decode())
    assert re.search(rf'<option value="sub-area-{cenario.g1.pk}" selected>', tela)
    resposta = cliente_logado.post(_conceder(cenario, pessoa), {'cargo': cenario.cargos_x['curador'].pk, 'escopo': f'sub-area-{cenario.g1.pk}'})
    assert resposta.status_code == 302
    assert Concessao.objects.filter(pessoa=pessoa, cargo=cenario.cargos_x['curador'], sub_area=cenario.g1).count() == 1


def test_escolha_de_sub_area_ignora_pessoa_fora_do_alcance_e_volta_ao_convite(cliente_logado, administradora, cenario, fabrica_pessoa, conceder_direto):
    de_y = fabrica_pessoa('Pessoa da Y')
    conceder_direto(de_y, cenario.cargos_y['tecnico'], cenario.fy)
    base = _casa(cenario) + 'pessoas/convidar/sub-area/'
    for pedida in (str(de_y.pk), '999999', 'abc'):
        html = _sem_nonce(cliente_logado.get(f'{base}{cenario.f1.pk}/?pessoa={pedida}').content.decode())
        assert f'{_casa(cenario)}pessoas/convidar?escopo=sub-area-{cenario.g1.pk}' in html
        assert '/conceder' not in html


def test_curador_so_da_sub_area_concede_nela_pela_tela(cliente_logado, conta, cenario, conceder_direto, alvo):
    pessoa, _ = alvo
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.g1)
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.t1)
    lista = cliente_logado.get(_casa(cenario) + 'pessoas/').content.decode()
    assert f'pessoa/{pessoa.pk}/conceder' in lista
    resposta = cliente_logado.post(_conceder(cenario, pessoa), {'cargo': cenario.cargos_x['tecnico'].pk, 'escopo': f'sub-area-{cenario.t1.pk}'})
    assert resposta.status_code == 302
    forjada = cliente_logado.post(_conceder(cenario, pessoa), {'cargo': cenario.cargos_x['tecnico'].pk, 'escopo': f'sub-area-{cenario.g2.pk}'})
    assert forjada.status_code == 400
