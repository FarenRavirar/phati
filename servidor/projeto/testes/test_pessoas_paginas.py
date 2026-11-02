"""Telas de pessoas (003 R13 a R17, R28, R33; A26): caso feliz, validação, acesso negado por URL direta e escape de HTML."""

import re
from datetime import timedelta
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
    assert 'Alvo Tecnico' in html and 'Técnico' in html and 'F1' in html
    assert 'Pessoa da Y' not in html
    assert 'Revogar' in html and 'Redefinir senha' in html
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
    assert 'Alvo Tecnico' in html and 'Usuario da F2' not in html
    assert 'Redefinir senha' not in html and 'Transferir a titularidade' not in html
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
    assert resposta.status_code == 200 and 'Alvo Tecnico' in html
    assert 'Convidar pessoa' not in html and 'Revogar' in html and 'Redefinir senha' in html
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
    assert 'Empresa Y' not in html and 'FY' not in html


def test_convidar_cpf_novo_cria_a_pessoa_e_a_senha_aparece_uma_vez_sem_cache_log_sessao_nem_auditoria(cliente_logado, administradora, cenario, cpf_novo, caplog, mailoutbox):
    caplog.set_level('DEBUG')
    resposta = cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf_novo()))
    html = resposta.content.decode()
    assert resposta.status_code == 200 and 'no-store' in resposta['Cache-Control']
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
    assert resposta.status_code == 200 and 'senha-temporaria' not in html and 'Ja Cadastrada' not in html
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
    assert Pessoa.objects.count() == antes and not Convite.objects.exists()


def test_cargo_de_outra_empresa_e_recusado_e_nada_e_criado(cliente_logado, administradora, cenario, cpf_novo):
    resposta = cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf_novo(), cargo=cenario.cargos_y['usuario'].pk))
    assert resposta.status_code == 400
    assert not Pessoa.objects.filter(nome='Pessoa Convidada').exists()


def test_periodo_com_fim_vale_ate_o_fim_do_dia(cliente_logado, administradora, cenario, cpf_novo):
    fim = (timezone.localdate() + timedelta(days=10)).isoformat()
    cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf_novo(), fim=fim))
    concessao = Concessao.objects.get(pessoa__nome='Pessoa Convidada')
    assert concessao.fim is not None and concessao.fim.astimezone(timezone.get_current_timezone()).date().isoformat() == (timezone.localdate() + timedelta(days=11)).isoformat()


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
    assert resposta.status_code == 403 and 'Você não pode conceder este cargo neste lugar.' in resposta.content.decode()
    assert Pessoa.objects.count() == antes
    # O Curador da F1 não oferece nem aceita a empresa inteira nem a F2.
    html = cliente_logado.get(caminho).content.decode()
    assert 'Empresa inteira' not in html and f'value="fazenda-{cenario.f2.pk}"' not in html
    resposta = cliente_logado.post(caminho, _dados(cenario, cpf_novo(), nome='Fora', escopo=f'fazenda-{cenario.f2.pk}'))
    assert resposta.status_code == 400 and not Pessoa.objects.filter(nome='Fora').exists()


# --- convites enviados (R13) ---


@pytest.fixture
def convite_enviado(cliente_logado, administradora, cenario, cpf_novo):
    cpf = cpf_novo()
    Pessoa.objects.criar(nome='Ja Cadastrada', email='ja@exemplo.test', cpf=cpf)
    cliente_logado.post(_casa(cenario) + 'pessoas/convidar', _dados(cenario, cpf))
    return Convite.objects.get()


def test_convites_enviados_lista_so_os_da_empresa_e_nao_mostra_a_pessoa(cliente_logado, convite_enviado, cenario):
    html = cliente_logado.get(_casa(cenario) + 'pessoas/convites').content.decode()
    assert 'Usuário' in html and 'F1' in html and 'Reenviar' in html and 'Cancelar' in html
    assert 'Ja Cadastrada' not in html


