"""API do catálogo pela URL real (008 T3.2; R9, R11, R14, R15, R16, R21): envio, prévia, publicação, leitura paginada.

Caminho feliz e infeliz: 404 idêntico (outra empresa x inexistente x sem permissão), 401 sem credencial, coluna oculta
fora da resposta, do filtro e da busca, texto com marcação escapado, limite de página, arquivo acima do limite, KML
hostil. Dado sintético (R17)."""

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from catalogo.ingestao import Limites, MENSAGEM_TAMANHO
from catalogo.models import AtributoVersao, Camada, EnvioCamada, Estudo, Feicao, Tema, VersaoCamada
from catalogo.testes.test_ingestao import geojson
from identidade import cpf as modulo_cpf
from projeto.ficha import CAMPOS, SEM_INFORMACAO
from identidade import senha, sessao
from permissao.cargos_base import criar_cargos_base
from permissao.models import Cargo, CargoPermissao

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
    # Só ids devolvidos pela API: o id público da camada, nunca a pk.
    segunda = _publicar(mundo.operador, _envio_do_operador(mundo), estudo_id=mundo.estudo.pk, camada_id=camada_id,
                        nos=[mundo.g1.pk, mundo.g1.pk])
    assert segunda.status_code == 201, segunda.content
    assert segunda.json()['versao'] == 2
    v2 = _ler(mundo.operador, f'camadas/{camada_id}/versoes/2/feicoes').json()
    assert [i['indice'] for i in v2['itens']] == [1, 2]
    pks = list(Feicao.objects.filter(versao__camada__publico_id=camada_id, versao__numero=2).order_by('id').values_list('id', flat=True))
    assert pks[0] > 2


# --- geometria da prévia para o mapa (R12) -----------------------------------------------------------------------------

def _geometria(pessoa, envio_id, consulta=''):
    return _ler(pessoa, f'envios/{envio_id}/geometria{consulta}')


def _vencer(envio_id):
    EnvioCamada.objects.filter(publico_id=envio_id).update(expira_em=timezone.now() - timedelta(minutes=1))


def test_geometria_feliz_devolve_feicoes_em_4326_com_total_e_sem_truncado(camadas, mundo):
    envio_id = _envio_do_operador(mundo)
    resposta = _geometria(mundo.operador, envio_id)
    corpo = resposta.json()
    assert resposta.status_code == 200
    assert corpo['type'] == 'FeatureCollection'  # GeoJSON: `type`, não `tipo`
    assert corpo['limite'] == 500
    assert corpo['total'] == 2
    assert corpo['truncado'] is False
    assert [f['properties']['indice'] for f in corpo['features']] == [1, 2]
    # Contrato do mapa.js: `camada_id` string (o id público do envio) e `cor` string; sem isso o mapa recusa a coleção.
    assert all(f['properties']['camada_id'] == envio_id for f in corpo['features'])
    assert all(f['properties']['camada'] == 'Prévia do envio (em análise)' for f in corpo['features'])
    # `cor` é nome de variável CSS: o mapa.js resolve com `getPropertyValue`, e nome sem valor em camadas.css derruba o mapa.
    css = (Path(__file__).resolve().parents[2] / 'projeto' / 'static' / 'projeto' / 'camadas.css').read_text(encoding='utf-8')
    assert all(f'{f["properties"]["cor"]}:' in css for f in corpo['features'])
    # Contrato do mapa.js (`CAMPOS_DA_FICHA`): todo campo da ficha é string; o que o envio não tem vai "Sem informação".
    for feicao in corpo['features']:
        for campo in CAMPOS:
            assert isinstance(feicao['properties'][campo], str), campo
        assert feicao['properties']['fonte'] == SEM_INFORMACAO
    assert corpo['features'][0]['geometry']['type'] == 'Point'
    assert corpo['features'][0]['geometry']['coordinates'] == pytest.approx([-48.3, -10.7], abs=1e-4)


