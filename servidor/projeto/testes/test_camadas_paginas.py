"""Telas de camadas (008 T4.1; R11, R12, R18, R21; A5, A6, A8): envio, prévia e publicação na casca da 003.

Sem `publicar_camada` na fazenda, a página responde 404 por URL direta, igual ao de envio ou fazenda inexistente. A prévia e
a publicação em si são da API (`catalogo/testes/test_api.py`); aqui se confere a página e o molde que a `camadas.js` usa.
"""

import uuid
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Estudo, EnvioCamada, Tema
from permissao.models import Cargo, CargoPermissao

pytestmark = pytest.mark.django_db

PAGINAS = ('camadas_novo', 'camadas_previa', 'camadas_confirmacao')


@pytest.fixture
def publicador(conta, cenario, conceder_direto):
    """Cargo com `ver` e `publicar_camada`, concedido a `conta` na fazenda F1."""
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Publicador sintético', base='curador')
    CargoPermissao.objects.bulk_create(CargoPermissao(cargo=cargo, permissao_id=acao) for acao in ('ver', 'publicar_camada'))
    conceder_direto(conta.pessoa, cargo, cenario.f1)
    return conta


@pytest.fixture
def so_ver(conta, cenario, conceder_direto):
    """Cargo só com `ver` na fazenda F1: ver a fazenda não basta para publicar."""
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Leitor sintético', base='usuario')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='ver')
    conceder_direto(conta.pessoa, cargo, cenario.f1)
    return conta


@pytest.fixture
def envio(conta, cenario):
    return EnvioCamada.objects.create(
        criado_por=conta.pessoa, empresa=cenario.x, fazenda=cenario.f1, arquivo_temporario='camada-sintetica.bin',
        hash_original='0' * 64, expira_em=timezone.now() + timedelta(hours=1),
    )


@pytest.fixture
def estudo(cenario):
    tema = Tema.objects.create(empresa=cenario.x, nome='Tema sintético')
    return Estudo.objects.create(empresa=cenario.x, fazenda=cenario.f1, tema=tema, nome='Estudo sintético')


def _url(nome, cenario, envio_id=None):
    kwargs = {'empresa_id': cenario.x.pk, 'fazenda_id': cenario.f1.pk}
    if nome != 'camadas_novo':
        kwargs['envio_id'] = envio_id if envio_id is not None else uuid.UUID(int=1)
    return reverse(nome, kwargs=kwargs)


# --- caminho feliz ---


def test_envio_mostra_formulario_com_token_csrf_e_script_com_nonce(cliente_logado, publicador, cenario):
    resposta = cliente_logado.get(_url('camadas_novo', cenario))
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert 'id="formulario-envio"' in html
    assert 'name="csrfmiddlewaretoken"' in html
    assert f'data-api-criar="/api/v1/fazendas/{cenario.f1.pk}/envios"' in html
    assert '<script src="/static/projeto/camadas.js" nonce=' in html


def test_previa_leva_a_api_do_envio_e_mostra_carregamento(cliente_logado, publicador, cenario, envio):
    resposta = cliente_logado.get(_url('camadas_previa', cenario, envio.publico_id))
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert f'data-api-previa="/api/v1/envios/{envio.publico_id}"' in html
    assert 'Carregando a prévia' in html
    assert '<output id="previa-carregando">' in html  # o aviso de carregamento é <output>, o de status (T4.8)
    assert 'Nada foi publicado' in html


def test_publicacao_lista_estudo_e_leva_a_api_de_publicar(cliente_logado, publicador, cenario, envio, estudo):
    resposta = cliente_logado.get(_url('camadas_confirmacao', cenario, envio.publico_id))
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert f'<option value="{estudo.pk}">Estudo sintético</option>' in html
    assert f'data-api-publicar="/api/v1/envios/{envio.publico_id}/publicar"' in html
    assert 'id="formulario-publicacao" hidden' in html  # aparece depois que a prévia carrega (camadas.js)
    assert '<output id="publicacao-carregando">' in html
    assert 'id="revisao-nos"' in html  # lista de revisão de nós, preenchida pelo camadas.js
    # Texto fiel ao comportamento: sugestão pré-selecionada, fora de nó fica na fazenda, e 'Própria fazenda' é a escolha explícita.
    for trecho in ('já vêm com o nó de maior área escolhido', 'Feições fora de todos os nós ficam na própria fazenda', "escolha 'Própria fazenda'", 'precisam de escolha'):
        assert trecho in html, trecho
    assert '<output class="aviso aviso-sucesso" id="publicacao-sucesso" hidden>' in html


