"""Leitor do Cloud Monitoring (004b T3.1, R14): soma de tiles 2D, paginação, erro nunca vira zero, segredo nunca vaza."""

import base64
import json
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from projeto.monitoramento_google import CloudMonitoring, ErroDoMonitoramento
from projeto.uso_google import PACIFICO

INICIO = datetime(2026, 11, 6, tzinfo=PACIFICO)  # meia-noite do Pacífico = 08:00 UTC
UMA_HORA = INICIO + timedelta(hours=1)
MARCA_DO_TOKEN = 'marca-sintetica-que-nao-pode-vazar'


CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
EMAIL = 'leitura@projeto-sintetico.iam.gserviceaccount.com'


@pytest.fixture(scope='module')
def pem():
    return CHAVE.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


@pytest.fixture
def credencial(tmp_path, pem):
    caminho = tmp_path / 'chave.json'
    caminho.write_text(json.dumps({'client_email': EMAIL, 'private_key': pem, 'project_id': 'projeto-sintetico'}))
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
        self.respostas = list(respostas) if respostas is not None else [[_ponto(7)]]
        self.urls = []
        self.cabecalhos = []
        self.prazos = []
        self.tokens = 0

    def __call__(self, pedido, timeout=None):
        url = pedido.full_url
        self.prazos.append(timeout)
        if url.startswith('https://oauth2.googleapis.com/token'):
            self.tokens += 1
            _confere_pedido_de_token(pedido)
            return Resposta({'access_token': MARCA_DO_TOKEN, 'expires_in': 3600})
        self.urls.append(url)
        self.cabecalhos.append(pedido.get_header('Authorization'))
        resposta = self.respostas.pop(0) if self.respostas else []
        pontos, pagina = resposta if isinstance(resposta, tuple) else (resposta, None)
        corpo = {'timeSeries': [{'points': pontos}] if pontos else []}
        if pagina:
            corpo['nextPageToken'] = pagina
        return Resposta(corpo)


def _confere_pedido_de_token(pedido):
    """Valida o que o Google validaria: grant_type, audiência, escopo, emissor e a assinatura RS256 com a chave pública."""
    campos = urllib.parse.parse_qs(pedido.data.decode())
    assert campos['grant_type'] == ['urn:ietf:params:oauth:grant-type:jwt-bearer']
    cabecalho, corpo, assinatura = campos['assertion'][0].split('.')

    def decodificar(parte):
        return base64.urlsafe_b64decode(parte + '=' * (-len(parte) % 4))

    reivindicacoes = json.loads(decodificar(corpo))
    assert reivindicacoes['aud'] == 'https://oauth2.googleapis.com/token'
    assert reivindicacoes['scope'] == 'https://www.googleapis.com/auth/monitoring.read'
    assert reivindicacoes['iss'] == EMAIL
    assert json.loads(decodificar(cabecalho))['alg'] == 'RS256'
    CHAVE.public_key().verify(decodificar(assinatura), f'{cabecalho}.{corpo}'.encode(), padding.PKCS1v15(), hashes.SHA256())


def _ponto(valor):
    return {'value': {'int64Value': str(valor)}}


def _leitor(credencial, google, **extra):
    return CloudMonitoring(credencial, abrir=google, relogio=lambda: 1_000_000, **extra)


def test_soma_os_pontos_das_horas_cheias_e_da_hora_corrente(credencial):
    google = FalsoGoogle([[_ponto(40), _ponto(2)], [_ponto(5)]])
    assert _leitor(credencial, google).contar(INICIO, INICIO + timedelta(hours=3, minutes=20)) == 47
    assert len(google.urls) == 2  # horas cheias + a hora corrente, minuto a minuto


def test_consulta_so_o_tile_2d_do_servico_de_tiles_no_projeto_da_chave(credencial):
    google = FalsoGoogle()
    _leitor(credencial, google).contar(INICIO, UMA_HORA)
    assert 'tile.googleapis.com%2Ftwodtiles' in google.urls[0]
    assert 'service%3D%22tile.googleapis.com' in google.urls[0]
    assert 'projects/projeto-sintetico/timeSeries' in google.urls[0]


def test_horas_cheias_usam_periodo_de_uma_hora_e_a_corrente_de_um_minuto(credencial):
    google = FalsoGoogle([[], []])
    _leitor(credencial, google).contar(INICIO, INICIO + timedelta(hours=2, minutes=5))
    assert 'alignmentPeriod=3600s' in google.urls[0]
    assert 'alignmentPeriod=60s' in google.urls[1]