def test_cancelar_convite_marca_o_cancelamento_e_audita(cliente_logado, convite_enviado, cenario):
    caminho = _casa(cenario) + f'pessoas/convites/{convite_enviado.pk}/cancelar'
    assert cliente_logado.get(caminho)['Location'].endswith('/pessoas/convites')  # GET não cancela
    convite_enviado.refresh_from_db()
    assert convite_enviado.cancelado_em is None
    resposta = cliente_logado.post(caminho)
    assert resposta.status_code == 302 and resposta['Location'].endswith('?feito=cancelado')
    convite_enviado.refresh_from_db()
    assert convite_enviado.cancelado_em is not None
    assert len(_auditoria('convite_cancelado')) == 1
    assert 'Convite cancelado.' in cliente_logado.get(resposta['Location']).content.decode()
    assert cliente_logado.post(caminho).status_code == 400  # já respondido: a regra do serviço volta como erro


def test_reenviar_respeita_o_intervalo_e_depois_renova(cliente_logado, convite_enviado, cenario):
    caminho = _casa(cenario) + f'pessoas/convites/{convite_enviado.pk}/reenviar'
    resposta = cliente_logado.post(caminho)
    assert resposta.status_code == 400 and 'Aguarde antes de reenviar.' in resposta.content.decode()
    Convite.objects.filter(pk=convite_enviado.pk).update(enviado_em=timezone.now() - timedelta(minutes=5))
    resposta = cliente_logado.post(caminho)
    assert resposta.status_code == 302 and resposta['Location'].endswith('?feito=reenviado')
    convite_enviado.refresh_from_db()
    assert convite_enviado.envios == 2


def test_convite_de_outra_pessoa_e_404_e_nao_muda(cliente_logado, convite_enviado, cenario, conceder_direto, cpf_novo):
    cpf = cpf_novo()
    admin2 = Pessoa.objects.criar('Admin 2', 'admin2@exemplo.test', cpf)
    admin2.set_password('cavalo azul sobe o morro')
    admin2.save()
    conceder_direto(admin2, cenario.cargos_x['administrador'], cenario.x)
    outro = Client()
    assert outro.post('/entrar', {'cpf': cpf, 'senha': 'cavalo azul sobe o morro'}).status_code == 302
    for acao in ('cancelar', 'reenviar'):
        assert outro.post(_casa(cenario) + f'pessoas/convites/{convite_enviado.pk}/{acao}').status_code == 404
    convite_enviado.refresh_from_db()
    assert convite_enviado.cancelado_em is None and convite_enviado.envios == 1


# --- revogar (R14) ---


def test_confirmacao_de_revogar_diz_que_a_linha_fica_e_revogar_grava_sem_apagar(cliente_logado, administradora, cenario, alvo):
    pessoa, concessao = alvo
    caminho = _casa(cenario) + f'pessoa/{pessoa.pk}/revogar/{concessao.pk}'
    pagina = cliente_logado.get(caminho)
    assert pagina.status_code == 200
    texto = pagina.content.decode()
    assert 'não é apagada' in texto and 'Alvo Tecnico' in texto
    concessao.refresh_from_db()
    assert concessao.revogada_em is None  # GET não revoga
    resposta = cliente_logado.post(caminho)
    assert resposta.status_code == 302 and resposta['Location'].endswith('?feito=revogado')
    concessao.refresh_from_db()
    assert concessao.revogada_em is not None and concessao.revogada_por == administradora
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
    assert resposta.status_code == 400 and 'O Administrador titular só sai por transferência de titularidade.' in resposta.content.decode()
    de_outro.refresh_from_db()
    assert de_outro.revogada_em is None


