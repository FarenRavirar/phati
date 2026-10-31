"""Convite de CPF que já existe (R24, A20; T5.5i): pendente até o aceite, que refaz as regras de R10 com quem convidou."""

import json
import threading
from datetime import timedelta
from importlib import import_module

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import Client
from django.utils import timezone

from comum.models import EventoAuditoria
from identidade import cpf as modulo_cpf
from identidade import sessao
from identidade.models import Pessoa
from permissao import convite as servico
from permissao import delegacao
from permissao.models import CategoriaDado, Convite, Concessao, Permissao


@pytest.fixture(autouse=True)
def catalogo(db):
    for codigo, descricao, delegavel in import_module('permissao.migrations.0001_initial').ACOES:
        Permissao.objects.get_or_create(codigo=codigo, defaults={'descricao': descricao, 'delegavel': delegavel})


def _com(fabrica_pessoa, conceder_direto, cargo, escopo, nome='Pessoa'):
    pessoa = fabrica_pessoa(nome)
    conceder_direto(pessoa, cargo, escopo)
    return pessoa


def _cpf_de(pessoa):
    return modulo_cpf.decifrar(pessoa.cpf_cifrado)


def _enviar(pessoa, rota, corpo=None, metodo='post'):
    cabecalho = {'Authorization': f'Bearer {sessao.emitir_acesso(pessoa, "teste")}'}
    chamar = getattr(Client(), metodo)
    if metodo == 'get':
        return chamar(f'/api/v1/{rota}', headers=cabecalho)
    return chamar(f'/api/v1/{rota}', data=json.dumps(corpo or {}), content_type='application/json', headers=cabecalho)


def _convidar(admin, cenario, existente, cargo='usuario', escopo=None):
    corpo = {
        'nome': 'Qualquer', 'email': 'q@exemplo.test', 'cpf': _cpf_de(existente),
        'cargo_id': cenario.cargos_x[cargo].pk, 'escopo': escopo or {'fazenda_id': cenario.f1.pk},
    }
    return _enviar(admin, 'pessoas', corpo)