def test_intervalos_vao_em_utc_e_a_meia_noite_do_pacifico_e_08h_utc(credencial):
    google = FalsoGoogle()
    _leitor(credencial, google).contar(INICIO, INICIO + timedelta(hours=2))
    assert 'interval.startTime=2026-11-06T08%3A00%3A00Z' in google.urls[0]
    assert 'interval.endTime=2026-11-06T10%3A00%3A00Z' in google.urls[0]


def test_sem_nenhum_ponto_e_nao_medido_nunca_zero(credencial):
    assert _leitor(credencial, FalsoGoogle([[]])).contar(INICIO, UMA_HORA) is None


def test_ponto_com_valor_zero_e_zero_medido(credencial):
    assert _leitor(credencial, FalsoGoogle([[_ponto(0)]])).contar(INICIO, UMA_HORA) == 0


def test_so_a_hora_corrente_com_pontos_soma_ela_e_ignora_a_janela_vazia(credencial):
    google = FalsoGoogle([[], [_ponto(4)]])
    assert _leitor(credencial, google).contar(INICIO, INICIO + timedelta(hours=1, minutes=5)) == 4


def test_resposta_parcial_do_google_e_erro_sem_somar_os_pontos(credencial):
    class Parcial(FalsoGoogle):
        def __call__(self, pedido, timeout=None):
            resposta = super().__call__(pedido, timeout)
            if 'timeSeries' in pedido.full_url:
                corpo = json.loads(resposta.read())
                corpo['executionErrors'] = [{'code': 14, 'message': 'indisponível'}]
                return Resposta(corpo)
            return resposta

    leitor = _leitor(credencial, Parcial([[_ponto(7)]]))
    with pytest.raises(ErroDoMonitoramento, match='parcial'):
        leitor.contar(INICIO, UMA_HORA)


def test_paginacao_soma_todas_as_paginas(credencial):
    google = FalsoGoogle([([_ponto(10)], 'p2'), [_ponto(5)]])
    assert _leitor(credencial, google).contar(INICIO, UMA_HORA) == 15
    assert 'pageToken=p2' in google.urls[1]


def test_token_vai_so_no_cabecalho_e_e_reaproveitado(credencial):
    google = FalsoGoogle([[], []])
    _leitor(credencial, google).contar(INICIO, INICIO + timedelta(hours=1, minutes=5))
    assert google.cabecalhos == [f'Bearer {MARCA_DO_TOKEN}'] * 2
    assert google.tokens == 1  # dois pedidos de série, um só token
    assert sum(1 for url in google.urls if MARCA_DO_TOKEN in url) == 0


def test_erro_de_rede_ou_http_vira_excecao_com_o_codigo(credencial):
    def quebra(pedido, timeout=None):
        if pedido.full_url.startswith('https://oauth2'):
            return Resposta({'access_token': MARCA_DO_TOKEN, 'expires_in': 3600})
        raise urllib.error.HTTPError(pedido.full_url, 403, f'corpo com {MARCA_DO_TOKEN}', {}, None)  # type: ignore[arg-type]

    leitor = CloudMonitoring(credencial, abrir=quebra, relogio=lambda: 1_000_000)
    with pytest.raises(ErroDoMonitoramento, match='403'):
        leitor.contar(INICIO, UMA_HORA)


def test_erro_http_nao_vaza_o_corpo_da_resposta(credencial):
    def quebra(pedido, timeout=None):
        if pedido.full_url.startswith('https://oauth2'):
            return Resposta({'access_token': MARCA_DO_TOKEN, 'expires_in': 3600})
        raise urllib.error.HTTPError(pedido.full_url, 403, f'corpo com {MARCA_DO_TOKEN}', {}, None)  # type: ignore[arg-type]

    leitor = CloudMonitoring(credencial, abrir=quebra, relogio=lambda: 1_000_000)
    with pytest.raises(ErroDoMonitoramento) as erro:
        leitor.contar(INICIO, UMA_HORA)
    assert MARCA_DO_TOKEN not in str(erro.value)


@pytest.mark.parametrize('conteudo', ['não é json', '{}', '{"client_email": "x"}'])
def test_credencial_ilegivel_ou_incompleta_da_erro_claro(tmp_path, conteudo):
    caminho = tmp_path / 'ruim.json'
    caminho.write_text(conteudo)
    leitor = CloudMonitoring(str(caminho), abrir=FalsoGoogle())
    with pytest.raises(ErroDoMonitoramento, match='credencial'):
        leitor.contar(INICIO, UMA_HORA)


