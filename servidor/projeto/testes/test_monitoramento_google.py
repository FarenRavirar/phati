"""Leitor do Cloud Monitoring (004b T3.1, R14): soma de tiles 2D, paginação, erro nunca vira zero, segredo nunca vaza."""

import json
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from projeto.monitoramento_google import CloudMonitoring, ErroDoMonitoramento
from projeto.uso_google import PACIFICO

INICIO = datetime(2026, 11, 6, tzinfo=PACIFICO)  # meia-noite do Pacífico = 08:00 UTC
MARCA_DO_TOKEN = 'marca-sintetica-que-nao-pode-vazar'


@pytest.fixture(scope='module')
def pem():
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


@pytest.fixture
def credencial(tmp_path, pem):
    caminho = tmp_path / 'chave.json'
    caminho.write_text(json.dumps({'client_email': 'leitura@projeto-sintetico.iam.gserviceaccount.com', 'private_key': pem, 'project_id': 'projeto-sintetico'}))
    return str(caminho)


class Resposta:
    def __init__(self, corpo):
        self._corpo = json.dumps(corpo).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return self._corpo


class FalsoGoogle:
    """Responde ao token e às consultas de timeSeries (uma resposta por consulta); guarda o que foi pedido.
    Cada resposta é uma lista de pontos ou `(pontos, token_da_proxima_pagina)`."""

    def __init__(self, respostas=None):
        self.respostas = list(respostas) if respostas is not None else [[{'value': {'int64Value': '7'}}]]
        self.urls = []
        self.cabecalhos = []

    def __call__(self, pedido, timeout=None):
        url = pedido.full_url
        if url.startswith('https://oauth2.googleapis.com/token'):
            return Resposta({'access_token': MARCA_DO_TOKEN, 'expires_in': 3600})
        self.urls.append(url)
        self.cabecalhos.append(pedido.get_header('Authorization'))
        resposta = self.respostas.pop(0) if self.respostas else []
        pontos, pagina = resposta if isinstance(resposta, tuple) else (resposta, None)
        corpo = {'timeSeries': [{'points': pontos}] if pontos else []}
        if pagina:
            corpo['nextPageToken'] = pagina
        return Resposta(corpo)


def _leitor(credencial, google):
    return CloudMonitoring(credencial, abrir=google, relogio=lambda: 1_000_000)


def _ponto(valor):
    return {'value': {'int64Value': str(valor)}}


def test_soma_os_pontos_e_consulta_so_o_tile_2d_do_servico_de_tiles(credencial):
    google = FalsoGoogle([[_ponto(40), _ponto(2)], [_ponto(5)]])
    total = _leitor(credencial, google).contar(INICIO, INICIO + timedelta(hours=3, minutes=20))
    assert total == 47
    assert len(google.urls) == 2  # horas cheias + a hora corrente, minuto a minuto
    assert 'tile.googleapis.com%2Ftwodtiles' in google.urls[0] and 'service%3D%22tile.googleapis.com' in google.urls[0]
    assert 'projects/projeto-sintetico/timeSeries' in google.urls[0]
    assert 'alignmentPeriod=3600s' in google.urls[0] and 'alignmentPeriod=60s' in google.urls[1]


def test_intervalos_vao_em_utc_e_a_meia_noite_do_pacifico_e_08h_utc(credencial):
    google = FalsoGoogle()
    _leitor(credencial, google).contar(INICIO, INICIO + timedelta(hours=2))
    assert 'interval.startTime=2026-11-06T08%3A00%3A00Z' in google.urls[0]
    assert 'interval.endTime=2026-11-06T10%3A00%3A00Z' in google.urls[0]


def test_sem_serie_e_zero_medido_so_com_resposta_200(credencial):
    assert _leitor(credencial, FalsoGoogle([[]])).contar(INICIO, INICIO + timedelta(hours=1)) == 0


def test_paginacao_soma_todas_as_paginas(credencial):
    google = FalsoGoogle([([_ponto(10)], 'p2'), [_ponto(5)]])
    assert _leitor(credencial, google).contar(INICIO, INICIO + timedelta(hours=1)) == 15
    assert 'pageToken=p2' in google.urls[1]


def test_token_vai_so_no_cabecalho_e_e_reaproveitado(credencial):
    google = FalsoGoogle([[], []])
    _leitor(credencial, google).contar(INICIO, INICIO + timedelta(hours=1, minutes=5))
    assert google.cabecalhos == [f'Bearer {MARCA_DO_TOKEN}'] * 2
    assert all(MARCA_DO_TOKEN not in url for url in google.urls)


def test_erro_de_rede_ou_http_vira_excecao_sem_vazar_o_corpo(credencial):
    def quebra(pedido, timeout=None):
        if pedido.full_url.startswith('https://oauth2'):
            return Resposta({'access_token': MARCA_DO_TOKEN, 'expires_in': 3600})
        raise urllib.error.HTTPError(pedido.full_url, 403, f'corpo com {MARCA_DO_TOKEN}', {}, None)  # type: ignore[arg-type]

    with pytest.raises(ErroDoMonitoramento) as erro:
        CloudMonitoring(credencial, abrir=quebra, relogio=lambda: 1_000_000).contar(INICIO, INICIO + timedelta(hours=1))
    assert '403' in str(erro.value) and MARCA_DO_TOKEN not in str(erro.value)


@pytest.mark.parametrize('conteudo', ['não é json', '{}', '{"client_email": "x"}'])
def test_credencial_ilegivel_ou_incompleta_da_erro_claro(tmp_path, conteudo):
    caminho = tmp_path / 'ruim.json'
    caminho.write_text(conteudo)
    with pytest.raises(ErroDoMonitoramento, match='credencial'):
        CloudMonitoring(str(caminho), abrir=FalsoGoogle()).contar(INICIO, INICIO + timedelta(hours=1))


def test_credencial_inexistente_da_erro_claro(tmp_path):
    with pytest.raises(ErroDoMonitoramento, match='credencial'):
        CloudMonitoring(str(tmp_path / 'nao-existe.json'), abrir=FalsoGoogle()).contar(INICIO, INICIO + timedelta(hours=1))


def test_chave_privada_invalida_da_erro_claro(tmp_path):
    caminho = tmp_path / 'chave.json'
    caminho.write_text(json.dumps({'client_email': 'x@y', 'private_key': 'não é pem', 'project_id': 'p'}))
    with pytest.raises(ErroDoMonitoramento, match='chave privada'):
        CloudMonitoring(str(caminho), abrir=FalsoGoogle()).contar(INICIO, INICIO + timedelta(hours=1))


def test_janela_menor_que_uma_hora_so_consulta_a_parte_minuto_a_minuto(credencial):
    google = FalsoGoogle([[_ponto(3)]])
    assert _leitor(credencial, google).contar(INICIO, INICIO + timedelta(minutes=20)) == 3
    assert len(google.urls) == 1 and 'alignmentPeriod=60s' in google.urls[0]


def test_fim_em_utc_e_pacifico_dao_a_mesma_soma(credencial):
    google = FalsoGoogle([[_ponto(9)]])
    fim = (INICIO + timedelta(hours=1)).astimezone(timezone.utc)
    assert _leitor(credencial, google).contar(INICIO, fim) == 9