def test_cpf_novo_cria_a_pessoa_concede_e_devolve_a_senha_temporaria(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    corpo = {'nome': 'Nova', 'email': 'n@exemplo.test', 'cpf': cpf_novo(), 'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}}
    resposta = _enviar(admin, 'pessoas', corpo)
    dados = resposta.json()
    assert (resposta.status_code, dados['pendente']) == (201, False)
    assert dados['senha_temporaria']
    assert Concessao.objects.filter(pessoa_id=dados['id']).count() == 1


def test_cpf_que_ja_existe_vira_convite_pendente_sem_dado_da_pessoa_e_sem_concessao(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = _com(fabrica_pessoa, conceder_direto, cenario.cargos_y['usuario'], cenario.fy, 'Moradora de Y')
    resposta = _convidar(admin, cenario, existente)
    assert (resposta.status_code, resposta.json()) == (201, {'pendente': True, 'id': None, 'concessao_id': None, 'senha_temporaria': None})
    assert 'Moradora de Y' not in resposta.content.decode()
    assert not Concessao.objects.filter(pessoa=existente, empresa=cenario.x).exists()
    assert Convite.objects.filter(pessoa=existente, convidado_por=admin).count() == 1
    assert EventoAuditoria.objects.filter(acao='convite_criado', pessoa_id=admin.pk).exists()


def test_quem_nao_pode_conceder_e_negado_igual_para_cpf_novo_e_existente(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    tecnico = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['tecnico'], cenario.f1)
    existente = fabrica_pessoa('Existente')
    novo = {'nome': 'N', 'email': 'n@exemplo.test', 'cpf': cpf_novo(), 'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}}
    assert _enviar(tecnico, 'pessoas', novo).status_code == _convidar(tecnico, cenario, existente).status_code == 403
    assert not Convite.objects.exists()


def test_convite_avisa_a_pessoa_por_e_mail_sem_dar_pista_a_quem_convida(cenario, fabrica_pessoa, conceder_direto, mailoutbox):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    resposta = _convidar(admin, cenario, existente)
    assert resposta.status_code == 201
    assert [m.to for m in mailoutbox] == [[existente.email]]
    assert 'Empresa X' in mailoutbox[0].body
    assert existente.email not in resposta.content.decode()


def test_convite_repetido_nao_empilha_linhas(cenario, fabrica_pessoa, conceder_direto, mailoutbox):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    for _ in range(3):
        assert _convidar(admin, cenario, existente).status_code == 201
    assert Convite.objects.filter(pessoa=existente).count() == 1
    assert len(mailoutbox) == 1  # o repetido não reenvia: o reenvio é pedido à parte


def test_a_pessoa_convidada_ve_so_os_convites_dela_e_aceita(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Administradora')
    existente, outra = fabrica_pessoa('Existente'), fabrica_pessoa('Outra')
    _convidar(admin, cenario, existente)
    lista = _enviar(existente, 'convites', metodo='get').json()
    assert [(c['empresa_nome'], c['cargo_nome'], c['convidado_por_nome']) for c in lista] == [('Empresa X', 'Usuário', 'Administradora')]
    assert _enviar(outra, 'convites', metodo='get').json() == []
    convite_id = lista[0]['id']
    assert _enviar(outra, f'convites/{convite_id}/aceitar').status_code == 404
    assert not Concessao.objects.filter(pessoa=existente, empresa=cenario.x).exists()
    assert _enviar(existente, f'convites/{convite_id}/aceitar').status_code == 204
    concessao = Concessao.objects.get(pessoa=existente, empresa=cenario.x)
    assert (concessao.fazenda_id, concessao.concedida_por) == (cenario.f1.pk, admin)
    assert EventoAuditoria.objects.filter(acao='convite_aceito', pessoa_id=existente.pk).exists()
    assert _enviar(existente, 'convites', metodo='get').json() == []


def test_aceitar_duas_vezes_ou_depois_de_recusar_falha_sem_segunda_concessao(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    _convidar(admin, cenario, existente)
    convite_id = Convite.objects.get().pk
    assert _enviar(existente, f'convites/{convite_id}/aceitar').status_code == 204
    repetida = _enviar(existente, f'convites/{convite_id}/aceitar')
    assert (repetida.status_code, repetida.json()) == (400, {'detalhe': 'convite_encerrado'})
    assert Concessao.objects.filter(pessoa=existente, empresa=cenario.x).count() == 1


def test_recusar_encerra_o_convite_e_nao_concede(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    _convidar(admin, cenario, existente)
    convite_id = Convite.objects.get().pk
    assert _enviar(existente, f'convites/{convite_id}/recusar').status_code == 204
    depois = _enviar(existente, f'convites/{convite_id}/aceitar')
    assert (depois.status_code, depois.json()) == (400, {'detalhe': 'convite_encerrado'})
    assert not Concessao.objects.filter(pessoa=existente, empresa=cenario.x).exists()
    assert EventoAuditoria.objects.filter(acao='convite_recusado').exists()


def test_convite_vencido_nao_aceita_e_some_da_lista(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    _convidar(admin, cenario, existente)
    Convite.objects.update(expira_em=timezone.now() - timedelta(seconds=1))
    assert _enviar(existente, 'convites', metodo='get').json() == []
    resposta = _enviar(existente, f'convites/{Convite.objects.get().pk}/aceitar')
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'convite_vencido'})
    assert not Concessao.objects.filter(pessoa=existente, empresa=cenario.x).exists()


def test_quem_convidou_perdeu_a_autoridade_antes_do_aceite(cenario, fabrica_pessoa, conceder_direto):
    admin = fabrica_pessoa('Administradora')
    concessao_do_admin = conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    _convidar(admin, cenario, existente)
    concessao_do_admin.revogada_em, concessao_do_admin.revogada_por = timezone.now(), admin
    concessao_do_admin.save(update_fields=['revogada_em', 'revogada_por'])
    resposta = _enviar(existente, f'convites/{Convite.objects.get().pk}/aceitar')
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'convite_sem_autoridade'})
    assert not Concessao.objects.filter(pessoa=existente, empresa=cenario.x).exists()


def test_cargo_que_deixou_de_caber_no_nivel_de_quem_convidou_falha_no_aceite(cenario, fabrica_pessoa, conceder_direto):
    curador = fabrica_pessoa('Curador')
    concessao = conceder_direto(curador, cenario.cargos_x['curador'], cenario.f1)
    existente = fabrica_pessoa('Existente')
    assert _convidar(curador, cenario, existente, cargo='usuario').status_code == 201
    # O curador troca a concessão de Curador por uma de Usuário: continua com acesso, mas já não convida ninguém.
    concessao.revogada_em, concessao.revogada_por = timezone.now(), curador
    concessao.save(update_fields=['revogada_em', 'revogada_por'])
    conceder_direto(curador, cenario.cargos_x['usuario'], cenario.f1)
    resposta = _enviar(existente, f'convites/{Convite.objects.get().pk}/aceitar')
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'convite_sem_autoridade'})


def test_aceite_com_fim_no_passado_e_vencido_e_nao_estoura_o_banco(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    fim = (timezone.now() + timedelta(days=1)).isoformat()
    corpo = {'nome': 'Q', 'email': 'q@exemplo.test', 'cpf': _cpf_de(existente), 'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}, 'fim': fim}
    assert _enviar(admin, 'pessoas', corpo).status_code == 201
    Convite.objects.update(fim=timezone.now() - timedelta(seconds=1))
    resposta = _enviar(existente, f'convites/{Convite.objects.get().pk}/aceitar')
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'convite_vencido'})


def test_servico_cpf_invalido_levanta_erro_de_regra_e_nao_cria_convite(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    with pytest.raises(ValidationError):
        servico.convidar_por_cpf(admin, 'N', 'n@exemplo.test', '111.111.111-11', cenario.cargos_x['usuario'], cenario.f1)
    assert not Convite.objects.exists()


def test_servico_anonimo_nao_convida(cenario):
    from django.contrib.auth.models import AnonymousUser

    anonima = AnonymousUser()
    with pytest.raises(PermissionDenied):
        servico.convidar_por_cpf(anonima, 'N', 'n@exemplo.test', '529.982.247-25', cenario.cargos_x['usuario'], cenario.f1)


def test_convite_nao_cria_pessoa_nova(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    total = Pessoa.objects.count()
    _convidar(admin, cenario, existente)
    assert Pessoa.objects.count() == total


@pytest.fixture
def mundo_do_convite(cenario, fabrica_pessoa, conceder_direto):
    # Montado como dono, antes de `como_app`.
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    return admin, fabrica_pessoa('Existente')


@pytest.mark.django_db(transaction=True, databases=['default', 'app'])
def test_convite_e_aceite_sob_o_papel_app_com_rls(cenario, mundo_do_convite, como_app):
    admin, existente = mundo_do_convite
    assert _convidar(admin, cenario, existente).status_code == 201
    lista = _enviar(existente, 'convites', metodo='get').json()
    assert [c['empresa_nome'] for c in lista] == ['Empresa X']
    assert _enviar(existente, f'convites/{lista[0]["id"]}/aceitar').status_code == 204
    assert _enviar(existente, 'convites', metodo='get').json() == []


def test_servico_nega_a_quem_nao_pode_conceder_mesmo_para_cpf_que_ja_existe(cenario, fabrica_pessoa, conceder_direto):
    # A rota já barra o Técnico antes; aqui a checagem do serviço, que vale para quem o chamar de outro lugar.
    tecnico = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['tecnico'], cenario.f1)
    existente = fabrica_pessoa('Existente')
    cpf = _cpf_de(existente)
    with pytest.raises(PermissionDenied):
        servico.convidar_por_cpf(tecnico, 'N', 'n@exemplo.test', cpf, cenario.cargos_x['usuario'], cenario.f1)
    assert not Convite.objects.exists()


def test_quem_convidou_lista_cancela_e_a_pessoa_nao_aceita_mais(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    _convidar(admin, cenario, existente)
    lista = _enviar(admin, 'convites-enviados', metodo='get').json()
    assert [(c['empresa_nome'], c['cargo_nome']) for c in lista] == [('Empresa X', 'Usuário')]
    assert 'Existente' not in json.dumps(lista)
    assert _enviar(admin, f'convites-enviados/{lista[0]["id"]}', metodo='delete').status_code == 204
    assert _enviar(admin, 'convites-enviados', metodo='get').json() == []
    assert _enviar(existente, 'convites', metodo='get').json() == []
    resposta = _enviar(existente, f'convites/{lista[0]["id"]}/aceitar')
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'convite_encerrado'})
    assert not Concessao.objects.filter(pessoa=existente, empresa=cenario.x).exists()
    assert EventoAuditoria.objects.filter(acao='convite_cancelado', pessoa_id=admin.pk).exists()


def test_outro_administrador_nao_cancela_nem_reenvia_convite_alheio(cenario, fabrica_pessoa, conceder_direto, mailoutbox):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Admin')
    colega = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Colega')
    existente = fabrica_pessoa('Existente')
    _convidar(admin, cenario, existente)
    convite_id = Convite.objects.get().pk
    antes = len(mailoutbox)
    assert _enviar(colega, 'convites-enviados', metodo='get').json() == []
    assert _enviar(colega, f'convites-enviados/{convite_id}', metodo='delete').status_code == 404
    assert _enviar(colega, f'convites-enviados/{convite_id}/reenviar').status_code == 404
    assert Convite.objects.get().cancelado_em is None
    assert len(mailoutbox) == antes


def test_reenviar_renova_a_validade_e_avisa_de_novo(cenario, fabrica_pessoa, conceder_direto, mailoutbox):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    _convidar(admin, cenario, existente)
    Convite.objects.update(expira_em=timezone.now() + timedelta(hours=1), enviado_em=timezone.now() - timedelta(minutes=2))
    convite_id = Convite.objects.get().pk
    assert _enviar(admin, f'convites-enviados/{convite_id}/reenviar').status_code == 204
    assert Convite.objects.get().expira_em > timezone.now() + timedelta(days=6)
    assert len(mailoutbox) == 2
    assert Convite.objects.get().envios == 2


def test_tecnico_nao_lista_nem_cancela_convites(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    tecnico = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['tecnico'], cenario.f1)
    _convidar(admin, cenario, fabrica_pessoa('Existente'))
    convite_id = Convite.objects.get().pk  # convite de verdade, de outra pessoa: o id 1 solto passaria por 404 de qualquer jeito
    assert _enviar(tecnico, 'convites-enviados', metodo='get').json() == []
    assert _enviar(tecnico, f'convites-enviados/{convite_id}', metodo='delete').status_code in (403, 404)
    assert _enviar(tecnico, f'convites-enviados/{convite_id}/reenviar').status_code in (403, 404)
    assert Convite.objects.get().cancelado_em is None


def test_servico_so_deixa_quem_convidou_cancelar_ou_reenviar(cenario, fabrica_pessoa, conceder_direto):
    # A rota já filtra pelo dono antes; aqui a checagem do serviço, que vale para quem o chamar de outro lugar.
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Admin')
    colega = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Colega')
    _convidar(admin, cenario, fabrica_pessoa('Existente'))
    convite_id = Convite.objects.get().pk
    with pytest.raises(Convite.DoesNotExist):
        servico.cancelar(colega, convite_id)
    with pytest.raises(Convite.DoesNotExist):
        servico.reenviar(colega, convite_id)
    assert Convite.objects.get().cancelado_em is None


def test_reenvio_antes_do_intervalo_e_recusado_sem_novo_e_mail(cenario, fabrica_pessoa, conceder_direto, mailoutbox):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    _convidar(admin, cenario, fabrica_pessoa('Existente'))
    convite_id = Convite.objects.get().pk
    resposta = _enviar(admin, f'convites-enviados/{convite_id}/reenviar')
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'reenvio_cedo'})
    assert len(mailoutbox) == 1
    assert Convite.objects.get().envios == 1