def test_previa_com_mapa_ligado_leva_o_mapa_a_geometria_do_envio(cliente_logado, publicador, cenario, envio, settings):
    settings.MAPA_TESTE_ATIVO = True
    html = cliente_logado.get(_url('camadas_previa', cenario, envio.publico_id)).content.decode()
    assert '<section class="mapa" data-mapa' in html
    assert f'data-camadas-url="/api/v1/envios/{envio.publico_id}/geometria"' in html
    # O mapa.js e o CSS do MapLibre entram junto: sem o script, o aviso "não foi possível abrir o mapa" fica na tela (T4.8).
    assert '<script type="module" src="/static/projeto/mapa.js"' in html
    assert 'projeto/terceiros/maplibre/maplibre-gl.css' in html
    assert 'data-mapa-truncado' in html  # aviso de geometria cortada (T4.8, P2): fica escondido até o mapa dizer que cortou
    # As regiões que o mapa.js procura (camadas, consulta, ficha): sem elas, `replaceChildren` cai em null (T4.8).
    for regiao in ('camadas', 'consulta', 'ficha'):
        assert f'data-conteudo-de="{regiao}"' in html


# --- caminho infeliz ---


@pytest.mark.parametrize('nome', PAGINAS)
def test_sem_permissao_por_url_direta_e_404(cliente_logado, cenario, envio, nome):
    assert cliente_logado.get(_url(nome, cenario, envio.publico_id)).status_code == 404


@pytest.mark.parametrize('nome', PAGINAS)
def test_ver_a_fazenda_nao_basta_para_publicar(cliente_logado, so_ver, cenario, envio, nome):
    assert cliente_logado.get(_url(nome, cenario, envio.publico_id)).status_code == 404


@pytest.mark.parametrize('nome', PAGINAS)
def test_fazenda_de_outra_empresa_e_404_mesmo_com_permissao(cliente_logado, publicador, cenario, envio, nome):
    kwargs = {'empresa_id': cenario.y.pk, 'fazenda_id': cenario.f1.pk}
    if nome != 'camadas_novo':
        kwargs['envio_id'] = envio.publico_id
    assert cliente_logado.get(reverse(nome, kwargs=kwargs)).status_code == 404


def test_envio_de_outra_fazenda_e_404(cliente_logado, publicador, cenario, conta):
    de_outra = EnvioCamada.objects.create(
        criado_por=conta.pessoa, empresa=cenario.x, fazenda=cenario.f2, arquivo_temporario='outra-sintetica.bin',
        hash_original='1' * 64, expira_em=timezone.now() + timedelta(hours=1),
    )
    assert cliente_logado.get(_url('camadas_previa', cenario, de_outra.publico_id)).status_code == 404


def test_envio_inexistente_e_404(cliente_logado, publicador, cenario):
    assert cliente_logado.get(_url('camadas_previa', cenario, uuid.uuid4())).status_code == 404


def test_envio_expirado_mostra_aviso_e_nao_o_formulario(cliente_logado, publicador, cenario, envio):
    EnvioCamada.objects.filter(pk=envio.pk).update(expira_em=timezone.now() - timedelta(minutes=1))
    previa = cliente_logado.get(_url('camadas_previa', cenario, envio.publico_id)).content.decode()
    confirmacao = cliente_logado.get(_url('camadas_confirmacao', cenario, envio.publico_id)).content.decode()
    assert 'Este envio expirou. Envie o arquivo de novo.' in previa
    assert 'data-api-previa' not in previa  # sem prévia nem publicação para um envio vencido
    assert 'Este envio expirou. Envie o arquivo de novo.' in confirmacao
    assert 'id="formulario-publicacao"' not in confirmacao


def test_fazenda_sem_estudo_mostra_estado_vazio(cliente_logado, publicador, cenario, envio):
    resposta = cliente_logado.get(_url('camadas_confirmacao', cenario, envio.publico_id))
    assert resposta.status_code == 200
    assert 'não tem estudo cadastrado' in resposta.content.decode()
    assert 'id="formulario-publicacao"' not in resposta.content.decode()


def test_nome_de_estudo_com_marcacao_aparece_escapado(cliente_logado, publicador, cenario, envio, estudo):
    Estudo.objects.filter(pk=estudo.pk).update(nome='<script>alert("x")</script>')
    html = cliente_logado.get(_url('camadas_confirmacao', cenario, envio.publico_id)).content.decode()
    assert '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;' in html
    assert '<script>alert' not in html


def test_previa_com_mapa_desligado_segue_sem_mapa_e_diz_isso(cliente_logado, publicador, cenario, envio, settings):
    settings.MAPA_TESTE_ATIVO = False
    html = cliente_logado.get(_url('camadas_previa', cenario, envio.publico_id)).content.decode()
    assert '<section class="mapa" data-mapa' not in html
    assert 'não está disponível neste ambiente' in html
    assert 'projeto/mapa.js' not in html  # sem a flag, nenhum script do mapa vai à página
    assert 'data-api-previa=' in html  # o resumo continua na tela


@pytest.mark.parametrize('nome', PAGINAS)
def test_metodo_errado_e_405(cliente_logado, publicador, cenario, envio, nome):
    assert cliente_logado.post(_url(nome, cenario, envio.publico_id)).status_code == 405


def test_deslogado_vai_para_a_entrada(cenario):
    resposta = Client().get(_url('camadas_novo', cenario))
    assert resposta.status_code == 302
    assert resposta['Location'].startswith('/entrar')