def test_credencial_inexistente_da_erro_claro(tmp_path):
    leitor = CloudMonitoring(str(tmp_path / 'nao-existe.json'), abrir=FalsoGoogle())
    with pytest.raises(ErroDoMonitoramento, match='credencial'):
        leitor.contar(INICIO, UMA_HORA)


def test_chave_privada_invalida_da_erro_claro(tmp_path):
    caminho = tmp_path / 'chave.json'
    caminho.write_text(json.dumps({'client_email': 'x@y', 'private_key': 'não é pem', 'project_id': 'p'}))
    leitor = CloudMonitoring(str(caminho), abrir=FalsoGoogle())
    with pytest.raises(ErroDoMonitoramento, match='chave privada'):
        leitor.contar(INICIO, UMA_HORA)


def test_janela_menor_que_uma_hora_so_consulta_a_parte_minuto_a_minuto(credencial):
    google = FalsoGoogle([[_ponto(3)]])
    assert _leitor(credencial, google).contar(INICIO, INICIO + timedelta(minutes=20)) == 3
    assert len(google.urls) == 1
    assert 'alignmentPeriod=60s' in google.urls[0]


def test_fim_em_utc_e_pacifico_dao_a_mesma_soma(credencial):
    google = FalsoGoogle([[_ponto(9)]])
    assert _leitor(credencial, google).contar(INICIO, UMA_HORA.astimezone(timezone.utc)) == 9


@pytest.mark.parametrize('ponto', [{'value': {}}, {}, {'value': {'int64Value': 'abc'}}, {'value': {'doubleValue': 1.5}}])
def test_ponto_sem_valor_inteiro_e_erro_nunca_zero(credencial, ponto):
    leitor = _leitor(credencial, FalsoGoogle([[ponto]]))
    with pytest.raises(ErroDoMonitoramento, match='sem valor inteiro'):
        leitor.contar(INICIO, UMA_HORA)


def test_prazo_total_esgotado_interrompe_as_consultas_restantes(credencial):
    relogio = iter([0, 5, 25, 25, 25])  # criação, 1º pedido (token), 2º pedido já passou de 20 s
    google = FalsoGoogle([[_ponto(1)], [_ponto(1)]])
    leitor = CloudMonitoring(credencial, abrir=google, relogio=lambda: 1_000_000, monotonico=lambda: next(relogio))
    with pytest.raises(ErroDoMonitoramento, match='prazo total'):
        leitor.contar(INICIO, INICIO + timedelta(hours=2, minutes=5))
    assert len(google.urls) == 0  # nenhuma consulta de série depois do prazo


def test_cada_pedido_leva_so_o_tempo_que_resta_do_prazo_total(credencial):
    relogio = iter([0, 1, 2])  # criação, pedido do token (sobram 19 s), pedido da série (sobram 18 s)
    google = FalsoGoogle([[_ponto(1)]])
    leitor = CloudMonitoring(credencial, abrir=google, relogio=lambda: 1_000_000, monotonico=lambda: next(relogio), prazo_total_s=20)
    leitor.contar(INICIO, UMA_HORA)
    assert google.prazos == [19, 18]
    assert max(google.prazos) <= 20


def test_projeto_monitorado_explicito_vence_o_da_chave(credencial):
    google = FalsoGoogle()
    _leitor(credencial, google, projeto='projeto-cobrado').contar(INICIO, UMA_HORA)
    assert 'projects/projeto-cobrado/timeSeries' in google.urls[0]
    assert 'projeto-sintetico' not in google.urls[0]


@pytest.mark.parametrize('vazio', [None, ''])
def test_sem_projeto_monitorado_usa_o_da_chave(credencial, vazio):
    google = FalsoGoogle()
    _leitor(credencial, google, projeto=vazio).contar(INICIO, UMA_HORA)
    assert 'projects/projeto-sintetico/timeSeries' in google.urls[0]


def test_projeto_monitorado_com_caracteres_estranhos_e_escapado_na_url(credencial):
    google = FalsoGoogle()
    _leitor(credencial, google, projeto='x/../outro?a=b').contar(INICIO, UMA_HORA)
    assert 'projects/x%2F..%2Foutro%3Fa%3Db/timeSeries' in google.urls[0]