def test_geometria_com_limite_menor_que_o_total_marca_truncado(camadas, mundo):
    envio_id = _envio_do_operador(mundo)
    corpo = _geometria(mundo.operador, envio_id, '?limite=1').json()
    assert corpo['total'] == 2  # total real, não zero nem o tamanho da página
    assert corpo['truncado'] is True
    assert len(corpo['features']) == 1


@pytest.mark.parametrize('consulta', ['?limite=0', '?limite=2001'])
def test_geometria_com_limite_fora_da_faixa_e_422(camadas, mundo, consulta):
    envio_id = _envio_do_operador(mundo)
    assert _geometria(mundo.operador, envio_id, consulta).status_code == 422


def test_geometria_sem_acesso_outra_empresa_e_inexistente_recebem_o_mesmo_404(camadas, mundo):
    envio_id = _envio_do_operador(mundo)
    sem = _geometria(mundo.sem_permissao, envio_id)
    outra = _geometria(mundo.intrusa, envio_id)
    ausente = _geometria(mundo.operador, uuid4())
    assert sem.status_code == outra.status_code == ausente.status_code == 404
    assert sem.json() == outra.json() == ausente.json() == NAO_ENCONTRADO


def test_geometria_de_envio_vencido_e_404(camadas, mundo):
    envio_id = _envio_do_operador(mundo)
    _vencer(envio_id)
    resposta = _geometria(mundo.operador, envio_id)
    assert resposta.status_code == 404
    assert resposta.json() == NAO_ENCONTRADO


def test_previa_de_envio_vencido_e_recusada(camadas, mundo):
    envio_id = _envio_do_operador(mundo)
    _vencer(envio_id)
    resposta = _ler(mundo.operador, f'envios/{envio_id}')
    assert resposta.status_code == 422
    assert resposta.json()['erros'] == ['envio vencido']


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
    assert sem.status_code == 404
    assert sem.json() == NAO_ENCONTRADO
    lista = _ler(mundo.sem_permissao, f'fazendas/{mundo.f1.pk}/camadas')
    assert lista.status_code == 404
    assert lista.json() == NAO_ENCONTRADO
    fazenda_inexistente = _ler(mundo.operador, 'fazendas/999999/camadas')
    assert fazenda_inexistente.json() == NAO_ENCONTRADO


def test_sem_credencial_recebe_401(camadas, mundo):
    assert Client().get(f'/api/v1/envios/{uuid4()}').status_code == 401


def test_publicar_envio_de_outra_empresa_responde_404(camadas, mundo):
    envio_id = _envio_do_operador(mundo)
    resposta = _publicar(mundo.intrusa, envio_id, estudo_id=mundo.estudo.pk, nos=[mundo.g1.pk, mundo.g1.pk])
    assert resposta.status_code == 404
    assert resposta.json() == NAO_ENCONTRADO
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
    assert busca.status_code == 200  # a busca não alcança a coluna oculta
    assert busca.json()['itens'] == []


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
    assert len(pagina['itens']) == 1
    assert pagina['deslocamento'] == 1
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
    assert '/etc/passwd' not in texto
    assert str(camadas) not in texto
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


# --- índice estável, camada pelo id público e leitura limitada (T3.2, R9, R16) ----------------------------------------------

def test_indice_e_o_ordinal_da_versao_com_e_sem_filtro(camadas, mundo):
    features = [{'type': 'Feature', 'properties': {'valor': v}, 'geometry': {'type': 'Point', 'coordinates': [-48.3, -10.7 + i / 100]}}
                for i, v in enumerate(['a', 'b', 'a'])]
    envio_id = _envio_do_operador(mundo, geojson(features))
    publicada = _publicar(mundo.operador, envio_id, estudo_id=mundo.estudo.pk, nos=[mundo.g1.pk] * 3)
    assert publicada.status_code == 201, publicada.content
    caminho = f"camadas/{publicada.json()['camada_id']}/versoes/1/feicoes"
    sem_filtro = _ler(mundo.operador, caminho).json()['itens']
    assert [i['indice'] for i in sem_filtro] == [1, 2, 3]
    filtrado = _ler(mundo.operador, f'{caminho}?coluna=valor&valor=a').json()['itens']
    assert [i['indice'] for i in filtrado] == [1, 3]  # a terceira feição continua sendo a 3ª da versão, não a 2ª do filtro
    assert [i['valores']['valor'] for i in filtrado] == ['a', 'a']


