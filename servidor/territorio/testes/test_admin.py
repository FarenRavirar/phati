"""Painel territorial (T5.2): criação só pelos serviços de `cadastro`, listas só do escopo da pessoa."""

import pytest
from django.contrib.messages import get_messages

from comum.models import EventoAuditoria
from territorio.models import Empresa, Fazenda, SubArea


def _com(fabrica_pessoa, conceder_direto, cargo, escopo, nome='Pessoa'):
    pessoa = fabrica_pessoa(nome)
    conceder_direto(pessoa, cargo, escopo)
    return pessoa


def _textos(resposta):
    return [str(mensagem) for mensagem in get_messages(resposta.wsgi_request)]


def test_plataforma_cria_empresa_pelo_painel_e_a_senha_temporaria_aparece_uma_vez(plataforma, entrar_no_painel, cpf_novo):
    cliente = entrar_no_painel(plataforma)
    corpo = {'nome': 'Empresa Nova', 'nome_administrador': 'Ana', 'email_administrador': 'ana@exemplo.test', 'cpf_administrador': cpf_novo()}
    resposta = cliente.post('/painel/territorio/empresa/add/', corpo)
    assert resposta.status_code == 302
    empresa = Empresa.objects.get(nome='Empresa Nova')
    assert empresa.titular_id is not None
    assert EventoAuditoria.objects.filter(acao='empresa_criada', alvo_id=empresa.pk).exists()
    assert any('Senha temporária' in texto for texto in _textos(cliente.get('/painel/')))
    assert not any('Senha temporária' in texto for texto in _textos(cliente.get('/painel/')))


def test_administrador_de_empresa_nao_cria_empresa_nem_ve_o_formulario(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel, cpf_novo):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    cliente = entrar_no_painel(admin)
    assert cliente.get('/painel/territorio/empresa/add/').status_code == 403
    corpo = {'nome': 'Intrusa', 'nome_administrador': 'Ivo', 'email_administrador': 'ivo@exemplo.test', 'cpf_administrador': cpf_novo()}
    assert cliente.post('/painel/territorio/empresa/add/', corpo).status_code == 403
    assert not Empresa.objects.filter(nome='Intrusa').exists()


def test_administrador_cria_fazenda_na_propria_empresa_e_e_negado_na_alheia(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    cliente = entrar_no_painel(_com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x))
    assert cliente.post('/painel/territorio/fazenda/add/', {'empresa': cenario.x.pk, 'nome': 'Nova'}).status_code == 302
    assert Fazenda.objects.filter(empresa=cenario.x, nome='Nova').exists()
    # Dono do banco enxerga a empresa Y no formulário: quem barra é o serviço (`pode()`), com 403.
    assert cliente.post('/painel/territorio/fazenda/add/', {'empresa': cenario.y.pk, 'nome': 'Invasora'}).status_code == 403
    assert not Fazenda.objects.filter(nome='Invasora').exists()


def test_curador_ve_so_a_fazenda_dele_e_nao_cria(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    cliente = entrar_no_painel(_com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f1))
    pagina = cliente.get('/painel/territorio/fazenda/').content.decode()
    assert 'F1' in pagina
    assert 'FY' not in pagina and '>F2<' not in pagina
    assert cliente.get('/painel/territorio/fazenda/add/').status_code == 403
    assert cliente.post('/painel/territorio/fazenda/add/', {'empresa': cenario.x.pk, 'nome': 'Nova'}).status_code == 403
    assert not Fazenda.objects.filter(nome='Nova').exists()


def test_administrador_de_y_nao_ve_fazenda_de_x(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    cliente = entrar_no_painel(_com(fabrica_pessoa, conceder_direto, cenario.cargos_y['administrador'], cenario.y))
    pagina = cliente.get('/painel/territorio/fazenda/').content.decode()
    assert 'FY' in pagina
    assert '>F1<' not in pagina and '>F2<' not in pagina


def test_sub_area_filha_pelo_painel_e_pai_de_outra_fazenda_vira_mensagem(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    cliente = entrar_no_painel(_com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x))
    ok = cliente.post('/painel/territorio/subarea/add/', {'fazenda': cenario.f1.pk, 'pai': cenario.g1.pk, 'nome': 'Nova'})
    assert ok.status_code == 302
    assert SubArea.objects.get(nome='Nova').nivel == 2
    torta = cliente.post('/painel/territorio/subarea/add/', {'fazenda': cenario.f2.pk, 'pai': cenario.g1.pk, 'nome': 'Torta'}, follow=True)
    assert any('outra fazenda' in texto for texto in _textos(torta))
    assert not SubArea.objects.filter(nome='Torta').exists()


@pytest.mark.parametrize('rota', ['empresa', 'fazenda', 'subarea'])
def test_nenhuma_tela_territorial_edita_ou_apaga_linha_direto(cenario, plataforma, entrar_no_painel, rota):
    cliente = entrar_no_painel(plataforma)
    alvo = {'empresa': cenario.x, 'fazenda': cenario.f1, 'subarea': cenario.g1}[rota]
    assert cliente.post(f'/painel/territorio/{rota}/{alvo.pk}/change/', {'nome': 'Trocado'}).status_code in (403, 302)
    assert cliente.post(f'/painel/territorio/{rota}/{alvo.pk}/delete/', {'post': 'yes'}).status_code == 403
    alvo.refresh_from_db()
    assert alvo.nome != 'Trocado'
