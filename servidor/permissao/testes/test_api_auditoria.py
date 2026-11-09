"""`GET /api/v1/auditoria` pela URL real (005 R2, R3, R7; A1 a A4, A7, A8): papéis, empresa alheia, CPF e índice."""

import pytest
from django.db import connection
from django.test import Client

from comum.models import EventoAuditoria
from identidade import sessao
from identidade.models import Pessoa
from permissao.auditoria_leitura import _filtrar
from permissao.pode import Escopos

pytestmark = pytest.mark.django_db


def _ler(pessoa, consulta=''):
    cabecalho = {'Authorization': f'Bearer {sessao.emitir_acesso(pessoa, "teste")}'}
    return Client().get(f'/api/v1/auditoria{consulta}', headers=cabecalho)


def _com(fabrica_pessoa, conceder_direto, cargo, escopo, nome='Pessoa'):
    pessoa = fabrica_pessoa(nome)
    conceder_direto(pessoa, cargo, escopo)
    return pessoa


def test_sem_credencial_responde_401():
    assert Client().get('/api/v1/auditoria').status_code == 401


def test_administrador_da_empresa_le_so_a_dela_e_pede_a_alheia_com_404(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    EventoAuditoria.objects.create(acao='fazenda_criada', empresa_id=cenario.x.pk)
    EventoAuditoria.objects.create(acao='fazenda_criada', empresa_id=cenario.y.pk)
    resposta = _ler(admin, '?acao=fazenda_criada')
    assert resposta.status_code == 200
    assert {linha['empresa'] for linha in resposta.json()} == {'Empresa X'}
    por_url = _ler(admin, f'?empresa_id={cenario.y.pk}')
    inexistente = _ler(admin, '?empresa_id=999999')
    assert (por_url.status_code, inexistente.status_code) == (404, 404)
    assert por_url.json() == inexistente.json()  # igual ao de empresa que não existe


@pytest.mark.parametrize('base', ['curador', 'tecnico', 'usuario'])
def test_demais_cargos_recebem_404(cenario, fabrica_pessoa, conceder_direto, base):
    pessoa = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x[base], cenario.x)
    assert _ler(pessoa).status_code == 404
    assert _ler(pessoa, f'?empresa_id={cenario.x.pk}').status_code == 404


def test_resposta_nunca_leva_cpf_nem_json_cru(cenario, plataforma, cpf_novo):
    cpf = cpf_novo()
    alvo = Pessoa.objects.criar(nome='Alvo Nomeado', email='alvo@exemplo.test', cpf=cpf)
    EventoAuditoria.objects.create(
        acao='redefinicao_pedida', pessoa_id=plataforma.pk, alvo_tipo='Pessoa', alvo_id=alvo.pk,
        empresa_id=cenario.x.pk, detalhes={'cpf': cpf, 'token': 'segredo'},
    )
    resposta = _ler(plataforma, '?acao=redefinicao_pedida')
    texto = resposta.content.decode()
    assert resposta.status_code == 200 and 'Alvo Nomeado' in texto
    assert cpf not in texto and 'segredo' not in texto and '"cpf"' not in texto


def test_abrir_a_lista_grava_a_consulta_e_o_cursor_nao(cenario, plataforma):
    for _ in range(3):
        EventoAuditoria.objects.create(acao='fazenda_criada', empresa_id=cenario.x.pk)
    antes = EventoAuditoria.objects.filter(acao='auditoria_consultada').count()
    primeira = _ler(plataforma, '?acao=fazenda_criada&limite=2').json()
    assert EventoAuditoria.objects.filter(acao='auditoria_consultada').count() == antes + 1
    _ler(plataforma, f'?acao=fazenda_criada&limite=2&depois={primeira[-1]["id"]}')
    assert EventoAuditoria.objects.filter(acao='auditoria_consultada').count() == antes + 1


@pytest.mark.parametrize('consulta', ['?limite=0', '?limite=101', '?depois=-1', '?empresa_id=abc', '?desde=ontem', '?acao=' + 'x' * 61])
def test_parametro_invalido_e_recusado_sem_gravar_consulta(plataforma, consulta):
    antes = EventoAuditoria.objects.filter(acao='auditoria_consultada').count()
    assert _ler(plataforma, consulta).status_code in (400, 422)
    assert EventoAuditoria.objects.filter(acao='auditoria_consultada').count() == antes


def test_a_consulta_por_empresa_e_por_pessoa_usa_indice_em_100_mil_eventos():
    """A8 (R8): `EXPLAIN` sobre 100.000 eventos sintéticos: sem `Seq Scan` e usando o índice de cada filtro.

    Os dados são enviesados de propósito (empresa 0 tem 95% das linhas; as outras e as pessoas são raras): com valores
    uniformes o planejador varre a chave primária e o teste passaria sem índice nenhum.
    """
    EventoAuditoria.objects.bulk_create(
        (EventoAuditoria(acao='fazenda_criada', pessoa_id=i % 5000, empresa_id=(i % 1000) + 1 if i % 20 == 0 else 0,
                         alvo_tipo='Pessoa', alvo_id=i % 7000, detalhes={'pessoa_id': i % 9000}) for i in range(100_000)),
        batch_size=5_000,
    )
    with connection.cursor() as consulta:
        consulta.execute('ANALYZE evento_auditoria')
    consultas = {
        'auditoria_empresa_id': _filtrar(Escopos(empresas=frozenset({3})), None, None, None, None, None, None),
        'auditoria_pessoa_id': _filtrar(Escopos(plataforma=True), None, None, None, 42, None, None),
        'auditoria_alvo': _filtrar(Escopos(plataforma=True), None, None, None, None, 42, None),
        'auditoria_detalhe_pessoa': _filtrar(Escopos(plataforma=True), None, None, None, None, 42, None),
    }
    for indice, eventos in consultas.items():
        plano = eventos.order_by('-id')[:31].explain()
        assert 'Seq Scan' not in plano and indice in plano, plano