def test_camada_de_outro_estudo_ou_inexistente_recebe_a_mesma_recusa(camadas, mundo):
    publicada = _feliz(mundo)
    outro = Estudo.objects.create(empresa=mundo.x, fazenda=mundo.f1, tema=mundo.tema, nome='Outro estudo')
    antes = VersaoCamada.objects.count()
    nos = [mundo.g1.pk, mundo.g1.pk]
    de_outro = _publicar(mundo.operador, _envio_do_operador(mundo), estudo_id=outro.pk, camada_id=publicada['camada_id'], nos=nos)
    inexistente = _publicar(mundo.operador, _envio_do_operador(mundo), estudo_id=mundo.estudo.pk, camada_id=str(uuid4()), nos=nos)
    recusa = {'detalhe': 'recusado', 'erros': ['camada não encontrada neste estudo']}
    assert de_outro.status_code == 422
    assert inexistente.status_code == 422
    assert de_outro.json() == recusa
    assert inexistente.json() == recusa  # mesma resposta: não revela se a camada existe em outro estudo
    assert VersaoCamada.objects.count() == antes


class _Arquivo:
    """Arquivo de mentira com `size` controlado: `read` guarda o tamanho pedido, para conferir que não lê além do limite."""

    def __init__(self, dados, size):
        self._dados = dados
        self.size = size
        self.pedidos = []

    def read(self, tamanho=-1):
        self.pedidos.append(tamanho)
        return self._dados[:tamanho] if tamanho >= 0 else self._dados


def test_ler_limitado_aceita_no_limite_e_recusa_um_byte_a_mais(monkeypatch):
    from catalogo import api
    monkeypatch.setattr(api, 'LIMITES_PADRAO', Limites(tamanho_bytes=10))
    assert api._ler_limitado(_Arquivo(b'0123456789', 10)) == b'0123456789'
    assert api._ler_limitado(_Arquivo(b'01234567890', 11)) is None


def test_ler_limitado_com_tamanho_desconhecido_nao_presume_e_recusa_acima_do_limite(monkeypatch):
    from catalogo import api
    monkeypatch.setattr(api, 'LIMITES_PADRAO', Limites(tamanho_bytes=10))
    dentro = _Arquivo(b'0123456789', None)
    assert api._ler_limitado(dentro) == b'0123456789'
    assert dentro.pedidos == [11]  # lê no máximo limite+1 bytes
    acima = _Arquivo(b'01234567890123', None)
    assert api._ler_limitado(acima) is None
    assert acima.pedidos == [11]  # não lê o arquivo inteiro para descobrir que passou


def test_ler_limitado_com_tamanho_conhecido_acima_do_limite_nao_le(monkeypatch):
    from catalogo import api
    monkeypatch.setattr(api, 'LIMITES_PADRAO', Limites(tamanho_bytes=10))
    arquivo = _Arquivo(b'x' * 50, 50)
    assert api._ler_limitado(arquivo) is None
    assert arquivo.pedidos == []  # recusa pelo tamanho antes de ler


