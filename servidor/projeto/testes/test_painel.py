"""Painel (T5.2): quem entra, a sessão do R15, a RLS por requisição e o que o admin do Django não pode fazer."""

import pytest
from django.test import Client

from identidade import cpf as modulo_cpf
from identidade import senha


def _com(fabrica_pessoa, conceder_direto, cargo, escopo, nome='Pessoa'):
    pessoa = fabrica_pessoa(nome)
    conceder_direto(pessoa, cargo, escopo)
    return pessoa


def test_anonimo_vai_para_a_entrada_e_a_tela_de_entrada_abre(db):
    cliente = Client()
    assert cliente.get('/painel/').status_code == 302
    assert cliente.get('/painel/territorio/fazenda/').status_code == 302
    tela = cliente.get('/painel/login/')
    assert (tela.status_code, 'CPF' in tela.content.decode()) == (200, True)


def test_administrador_entra_pelo_cpf_e_abre_o_painel(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    cliente = entrar_no_painel(admin)
    pagina = cliente.get('/painel/')
    assert pagina.status_code == 200
    assert admin.cpf_busca not in pagina.content.decode()  # o nome aparece no cabeçalho, nunca o índice cego do CPF
    assert {'entrada_em', 'ultima_atividade'} <= set(cliente.session.keys())


@pytest.mark.parametrize('base', ['tecnico', 'usuario'])
def test_tecnico_e_usuario_nao_abrem_nenhuma_tela(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel, base):
    cliente = entrar_no_painel(_com(fabrica_pessoa, conceder_direto, cenario.cargos_x[base], cenario.f1))
    for rota in ('/painel/', '/painel/territorio/fazenda/', '/painel/permissao/concessao/', '/painel/identidade/pessoa/',
                 '/painel/permissao/cargo/', '/painel/territorio/fazenda/add/'):
        assert cliente.get(rota).status_code == 302, rota


def test_pessoa_sem_acesso_nao_abre_o_painel(cenario, fabrica_pessoa, entrar_no_painel):
    assert entrar_no_painel(fabrica_pessoa('Sem acesso')).get('/painel/').status_code == 302


def test_senha_errada_e_senha_temporaria_nao_entram(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    texto = senha.emitir_senha_temporaria(admin)  # deve_trocar_senha: a troca é da API
    cliente = Client()
    cpf = modulo_cpf.decifrar(admin.cpf_cifrado)
    assert cliente.post('/painel/login/', {'username': cpf, 'password': 'errada'}).status_code == 200
    assert cliente.post('/painel/login/', {'username': cpf, 'password': texto}).status_code == 200
    assert cliente.get('/painel/').status_code == 302


def test_sessao_ociosa_ou_velha_demais_perde_o_painel(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel, settings):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    cliente = entrar_no_painel(admin)
    sessao = cliente.session
    sessao['ultima_atividade'] -= settings.SESSAO_OCIOSIDADE_SEGUNDOS + 1
    sessao.save()
    assert cliente.get('/painel/').status_code == 302
    assert cliente.get('/painel/').status_code == 302  # sessão esvaziada, não só ignorada


def test_revogar_o_acesso_fecha_o_painel_na_requisicao_seguinte(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    from django.utils import timezone

    admin = fabrica_pessoa('Admin')
    concessao = conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    cliente = entrar_no_painel(admin)
    assert cliente.get('/painel/').status_code == 200
    concessao.revogada_em, concessao.revogada_por = timezone.now(), admin
    concessao.save(update_fields=['revogada_em', 'revogada_por'])
    assert cliente.get('/painel/').status_code == 302


def test_troca_de_senha_do_admin_do_django_esta_fechada(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    cliente = entrar_no_painel(_com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x))
    assert cliente.get('/painel/password_change/').status_code == 403
    assert cliente.post('/painel/password_change/', {}).status_code == 403


def test_acao_em_massa_de_apagar_nao_existe(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    from territorio.models import Fazenda

    cliente = entrar_no_painel(_com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x))
    resposta = cliente.post(
        '/painel/territorio/fazenda/', {'action': 'delete_selected', '_selected_action': [cenario.f1.pk], 'post': 'yes'}
    )
    assert Fazenda.objects.filter(pk=cenario.f1.pk).exists()
    assert 'delete_selected' not in resposta.content.decode().split('name="action"')[-1][:2000]