def test_curador_revoga_abaixo_dele_e_nao_revoga_administrador(cliente_logado, conta, cenario, conceder_direto, alvo, fabrica_pessoa):
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.f1)
    admin_da_f1 = fabrica_pessoa('Admin da F1')
    de_admin = conceder_direto(admin_da_f1, cenario.cargos_x['administrador'], cenario.f1)
    pessoa, concessao = alvo
    assert cliente_logado.post(_casa(cenario) + f'pessoa/{admin_da_f1.pk}/revogar/{de_admin.pk}').status_code == 403
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
    assert confirmacao.status_code == 200 and 'Alvo Tecnico' in confirmacao.content.decode()
    assert not PedidoRedefinicao.objects.exists()  # GET não pede
    resposta = cliente_logado.post(caminho)
    html = resposta.content.decode()
    assert resposta.status_code == 200 and 'no-store' in resposta['Cache-Control']
    pedido = PedidoRedefinicao.objects.get()
    assert (pedido.pessoa, pedido.solicitado_por) == (pessoa, administradora)
    assert len(mailoutbox) == 1 and mailoutbox[0].to == [pessoa.email]
    achado = re.search(r'segredo=([\w-]+)', mailoutbox[0].body)
    assert achado is not None
    segredo = achado.group(1)
    assert segredo not in html and segredo not in caplog.text and segredo not in str(dict(cliente_logado.session))
    assert all(segredo not in str(evento.detalhes) for evento in EventoAuditoria.objects.all())
    assert 'senha temporária' not in html.lower() and 'senha-temporaria' not in html
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
    assert 'Etapa 1 de 2' in pagina and 'Candidata Admin' in pagina and titular.nome not in pagina.split('Novo titular')[1].split('</select>')[0]
    etapa_1 = {'etapa': '1', 'novo_titular': candidata.pk, 'justificativa': 'Troca de gestão.'}
    resposta = cliente_logado.post(caminho, etapa_1)
    assert resposta.status_code == 200 and 'Etapa 2 de 2' in resposta.content.decode() and 'Empresa X' in resposta.content.decode()
    cenario.x.refresh_from_db()
    assert cenario.x.titular == titular  # a etapa 1 não muda nada
    assert _auditoria('titularidade_transferida') == []
    etapa_2 = {**etapa_1, 'etapa': '2', 'confirmacao': 'empresa x'}
    resposta = cliente_logado.post(caminho, etapa_2)  # nome digitado errado (caixa diferente)
    assert resposta.status_code == 400
    cenario.x.refresh_from_db()
    assert cenario.x.titular == titular
    resposta = cliente_logado.post(caminho, {**etapa_2, 'confirmacao': ' Empresa X '})
    assert resposta.status_code == 302 and resposta['Location'].endswith('?feito=titularidade')
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
        assert TRECHO_HTML not in html and '&lt;script&gt;' in html, caminho
    assert Pessoa.objects.get(pk=hostil.pk).nome == TRECHO_HTML
    resposta = cliente_logado.post(_casa(cenario) + 'titularidade', {'etapa': '1', 'novo_titular': candidata.pk, 'justificativa': TRECHO_HTML})
    assert TRECHO_HTML not in resposta.content.decode() and '&lt;script&gt;' in resposta.content.decode()
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
    assert 'Empresa inteira' not in html and 'Escolher uma sub-área' in html
    fazendas = cliente_logado.get(caminho + '/sub-area/').content.decode()
    assert f'/sub-area/{cenario.f1.pk}/' in fazendas and f'/sub-area/{cenario.f2.pk}/' not in fazendas
    sub_areas = _sem_nonce(cliente_logado.get(caminho + f'/sub-area/{cenario.f1.pk}/').content.decode())
    assert 'G1' in sub_areas and 'T1' in sub_areas and 'G2' not in sub_areas
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
    assert etapa_1.status_code == 200 and f'/sub-area/{cenario.f1.pk}/' in etapa_1.content.decode()
    assert f'/sub-area/{cenario.fy.pk}/' not in etapa_1.content.decode()
    etapa_2 = cliente_logado.get(base + f'/sub-area/{cenario.f1.pk}/').content.decode()
    ordem = [etapa_2.index(nome) for nome in ('G1', 'T1', 'G2')]
    assert ordem == sorted(ordem)  # pai antes do filho, na ordem da árvore
    assert 'nivel-1' in etapa_2 and 'nivel-2' in etapa_2
    formulario_pronto = cliente_logado.get(base + f'?escopo=sub-area-{cenario.t1.pk}').content.decode()
    assert re.search(r'<option value="sub-area-%d" selected>F1 › G1 › T1</option>' % cenario.t1.pk, formulario_pronto)


def test_filtro_da_sub_area_mostra_a_trilha_e_filtra_pelo_texto(cliente_logado, administradora, cenario):
    caminho = _casa(cenario) + f'pessoas/convidar/sub-area/{cenario.f1.pk}/'
    html = _sem_nonce(cliente_logado.get(caminho + '?q=t1').content.decode())
    assert 'F1 › G1 › T1' in html and 'G2' not in html
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
    assert 'Página 1 de 2' in html and 'q=lote&amp;pagina=2' in html
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