def test_coluna_com_nome_numerico_filtra_e_entra_na_busca(camadas, mundo):
    # Regressão (achado Codex, P2): nome numérico não pode virar índice de array no filtro nem na busca.
    features = [
        {'type': 'Feature', 'properties': {'2026': 7, 'valor': 'a'}, 'geometry': {'type': 'Point', 'coordinates': [-48.3, -10.7]}},
        {'type': 'Feature', 'properties': {'2026': 8, 'valor': 'b'}, 'geometry': {'type': 'Point', 'coordinates': [-48.29, -10.69]}},
    ]
    envio_id = _envio_do_operador(mundo, geojson(features))
    publicada = _publicar(mundo.operador, envio_id, estudo_id=mundo.estudo.pk, nos=[mundo.g1.pk, mundo.g1.pk])
    assert publicada.status_code == 201, publicada.content
    caminho = f"camadas/{publicada.json()['camada_id']}/versoes/1/feicoes"
    filtrado = _ler(mundo.operador, f'{caminho}?coluna=2026&valor=7').json()['itens']
    assert [i['valores']['2026'] for i in filtrado] == [7]
    busca = _ler(mundo.operador, f'{caminho}?busca=8').json()['itens']
    assert [i['valores']['2026'] for i in busca] == [8]


# --- leitura de feição por nó (plan.md:63, R11; decisão do mantenedor): ver no nó lê só as feições do nó ----------------------

def _camada_com_feicoes_por_no(mundo, cenario):
    from django.contrib.gis.geos import GEOSGeometry  # noqa: PLC0415 (import local: só esta fixture usa geometria)
    camada = Camada.objects.create(estudo=mundo.estudo, empresa=cenario.x, fazenda=cenario.f1, nome='Camada por nó')
    versao = VersaoCamada.objects.create(camada=camada, empresa=cenario.x, fazenda=cenario.f1, numero=1,
                                         sistema_original='WGS 84', origem='Sintético', enviada_por=mundo.operador)
    quadrado = 'POLYGON((-48.3 -10.7, -48.29 -10.7, -48.29 -10.69, -48.3 -10.69, -48.3 -10.7))'
    AtributoVersao.objects.create(versao=versao, empresa=cenario.x, fazenda=cenario.f1, nome='no')  # coluna visível: a resposta traz o valor
    for no in (cenario.g1, cenario.g2, None):
        Feicao.objects.create(versao=versao, empresa=cenario.x, fazenda=cenario.f1, sub_area=no,
                              geometria=GEOSGeometry(quadrado, srid=4674), valores={'no': no.nome if no else 'fazenda'})
    return camada


def test_no_com_ver_le_so_as_feicoes_do_proprio_no(camadas, mundo, cenario, fabrica_pessoa, conceder_direto):
    camada = _camada_com_feicoes_por_no(mundo, cenario)
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Ver no G1', base='usuario')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='ver')
    so_g1 = fabrica_pessoa('So G1')
    conceder_direto(so_g1, cargo, cenario.g1)
    resposta = _ler(so_g1, f'camadas/{camada.publico_id}/versoes/1/feicoes')
    assert resposta.status_code == 200
    itens = resposta.json()['itens']
    assert [i['valores']['no'] for i in itens] == ['G1']  # nem G2 nem a da fazenda (nó None)
    assert itens[0]['indice'] == 1  # o ordinal conta só o que a pessoa lê: não vaza a posição das outras
    # Os valores de nó de outras feições não aparecem em nenhum lugar da resposta.
    assert 'G2' not in resposta.content.decode() and 'fazenda' not in resposta.content.decode()


def test_admin_da_fazenda_le_todas_as_feicoes_inclusive_da_fazenda(camadas, mundo, cenario):
    camada = _camada_com_feicoes_por_no(mundo, cenario)
    itens = _ler(mundo.operador, f'camadas/{camada.publico_id}/versoes/1/feicoes').json()['itens']
    assert sorted(i['valores']['no'] for i in itens) == ['G1', 'G2', 'fazenda']


def test_sem_nenhum_ver_na_camada_e_404_igual_a_inexistente(camadas, mundo, cenario, fabrica_pessoa):
    camada = _camada_com_feicoes_por_no(mundo, cenario)
    sem = fabrica_pessoa('Sem ver nenhum')
    de_fora = _ler(sem, f'camadas/{camada.publico_id}/versoes/1/feicoes')
    inexistente = _ler(sem, f'camadas/{uuid4()}/versoes/1/feicoes')
    assert de_fora.status_code == inexistente.status_code == 404
    assert de_fora.json() == inexistente.json() == NAO_ENCONTRADO