def test_reenvio_passado_o_teto_por_convite_e_recusado(cenario, fabrica_pessoa, conceder_direto, mailoutbox):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    _convidar(admin, cenario, fabrica_pessoa('Existente'))
    convite_id = Convite.objects.get().pk
    for esperado in (2, 3, 4):
        Convite.objects.update(enviado_em=timezone.now() - timedelta(minutes=2))
        assert _enviar(admin, f'convites-enviados/{convite_id}/reenviar').status_code == 204
        assert Convite.objects.get().envios == esperado
    Convite.objects.update(enviado_em=timezone.now() - timedelta(minutes=2))
    resposta = _enviar(admin, f'convites-enviados/{convite_id}/reenviar')
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'reenvio_esgotado'})
    assert len(mailoutbox) == 4


def test_teto_de_convites_por_hora_de_quem_convida(cenario, fabrica_pessoa, conceder_direto, mailoutbox):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    for numero in range(servico.MAXIMO_DE_CONVITES_POR_HORA):
        assert _convidar(admin, cenario, fabrica_pessoa(f'Pessoa {numero}')).status_code == 201
    resposta = _convidar(admin, cenario, fabrica_pessoa('Uma a mais'))
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'convites_demais'})
    assert Convite.objects.count() == servico.MAXIMO_DE_CONVITES_POR_HORA
    assert len(mailoutbox) == servico.MAXIMO_DE_CONVITES_POR_HORA
    Convite.objects.update(criado_em=timezone.now() - timedelta(hours=2))
    assert _convidar(admin, cenario, fabrica_pessoa('Depois da hora')).status_code == 201


