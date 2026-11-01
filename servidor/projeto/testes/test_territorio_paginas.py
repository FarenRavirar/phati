"""Telas de gestão do território (003 R9 a R12, R28, R33; A6, A27): caso feliz, validação, acesso negado e escape de HTML."""

from datetime import timedelta

import pytest
from django.test import Client

from comum.models import EventoAuditoria
from permissao.models import Convite
from territorio.cadastro import arquivar
from territorio.models import Empresa, Fazenda, NivelDivisao, SubArea
from territorio.niveis import nome_do_nivel

SCRIPT = '<script>alert(1)</script>'


def _casa(cenario):
    return f'/empresa/{cenario.x.pk}/'


def _fazenda(cenario, fazenda=None):
    return f'/empresa/{cenario.x.pk}/fazenda/{(fazenda or cenario.f1).pk}/'


def _sub_area(cenario, sub_area=None):
    return f'{_fazenda(cenario)}sub-area/{(sub_area or cenario.g1).pk}/'


@pytest.fixture
def administradora(conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    return conta.pessoa


# Telas e a ação que cada uma exige: o mesmo laço prova o negado de todas por URL direta (R12).
def _telas(cenario):
    return {
        'empresa_editar': _casa(cenario) + 'editar',
        'empresa_niveis': _casa(cenario) + 'niveis',
        'empresa_arquivar': _casa(cenario) + 'arquivar',
        'fazenda_nova': _casa(cenario) + 'fazenda/nova',
        'fazenda_editar': _fazenda(cenario) + 'editar',
        'fazenda_arquivar': _fazenda(cenario) + 'arquivar',
        'sub_area_nova': _fazenda(cenario) + 'sub-area/nova',
        'sub_area_editar': _sub_area(cenario) + 'editar',
        'sub_area_arquivar': _sub_area(cenario) + 'arquivar',
    }


def test_deslogado_e_levado_a_entrada_em_toda_tela_de_gestao(cenario):
    cliente = Client()
    for caminho in (*_telas(cenario).values(), '/empresas/nova', '/arquivadas/'):
        resposta = cliente.get(caminho)
        assert (caminho, resposta.status_code, resposta['Location'].startswith('/entrar')) == (caminho, 302, True)
        if caminho != '/arquivadas/':  # só consulta: o método vem antes da sessão
            assert cliente.post(caminho).status_code == 302


def test_pessoa_sem_alcance_ou_de_outra_empresa_recebe_404_em_toda_tela(cliente_logado, conta, cenario, conceder_direto):
    telas = _telas(cenario)
    for caminho in telas.values():
        assert (caminho, cliente_logado.get(caminho).status_code) == (caminho, 404)
    conceder_direto(conta.pessoa, cenario.cargos_y['administrador'], cenario.y)
    for caminho in telas.values():
        assert (caminho, cliente_logado.get(caminho).status_code) == (caminho, 404)
        assert (caminho, cliente_logado.post(caminho, {'nome': 'Invasora'}).status_code) == (caminho, 404)
    assert Fazenda.objects.get(pk=cenario.f1.pk).nome == 'F1'
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is None


def test_curador_tecnico_e_usuario_com_alcance_recebem_403_em_toda_tela(cliente_logado, conta, cenario, conceder_direto):
    for base in ('curador', 'tecnico', 'usuario'):
        concessao = conceder_direto(conta.pessoa, cenario.cargos_x[base], cenario.x)
        for nome, caminho in _telas(cenario).items():
            assert (base, nome, cliente_logado.get(caminho).status_code) == (base, nome, 403)
            assert (base, nome, cliente_logado.post(caminho, {'nome': 'Invasora'}).status_code) == (base, nome, 403)
        concessao.delete()
    assert cliente_logado.get('/empresas/nova').status_code == 403
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is None


def test_administrador_de_empresa_nao_cria_empresa(cliente_logado, administradora):
    assert cliente_logado.get('/empresas/nova').status_code == 403
    assert cliente_logado.post('/empresas/nova', {'nome': 'Intrusa'}).status_code == 403
    assert not Empresa.objects.filter(nome='Intrusa').exists()


def test_plataforma_cria_empresa_e_a_senha_temporaria_aparece_uma_vez_sem_cache(cliente_logado, conta, cpf_novo):
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    campos = {'nome': 'Empresa Nova', 'nome_administrador': 'Ana', 'email_administrador': 'ana@exemplo.test', 'cpf_administrador': cpf_novo()}
    resposta = cliente_logado.post('/empresas/nova', campos)
    assert resposta.status_code == 200
    assert 'no-store' in resposta['Cache-Control']
    empresa = Empresa.objects.get(nome='Empresa Nova')
    assert b'Senha tempor' in resposta.content
    assert dict(NivelDivisao.objects.filter(empresa=empresa).values_list('nivel', 'nome')) == {1: 'Gleba', 2: 'Talhão'}
    # Recarregar a página não repete a senha: é outra tela, sem a senha.
    assert b'Senha tempor' not in cliente_logado.get(f'/empresa/{empresa.pk}/').content


def test_criar_empresa_com_dado_invalido_volta_ao_formulario_com_o_erro(cliente_logado, conta, cpf_novo):
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    resposta = cliente_logado.post('/empresas/nova', {'nome': '  ', 'nome_administrador': 'Ana', 'email_administrador': 'ana@exemplo.test', 'cpf_administrador': cpf_novo()})
    assert resposta.status_code == 400
    assert 'Informe um nome de 1 a 200 caracteres.' in resposta.content.decode()
    assert not Empresa.objects.filter(nome='').exists()


def test_administrador_cadastra_fazenda_e_cai_na_pagina_dela(cliente_logado, administradora, cenario):
    assert cliente_logado.get(_casa(cenario) + 'fazenda/nova').status_code == 200
    resposta = cliente_logado.post(_casa(cenario) + 'fazenda/nova', {'nome': 'Fazenda Nova'})
    nova = Fazenda.objects.get(nome='Fazenda Nova')
    assert (resposta.status_code, resposta['Location']) == (302, f'/empresa/{cenario.x.pk}/fazenda/{nova.pk}/')


def test_nome_vazio_ou_so_espacos_volta_com_400_e_nada_grava(cliente_logado, administradora, cenario):
    for nome in ('', '   '):
        resposta = cliente_logado.post(_casa(cenario) + 'fazenda/nova', {'nome': nome})
        assert resposta.status_code == 400
        assert 'Informe um nome' in resposta.content.decode()
    assert Fazenda.objects.filter(empresa=cenario.x).count() == 2


def test_nome_com_script_e_escapado_na_tela_e_na_resposta_de_erro(cliente_logado, administradora, cenario):
    cliente_logado.post(_casa(cenario) + 'fazenda/nova', {'nome': SCRIPT})
    html = cliente_logado.get(_casa(cenario)).content.decode()
    assert SCRIPT not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    # No formulário que volta com o valor digitado (erro de outro campo), o texto também sai escapado.
    resposta = cliente_logado.post(_casa(cenario) + 'niveis', {'nivel_1': SCRIPT, 'nivel_2': 'x' * 101})
    assert resposta.status_code == 400
    assert SCRIPT not in resposta.content.decode()


def test_renomear_fazenda_grava_audita_e_volta_a_pagina(cliente_logado, administradora, cenario):
    pagina = cliente_logado.get(_fazenda(cenario) + 'editar')
    assert pagina.status_code == 200 and 'value="F1"' in pagina.content.decode()
    resposta = cliente_logado.post(_fazenda(cenario) + 'editar', {'nome': 'F1 Nova'})
    assert (resposta.status_code, resposta['Location']) == (302, _fazenda(cenario))
    assert Fazenda.objects.get(pk=cenario.f1.pk).nome == 'F1 Nova'
    assert EventoAuditoria.objects.filter(acao='fazenda_renomeada', detalhes={'nome_antigo': 'F1', 'nome_novo': 'F1 Nova'}).exists()


def test_renomear_empresa_e_sub_area(cliente_logado, administradora, cenario):
    assert cliente_logado.post(_casa(cenario) + 'editar', {'nome': 'X Nova'}).status_code == 302
    assert cliente_logado.post(_sub_area(cenario) + 'editar', {'nome': 'G1 Nova'}).status_code == 302
    assert Empresa.objects.get(pk=cenario.x.pk).nome == 'X Nova'
    assert SubArea.objects.get(pk=cenario.g1.pk).nome == 'G1 Nova'


def test_renomear_com_nome_vazio_volta_com_400(cliente_logado, administradora, cenario):
    resposta = cliente_logado.post(_fazenda(cenario) + 'editar', {'nome': ' '})
    assert resposta.status_code == 400
    assert Fazenda.objects.get(pk=cenario.f1.pk).nome == 'F1'


def test_sub_area_nova_mostra_o_nome_do_nivel_e_grava_a_filha(cliente_logado, administradora, cenario):
    NivelDivisao.objects.create(empresa=cenario.x, nivel=1, nome='Gleba')
    NivelDivisao.objects.create(empresa=cenario.x, nivel=2, nome='Talhão')
    pagina = cliente_logado.get(_fazenda(cenario, cenario.f2) + 'sub-area/nova')
    assert 'Gleba' in pagina.content.decode()
    assert cliente_logado.post(_fazenda(cenario, cenario.f2) + 'sub-area/nova', {'nome': 'Gleba Norte'}).status_code == 302
    raiz = SubArea.objects.get(nome='Gleba Norte')
    assert raiz.nivel == 1
    filha = cliente_logado.get(_fazenda(cenario, cenario.f2) + f'sub-area/nova?pai={raiz.pk}')
    assert 'Talhão' in filha.content.decode() and f'name="pai" value="{raiz.pk}"' in filha.content.decode()
    assert cliente_logado.post(_fazenda(cenario, cenario.f2) + 'sub-area/nova', {'nome': 'Talhão 1', 'pai': raiz.pk}).status_code == 302
    assert SubArea.objects.get(nome='Talhão 1').nivel == 2


def test_sub_area_nova_com_pai_de_outra_fazenda_ou_invalido_da_404(cliente_logado, administradora, cenario):
    caminho = _fazenda(cenario, cenario.f2) + 'sub-area/nova'
    assert cliente_logado.get(caminho + f'?pai={cenario.g1.pk}').status_code == 404  # G1 é da F1
    assert cliente_logado.get(caminho + '?pai=abc').status_code == 404


def test_niveis_da_empresa_grava_os_nomes_e_muda_o_que_a_criacao_mostra(cliente_logado, administradora, cenario):
    assert cliente_logado.get(_casa(cenario) + 'niveis').status_code == 200
    resposta = cliente_logado.post(_casa(cenario) + 'niveis', {'nivel_1': 'Quadra', 'nivel_2': '', 'nivel_3': ''})
    assert resposta.status_code == 302
    assert nome_do_nivel(cenario.x, 1) == 'Quadra'
    assert nome_do_nivel(cenario.x, 2) == 'Nível 2'
    assert 'Quadra' in cliente_logado.get(_fazenda(cenario, cenario.f2) + 'sub-area/nova').content.decode()


def test_arquivar_pede_confirmacao_que_diz_o_que_atinge_e_so_o_post_arquiva(cliente_logado, administradora, cenario, fabrica_pessoa):
    from django.utils import timezone

    convidada = fabrica_pessoa('Convidada')
    Convite.objects.create(
        pessoa=convidada, convidado_por=convidada, cargo=cenario.cargos_x['usuario'], empresa=cenario.x, fazenda=cenario.f1,
        empresa_nome='Empresa X', cargo_nome='Usuário', expira_em=timezone.now() + timedelta(days=2),
    )
    pagina = cliente_logado.get(_fazenda(cenario) + 'arquivar').content.decode()
    assert '3 sub-áreas arquivadas junto.' in pagina
    assert '1 convite pendente cancelado' in pagina
    assert 'Nada é apagado.' in pagina
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is None  # o GET não arquiva
    resposta = cliente_logado.post(_fazenda(cenario) + 'arquivar')
    assert (resposta.status_code, resposta['Location']) == (302, _fazenda(cenario))
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is not None
    assert Convite.objects.get(pessoa=convidada).cancelado_em is not None


def test_fazenda_arquivada_segue_consultavel_sai_do_seletor_e_nega_escrita(cliente_logado, administradora, cenario):
    arquivar(administradora, cenario.f1)
    assert cliente_logado.get(_fazenda(cenario)).status_code == 200
    seletor = cliente_logado.get('/empresas/').content.decode()
    assert f'/fazenda/{cenario.f1.pk}/' not in seletor
    for caminho in ('editar', 'arquivar', 'sub-area/nova'):
        assert (caminho, cliente_logado.get(_fazenda(cenario) + caminho).status_code) == (caminho, 403)
        assert (caminho, cliente_logado.post(_fazenda(cenario) + caminho, {'nome': 'Tarde'}).status_code) == (caminho, 403)
    assert Fazenda.objects.get(pk=cenario.f1.pk).nome == 'F1'


def test_secao_arquivadas_lista_e_desarquiva_pela_confirmacao(cliente_logado, administradora, cenario):
    arquivar(administradora, cenario.f1)
    pagina = cliente_logado.get('/arquivadas/').content.decode()
    assert 'F1' in pagina and f'{_fazenda(cenario)}desarquivar' in pagina
    assert cliente_logado.get(_fazenda(cenario) + 'desarquivar').status_code == 200
    resposta = cliente_logado.post(_fazenda(cenario) + 'desarquivar')
    assert (resposta.status_code, resposta['Location']) == (302, _fazenda(cenario))
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is None
    assert 'F1' not in cliente_logado.get('/arquivadas/').content.decode().split('<main')[1]


def test_desarquivar_com_ancestral_arquivado_mostra_o_motivo_e_nao_restaura(cliente_logado, administradora, cenario):
    arquivar(administradora, cenario.x)
    resposta = cliente_logado.post(_fazenda(cenario) + 'desarquivar')
    assert resposta.status_code == 400
    assert 'Desarquive o item de cima antes.' in resposta.content.decode()
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is not None


def test_sub_area_arquivada_aparece_na_secao_da_fazenda_com_desarquivar(cliente_logado, administradora, cenario):
    arquivar(administradora, SubArea.objects.get(pk=cenario.g2.pk))
    html = cliente_logado.get(_fazenda(cenario)).content.decode()
    assert '<h2>Arquivadas</h2>' in html
    assert f'{_sub_area(cenario, cenario.g2)}desarquivar' in html


def test_so_leitura_nao_ve_links_de_gestao(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.x)
    html = cliente_logado.get(_fazenda(cenario)).content.decode().split('<main')[1]
    for texto in ('Renomear fazenda', 'Arquivar fazenda', 'Cadastrar sub-área'):
        assert texto not in html
