"""API do catálogo pela URL real (008 T3.2; R9, R11, R14, R15, R16, R21): envio, prévia, publicação, leitura paginada.

Caminho feliz e infeliz: 404 idêntico (outra empresa x inexistente x sem permissão), 401 sem credencial, coluna oculta
fora da resposta, do filtro e da busca, texto com marcação escapado, limite de página, arquivo acima do limite, KML
hostil. Dado sintético (R17)."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from catalogo.ingestao import Limites, MENSAGEM_TAMANHO
from catalogo.models import Camada, EnvioCamada, Estudo, Feicao, Tema, VersaoCamada
from catalogo.testes.test_ingestao import geojson
from identidade import cpf as modulo_cpf
from identidade import senha, sessao
from permissao.cargos_base import criar_cargos_base

pytestmark = pytest.mark.django_db(transaction=True, databases=['default', 'app'])
NAO_ENCONTRADO = {'detalhe': 'nao_encontrado'}
METADADOS = {'nome': 'Camada sintetica', 'tema': 'Solo', 'origem': 'Levantamento sintetico'}


@pytest.fixture
def camadas(settings, tmp_path):
    settings.CAMADAS_DIR = tmp_path / 'camadas'
    settings.CAMADAS_DIR.mkdir()
    return settings.CAMADAS_DIR


@pytest.fixture
def mundo(camadas, catalogo_da_corrida, cenario, fabrica_pessoa, conceder_direto):
    m = SimpleNamespace(x=cenario.x, f1=cenario.f1, f2=cenario.f2, g1=cenario.g1, g2=cenario.g2)
    m.operador = fabrica_pessoa('Operadora Sintetica')
    conceder_direto(m.operador, cenario.cargos_x['administrador'], cenario.x)
    m.intrusa = fabrica_pessoa('Intrusa de Y')
    conceder_direto(m.intrusa, cenario.cargos_y['administrador'], cenario.y)
    m.sem_permissao = fabrica_pessoa('Sem Permissao')
    m.tema = Tema.objects.create(empresa=cenario.x, nome='Solo')
    m.estudo = Estudo.objects.create(empresa=cenario.x, fazenda=cenario.f1, tema=m.tema, nome='Estudo F1')
    return m


def _pontos(obs='sintetico'):
    return geojson([
        {'type': 'Feature', 'properties': {'valor': 0, 'obs': obs}, 'geometry': {'type': 'Point', 'coordinates': [-48.3, -10.7]}},
        {'type': 'Feature', 'properties': {'valor': None, 'obs': None}, 'geometry': {'type': 'Point', 'coordinates': [-48.29, -10.69]}},
    ])


def _cabecalho(pessoa):
    return {'Authorization': f'Bearer {sessao.emitir_acesso(pessoa, "teste")}'}


def _subir(pessoa, fazenda_id, dados, nome='camada.geojson'):
    arquivo = SimpleUploadedFile(nome, dados, content_type='application/geo+json')
    return Client().post(f'/api/v1/fazendas/{fazenda_id}/envios', data={'arquivo': arquivo}, headers=_cabecalho(pessoa))


def _ler(pessoa, caminho):
    return Client().get(f'/api/v1/{caminho}', headers=_cabecalho(pessoa))


def _publicar(pessoa, envio_id, **corpo):
    dados = {'estudo_id': corpo.pop('estudo_id'), 'metadados': METADADOS, 'nos': [], 'sistema_confirmado': True, **corpo}
    return Client().post(f'/api/v1/envios/{envio_id}/publicar', data=json.dumps(dados), content_type='application/json',
                         headers=_cabecalho(pessoa))


def _envio_do_operador(mundo, dados=None):
    resposta = _subir(mundo.operador, mundo.f1.pk, dados if dados is not None else _pontos())
    assert resposta.status_code == 201, resposta.content
    return resposta.json()['envio_id']


def _feliz(mundo, obs='sintetico', ocultos=(), nos=None):
    envio_id = _envio_do_operador(mundo, _pontos(obs))
    nos = nos if nos is not None else [mundo.g1.pk, mundo.g1.pk]
    resposta = _publicar(mundo.operador, envio_id, estudo_id=mundo.estudo.pk, ocultos=list(ocultos), nos=nos)
    assert resposta.status_code == 201, resposta.content
    return resposta.json()


# --- caminho feliz ---------------------------------------------------------------------------------------------------

def test_feliz_envia_le_previa_publica_lista_e_le_feicoes(camadas, mundo):
    envio_id = _envio_do_operador(mundo)
    previa = _ler(mundo.operador, f'envios/{envio_id}')
    assert previa.status_code == 200
    assert previa.json()['colunas'] == ['valor', 'obs']
    assert previa.json()['transformacao'] == 'equivalencia'  # WGS84 assumido: a prévia diz (R4)
    publicada = _publicar(mundo.operador, envio_id, estudo_id=mundo.estudo.pk, nos=[mundo.g1.pk, mundo.g1.pk])
    assert publicada.status_code == 201, publicada.content
    camada_id = publicada.json()['camada_id']
    lista = _ler(mundo.operador, f'fazendas/{mundo.f1.pk}/camadas')
    assert [i['camada_id'] for i in lista.json()['itens']] == [camada_id]
    feicoes = _ler(mundo.operador, f'camadas/{camada_id}/versoes/1/feicoes')
    assert feicoes.status_code == 200
    assert len(feicoes.json()['itens']) == 2
    assert feicoes.json()['itens'][0]['valores'] == {'obs': 'sintetico', 'valor': 0}
    assert [i['indice'] for i in feicoes.json()['itens']] == [1, 2]  # ordinal na versão, sem a pk (T3.8)
    assert all('id' not in item for item in feicoes.json()['itens'])
    # Segunda versão da mesma camada: as pks já passam de 2, então o ordinal e a pk não se confundem (T3.8).
    camada = Camada.objects.get(publico_id=camada_id)
    segunda = _publicar(mundo.operador, _envio_do_operador(mundo), estudo_id=mundo.estudo.pk, camada_id=camada.pk,
                        nos=[mundo.g1.pk, mundo.g1.pk])
    assert segunda.status_code == 201, segunda.content
    v2 = _ler(mundo.operador, f'camadas/{camada_id}/versoes/2/feicoes').json()
    assert [i['indice'] for i in v2['itens']] == [1, 2]
    pks = list(Feicao.objects.filter(versao__camada=camada, versao__numero=2).order_by('id').values_list('id', flat=True))
    assert pks[0] > 2


# --- 404 idêntico (R11) ------------------------------------------------------------------------------------------------

def test_outra_empresa_e_inexistente_recebem_o_mesmo_404(camadas, mundo):
    envio_id = _envio_do_operador(mundo)
    de_outra_empresa = _ler(mundo.intrusa, f'envios/{envio_id}')
    inexistente = _ler(mundo.intrusa, f'envios/{uuid4()}')
    assert de_outra_empresa.status_code == inexistente.status_code == 404
    assert de_outra_empresa.json() == inexistente.json() == NAO_ENCONTRADO


def test_sem_permissao_recebe_o_mesmo_404_que_inexistente(camadas, mundo):
    envio_id = _envio_do_operador(mundo)
    sem = _ler(mundo.sem_permissao, f'envios/{envio_id}')
    assert sem.status_code == 404 and sem.json() == NAO_ENCONTRADO
    lista = _ler(mundo.sem_permissao, f'fazendas/{mundo.f1.pk}/camadas')
    assert lista.status_code == 404 and lista.json() == NAO_ENCONTRADO
    fazenda_inexistente = _ler(mundo.operador, 'fazendas/999999/camadas')
    assert fazenda_inexistente.json() == NAO_ENCONTRADO


def test_sem_credencial_recebe_401(camadas, mundo):
    assert Client().get(f'/api/v1/envios/{uuid4()}').status_code == 401


def test_publicar_envio_de_outra_empresa_responde_404(camadas, mundo):
    envio_id = _envio_do_operador(mundo)
    resposta = _publicar(mundo.intrusa, envio_id, estudo_id=mundo.estudo.pk, nos=[mundo.g1.pk, mundo.g1.pk])
    assert resposta.status_code == 404 and resposta.json() == NAO_ENCONTRADO
    assert not VersaoCamada.objects.exists()


# --- atributo oculto (R9) ----------------------------------------------------------------------------------------------

def test_coluna_oculta_fica_fora_da_resposta_do_filtro_e_da_busca(camadas, mundo):
    publicada = _feliz(mundo, obs='segredo sintetico', ocultos=['obs'])
    camada_id = publicada['camada_id']
    feicoes = _ler(mundo.operador, f'camadas/{camada_id}/versoes/1/feicoes').json()
    assert all('obs' not in item['valores'] for item in feicoes['itens'])
    assert 'segredo sintetico' not in json.dumps(feicoes)  # o valor não sai nem sem a coluna no esquema
    filtro = _ler(mundo.operador, f'camadas/{camada_id}/versoes/1/feicoes?coluna=obs&valor=segredo%20sintetico')
    assert filtro.status_code == 422
    busca = _ler(mundo.operador, f'camadas/{camada_id}/versoes/1/feicoes?busca=segredo')
    assert busca.status_code == 200 and busca.json()['itens'] == []  # a busca não alcança a coluna oculta


def test_filtro_por_coluna_visivel_funciona(camadas, mundo):
    camada_id = _feliz(mundo)['camada_id']
    resposta = _ler(mundo.operador, f'camadas/{camada_id}/versoes/1/feicoes?coluna=valor&valor=0')
    assert resposta.status_code == 200
    assert [item['valores']['valor'] for item in resposta.json()['itens']] == [0]


# --- escape e limite --------------------------------------------------------------------------------------------------

def test_texto_com_marcacao_sai_como_texto_no_json(camadas, mundo):
    camada_id = _feliz(mundo, obs='<b>x</b>')['camada_id']
    resposta = _ler(mundo.operador, f'camadas/{camada_id}/versoes/1/feicoes')
    assert resposta['Content-Type'].startswith('application/json')
    assert resposta.json()['itens'][0]['valores']['obs'] == '<b>x</b>'  # valor literal, dentro de string JSON


def test_paginacao_respeita_o_limite_maximo(camadas, mundo):
    camada_id = _feliz(mundo)['camada_id']
    assert _ler(mundo.operador, f'camadas/{camada_id}/versoes/1/feicoes?limite=101').status_code == 422
    pagina = _ler(mundo.operador, f'camadas/{camada_id}/versoes/1/feicoes?limite=1&deslocamento=1').json()
    assert len(pagina['itens']) == 1 and pagina['deslocamento'] == 1
    assert pagina['itens'][0]['indice'] == 2  # a segunda feição, com o mesmo ordinal de sempre


# --- envio recusado (R16, R14) -----------------------------------------------------------------------------------------

def test_arquivo_acima_do_limite_e_recusado_sem_arquivo_nem_linha(camadas, mundo, monkeypatch):
    from catalogo import api
    monkeypatch.setattr(api, 'LIMITES_PADRAO', Limites(tamanho_bytes=10))
    antes = EnvioCamada.objects.count()
    resposta = _subir(mundo.operador, mundo.f1.pk, _pontos())
    assert resposta.status_code == 422
    assert resposta.json() == {'detalhe': 'recusado', 'erros': [MENSAGEM_TAMANHO]}
    assert EnvioCamada.objects.count() == antes
    assert list(camadas.iterdir()) == []


def test_kml_hostil_e_recusado_ponta_a_ponta_sem_caminho_interno(camadas, mundo):
    hostil = b'<!DOCTYPE kml [<!ENTITY e SYSTEM "file:///etc/passwd">]><kml><Document/></kml>'
    antes = EnvioCamada.objects.count()
    resposta = _subir(mundo.operador, mundo.f1.pk, hostil, nome='hostil.kml')
    assert resposta.status_code == 422
    texto = resposta.content.decode()
    assert '/etc/passwd' not in texto and str(camadas) not in texto
    assert EnvioCamada.objects.count() == antes
    assert list(camadas.iterdir()) == []


def test_publicacao_recusada_responde_422_com_a_lista_de_erros(camadas, mundo):
    envio_id = _envio_do_operador(mundo)
    resposta = _publicar(mundo.operador, envio_id, estudo_id=mundo.estudo.pk, nos=[mundo.g1.pk, mundo.g1.pk],
                         metadados={'nome': 'Camada sintetica', 'tema': 'Outro', 'origem': 'x'})
    assert resposta.status_code == 422
    assert resposta.json()['erros'] == ['tema do arquivo diferente do tema do estudo']
    assert not VersaoCamada.objects.exists()


def test_envio_pelo_navegador_exige_o_token_csrf(camadas, mundo):
    # Sessão de navegador (cookie) com CSRF conferido: POST sem token é 403; com o token do cookie, 201.
    senha_texto = 'uma senha longa e unica 2026'
    senha.definir_senha(mundo.operador, senha_texto)
    entrada = Client().post('/api/v1/entrar', data=json.dumps({'cpf': modulo_cpf.decifrar(mundo.operador.cpf_cifrado), 'senha': senha_texto}),
                            content_type='application/json')
    assert entrada.status_code == 200
    navegador = Client(enforce_csrf_checks=True)
    navegador.cookies.update(entrada.cookies)
    arquivo = lambda: SimpleUploadedFile('camada.geojson', _pontos(), content_type='application/geo+json')
    url = f'/api/v1/fazendas/{mundo.f1.pk}/envios'
    assert navegador.post(url, data={'arquivo': arquivo()}).status_code == 403
    token = navegador.cookies['csrftoken'].value
    aceito = navegador.post(url, data={'arquivo': arquivo()}, headers={'X-CSRFToken': token})
    assert aceito.status_code == 201, aceito.content
    assert EnvioCamada.objects.count() == 1


def test_corpo_nao_arquivo_acima_de_data_upload_max_memory_size_e_recusado_pelo_django(settings):
    corpo = json.dumps({'cpf': '52998224725', 'senha': 'x' * (settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1)})
    resposta = Client().post('/api/v1/entrar', data=corpo, content_type='application/json')
    assert resposta.status_code == 400  # RequestDataTooBig: o Django recusa o corpo bruto antes da rota


def test_arquivo_acima_de_data_upload_max_memory_size_nao_e_recusado_por_ele(camadas, mundo, settings):
    # DATA_UPLOAD_MAX_MEMORY_SIZE não conta dado de arquivo em request.POST: o envio passa e o tipo é que recusa (422, não 400).
    resposta = _subir(mundo.operador, mundo.f1.pk, b'x' * (settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1), nome='grande.bin')
    assert resposta.status_code == 422
    assert resposta.json()['erros'] == ['tipo de arquivo não suportado']