def test_convite_repetido_com_outro_periodo_substitui_o_anterior(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    longo = (timezone.now() + timedelta(days=30)).isoformat()
    curto = (timezone.now() + timedelta(days=1)).isoformat()
    base = {'nome': 'Q', 'email': 'q@exemplo.test', 'cpf': _cpf_de(existente), 'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}}
    assert _enviar(admin, 'pessoas', {**base, 'fim': longo}).status_code == 201
    Convite.objects.update(enviado_em=timezone.now() - timedelta(minutes=2))
    assert _enviar(admin, 'pessoas', {**base, 'fim': curto}).status_code == 201
    assert Convite.objects.filter(cancelado_em__isnull=True).count() == 1
    assert Convite.objects.filter(cancelado_em__isnull=False).count() == 1
    assert _enviar(existente, f'convites/{Convite.objects.get(cancelado_em__isnull=True).pk}/aceitar').status_code == 204
    concessao = Concessao.objects.get(pessoa=existente, empresa=cenario.x)
    assert concessao.fim is not None
    assert concessao.fim < timezone.now() + timedelta(days=2)


def test_convite_repetido_com_outras_categorias_substitui_o_anterior(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    categoria = CategoriaDado.objects.create(empresa=cenario.x, nome='Solo')
    base = {'nome': 'Q', 'email': 'q@exemplo.test', 'cpf': _cpf_de(existente), 'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}}
    assert _enviar(admin, 'pessoas', base).status_code == 201
    Convite.objects.update(enviado_em=timezone.now() - timedelta(minutes=2))
    assert _enviar(admin, 'pessoas', {**base, 'categoria_ids': [categoria.pk]}).status_code == 201
    aberto = Convite.objects.get(cancelado_em__isnull=True)
    assert list(aberto.categorias.all()) == [categoria]


def test_convite_vencido_sem_resposta_aparece_na_lista_de_quem_convidou_marcado(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    _convidar(admin, cenario, fabrica_pessoa('Existente'))
    Convite.objects.update(expira_em=timezone.now() - timedelta(days=1))
    lista = _enviar(admin, 'convites-enviados', metodo='get').json()
    assert [c['vencido'] for c in lista] == [True]
    Convite.objects.update(enviado_em=timezone.now() - timedelta(minutes=2))
    assert _enviar(admin, f'convites-enviados/{lista[0]["id"]}/reenviar').status_code == 204
    assert [c['vencido'] for c in _enviar(admin, 'convites-enviados', metodo='get').json()] == [False]


def test_convite_vencido_ha_muito_tempo_sai_da_lista(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    _convidar(admin, cenario, fabrica_pessoa('Existente'))
    Convite.objects.update(expira_em=timezone.now() - servico.RETENCAO_DE_VENCIDOS - timedelta(days=1))
    assert _enviar(admin, 'convites-enviados', metodo='get').json() == []


def test_cpf_novo_consome_a_mesma_cota_por_hora_do_convite(cenario, fabrica_pessoa, conceder_direto, cpf_novo, mailoutbox):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    corpo = lambda: {'nome': 'N', 'email': 'n@exemplo.test', 'cpf': cpf_novo(), 'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}}
    for _ in range(servico.MAXIMO_DE_CONVITES_POR_HORA):
        assert _enviar(admin, 'pessoas', corpo()).status_code == 201
    total = Pessoa.objects.count()
    resposta = _enviar(admin, 'pessoas', corpo())
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'convites_demais'})
    assert Pessoa.objects.count() == total
    assert len(mailoutbox) == servico.MAXIMO_DE_CONVITES_POR_HORA


def test_cota_mistura_cpf_novo_e_existente(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    metade = servico.MAXIMO_DE_CONVITES_POR_HORA // 2
    novo = lambda: {'nome': 'N', 'email': 'n@exemplo.test', 'cpf': cpf_novo(), 'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}}
    for numero in range(metade):
        assert _enviar(admin, 'pessoas', novo()).status_code == 201
        assert _convidar(admin, cenario, fabrica_pessoa(f'Existente {numero}')).status_code == 201
    assert _enviar(admin, 'pessoas', novo()).status_code == 400
    assert _convidar(admin, cenario, fabrica_pessoa('Uma a mais')).status_code == 400


@pytest.mark.parametrize('base', ['administrador', 'curador'])
def test_categoria_em_cargo_que_nao_aceita_categoria_e_recusada_antes_de_gravar(cenario, fabrica_pessoa, conceder_direto, cpf_novo, mailoutbox, base):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    categoria = CategoriaDado.objects.create(empresa=cenario.x, nome='Solo')
    total = Pessoa.objects.count()
    comum = {'nome': 'N', 'email': 'n@exemplo.test', 'cargo_id': cenario.cargos_x[base].pk, 'escopo': {'fazenda_id': cenario.f1.pk}, 'categoria_ids': [categoria.pk]}
    novo = _enviar(admin, 'pessoas', {**comum, 'cpf': cpf_novo()})
    ja_existe = _enviar(admin, 'pessoas', {**comum, 'cpf': _cpf_de(existente)})
    assert [(r.status_code, r.json()) for r in (novo, ja_existe)] == [(400, {'detalhe': 'categoria_incompativel'})] * 2
    assert Pessoa.objects.count() == total
    assert not Convite.objects.exists()
    assert mailoutbox == []


@pytest.fixture
def mundo_da_cota(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    return admin, [fabrica_pessoa(f'Existente {n}') for n in range(servico.MAXIMO_DE_CONVITES_POR_HORA + 2)]


@pytest.mark.django_db(transaction=True)
def test_pedidos_paralelos_do_mesmo_remetente_nao_passam_do_teto(cenario, mundo_da_cota):
    admin, existentes = mundo_da_cota
    cargo, fazenda = cenario.cargos_x['usuario'], cenario.f1
    for pessoa in existentes[: servico.MAXIMO_DE_CONVITES_POR_HORA - 1]:
        servico.convidar_por_cpf(admin, 'N', 'n@exemplo.test', _cpf_de(pessoa), cargo, fazenda)
    resultados, largada = [], threading.Barrier(2)

    def correr(pessoa):
        largada.wait()
        try:
            servico.convidar_por_cpf(admin, 'N', 'n@exemplo.test', _cpf_de(pessoa), cargo, fazenda)
            resultados.append('ok')
        except ValidationError as erro:
            resultados.append(erro.code)
        finally:
            connection.close()

    fios = [threading.Thread(target=correr, args=(pessoa,)) for pessoa in existentes[-2:]]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert sorted(resultados) == ['convites_demais', 'ok']
    assert Convite.objects.count() == servico.MAXIMO_DE_CONVITES_POR_HORA


def test_plataforma_com_cargo_de_outra_empresa_e_negada_nos_dois_caminhos_e_nada_fica(cenario, plataforma, fabrica_pessoa, cpf_novo, mailoutbox):
    existente = fabrica_pessoa('Existente')
    cargo_de_y, escopo_de_x = cenario.cargos_y['usuario'], {'fazenda_id': cenario.f1.pk}
    base = {'nome': 'N', 'email': 'n@exemplo.test', 'cargo_id': cargo_de_y.pk, 'escopo': escopo_de_x}
    total = Pessoa.objects.count()
    novo = _enviar(plataforma, 'pessoas', {**base, 'cpf': cpf_novo()})
    ja_existe = _enviar(plataforma, 'pessoas', {**base, 'cpf': _cpf_de(existente)})
    assert (novo.status_code, ja_existe.status_code) == (403, 403)
    assert Pessoa.objects.count() == total
    assert not Convite.objects.exists()
    assert mailoutbox == []
    conceder = _enviar(plataforma, f'pessoas/{existente.pk}/concessoes', {'cargo_id': cargo_de_y.pk, 'escopo': escopo_de_x})
    assert conceder.status_code == 403
    assert not Concessao.objects.filter(pessoa=existente).exists()


def test_convite_com_fim_ja_passado_sai_das_listas_e_nao_se_reenvia(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    _convidar(admin, cenario, existente)
    convite_id = Convite.objects.get().pk
    Convite.objects.update(fim=timezone.now() - timedelta(seconds=1), enviado_em=timezone.now() - timedelta(minutes=2))
    assert _enviar(existente, 'convites', metodo='get').json() == []
    assert _enviar(admin, 'convites-enviados', metodo='get').json() == []
    resposta = _enviar(admin, f'convites-enviados/{convite_id}/reenviar')
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'convite_vencido'})


def test_substituir_o_convite_herda_o_intervalo_e_o_teto_de_envios(cenario, fabrica_pessoa, conceder_direto, mailoutbox):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    base = {'nome': 'Q', 'email': 'q@exemplo.test', 'cpf': _cpf_de(existente), 'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}}
    dia = lambda numero: (timezone.now() + timedelta(days=numero)).isoformat()
    assert _enviar(admin, 'pessoas', {**base, 'fim': dia(10)}).status_code == 201
    cedo = _enviar(admin, 'pessoas', {**base, 'fim': dia(11)})
    assert (cedo.status_code, cedo.json()) == (400, {'detalhe': 'reenvio_cedo'})
    assert Convite.objects.filter(cancelado_em__isnull=True).count() == 1
    assert len(mailoutbox) == 1
    for numero in (12, 13, 14):  # a 2ª, a 3ª e a 4ª mensagem
        Convite.objects.update(enviado_em=timezone.now() - timedelta(minutes=2))
        assert _enviar(admin, 'pessoas', {**base, 'fim': dia(numero)}).status_code == 201
    assert Convite.objects.get(cancelado_em__isnull=True).envios == 4
    Convite.objects.update(enviado_em=timezone.now() - timedelta(minutes=2))
    esgotado = _enviar(admin, 'pessoas', {**base, 'fim': dia(15)})
    assert (esgotado.status_code, esgotado.json()) == (400, {'detalhe': 'reenvio_esgotado'})
    assert len(mailoutbox) == 4


def test_convites_enviados_de_empresa_que_a_pessoa_perdeu_nao_aparecem(cenario, fabrica_pessoa, conceder_direto):
    admin = fabrica_pessoa('Administradora')
    concessao_de_x = conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    _convidar(admin, cenario, fabrica_pessoa('Existente'))
    assert len(_enviar(admin, 'convites-enviados', metodo='get').json()) == 1
    concessao_de_x.revogada_em, concessao_de_x.revogada_por = timezone.now(), admin
    concessao_de_x.save(update_fields=['revogada_em', 'revogada_por'])
    conceder_direto(admin, cenario.cargos_y['administrador'], cenario.y)  # ainda convida, mas só em Y
    assert _enviar(admin, 'convites-enviados', metodo='get').json() == []


@pytest.mark.django_db(transaction=True)
def test_aceite_espera_a_revogacao_em_andamento_de_quem_convidou(cenario, fabrica_pessoa, conceder_direto):
    # Sem a trava de quem convidou, o aceite não via a revogação ainda sem commit e criava a concessão (Sourcery, PR #21).
    admin = fabrica_pessoa('Administradora')
    concessao = conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    _convidar(admin, cenario, existente)
    convite = Convite.objects.get()
    travada, liberar, resultado = threading.Event(), threading.Event(), []

    def revogar():
        try:
            with transaction.atomic():
                delegacao._travar_pessoa(admin.pk)
                Concessao.objects.filter(pk=concessao.pk).update(revogada_em=timezone.now(), revogada_por=admin)
                travada.set()
                liberar.wait(10)
        finally:
            connection.close()

    def aceitar():
        try:
            servico.aceitar(existente, convite.pk)
            resultado.append('ok')
        except ValidationError as erro:
            resultado.append(erro.code)
        finally:
            connection.close()

    fio_revogacao = threading.Thread(target=revogar)
    fio_revogacao.start()
    assert travada.wait(10)
    fio_aceite = threading.Thread(target=aceitar)
    fio_aceite.start()
    fio_aceite.join(1)
    preso = fio_aceite.is_alive()
    liberar.set()
    fio_revogacao.join()
    fio_aceite.join(10)
    assert preso  # esperou a transação de quem convidou
    assert resultado == ['convite_sem_autoridade']
    assert not Concessao.objects.filter(pessoa=existente, empresa=cenario.x).exists()
