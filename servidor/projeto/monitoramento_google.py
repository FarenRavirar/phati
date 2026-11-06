"""Leitor do Cloud Monitoring para o monitor de uso do Google (004b T3.1, R14).

Soma os tiles 2D cobrados do projeto: métrica `serviceruntime.googleapis.com/quota/rate/net_usage`, serviço
`tile.googleapis.com`, `quota_metric` `tile.googleapis.com/twodtiles` (medido em 2026-11-06 contra a API real; sessão e
viewport vêm em `uncharged_bucket` e não contam). Só `urllib` e `cryptography`, já no lockfile. A chave da conta de serviço
fica em arquivo fora do repositório (`PHATI_GOOGLE_MONITORING_CREDENCIAL`); aqui ela só é lida para assinar o JWT e nunca
vai a log, a exceção nem à tela.
"""

import base64
import json
import time
import urllib.parse
import urllib.request
from datetime import timedelta, timezone

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ESCOPO = 'https://www.googleapis.com/auth/monitoring.read'
URL_TOKEN = 'https://oauth2.googleapis.com/token'
METRICA = 'serviceruntime.googleapis.com/quota/rate/net_usage'
SERVICO = 'tile.googleapis.com'
QUOTA_METRIC = 'tile.googleapis.com/twodtiles'
PRAZO_S = 30
HORA = 3600


class ErroDoMonitoramento(Exception):
    """Falha ao ler o uso. A mensagem nunca leva chave nem token."""


def _b64(dados):
    return base64.urlsafe_b64encode(dados).rstrip(b'=').decode()


class CloudMonitoring:
    # Atraso de publicação de `net_usage`: até 240 s (doc do Google, 2026-11-06); a soma pode estar uns minutos defasada.
    origem = 'Cloud Monitoring do Google (tiles 2D, atraso de até 4 min)'

    def __init__(self, caminho_credencial, abrir=urllib.request.urlopen, relogio=time.time):
        self._caminho = caminho_credencial
        self._abrir = abrir
        self._relogio = relogio
        self._token = None
        self._token_expira = 0

    def _credencial(self):
        try:
            with open(self._caminho, encoding='utf-8') as arquivo:
                chave = json.load(arquivo)
            return chave['client_email'], chave['private_key'], chave['project_id']
        except (OSError, ValueError, KeyError) as erro:
            raise ErroDoMonitoramento('credencial ilegível ou incompleta') from erro

    def _acesso(self):
        agora = int(self._relogio())
        if self._token and agora < self._token_expira - 60:
            return self._token
        email, privada, _ = self._credencial()
        cabecalho = _b64(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode())
        corpo = _b64(json.dumps({'iss': email, 'scope': ESCOPO, 'aud': URL_TOKEN, 'iat': agora, 'exp': agora + 3000}).encode())
        entrada = f'{cabecalho}.{corpo}'.encode()
        try:
            chave_privada = serialization.load_pem_private_key(privada.encode(), password=None)
        except (ValueError, TypeError) as erro:
            raise ErroDoMonitoramento('chave privada inválida') from erro
        if not isinstance(chave_privada, rsa.RSAPrivateKey):
            raise ErroDoMonitoramento('chave privada inválida')
        assinatura = _b64(chave_privada.sign(entrada, padding.PKCS1v15(), hashes.SHA256()))
        dados = urllib.parse.urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': f'{entrada.decode()}.{assinatura}'}).encode()
        resposta = self._pedir(urllib.request.Request(URL_TOKEN, data=dados))
        self._token = resposta['access_token']
        self._token_expira = agora + int(resposta.get('expires_in', 3000))
        return self._token

    def _pedir(self, pedido):
        try:
            with self._abrir(pedido, timeout=PRAZO_S) as resposta:
                return json.load(resposta)
        except OSError as erro:  # inclui HTTPError e URLError; o corpo do erro pode ecoar dado, então só o tipo e o código
            raise ErroDoMonitoramento(f'falha ao falar com o Google ({type(erro).__name__} {getattr(erro, "code", "")})'.strip()) from None
        except ValueError as erro:
            raise ErroDoMonitoramento('resposta do Google fora do formato JSON') from erro

    def _soma(self, inicio, fim, periodo_s):
        _, _, projeto = self._credencial()
        parametros = {
            'filter': f'metric.type="{METRICA}" AND resource.type="consumer_quota" AND resource.labels.service="{SERVICO}" AND metric.labels.quota_metric="{QUOTA_METRIC}"',
            'interval.startTime': inicio.strftime('%Y-%m-%dT%H:%M:%SZ'), 'interval.endTime': fim.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'aggregation.alignmentPeriod': f'{periodo_s}s', 'aggregation.perSeriesAligner': 'ALIGN_SUM',
            'aggregation.crossSeriesReducer': 'REDUCE_SUM',
        }
        total, pagina = 0, None
        while True:
            consulta = {**parametros, **({'pageToken': pagina} if pagina else {})}
            url = f'https://monitoring.googleapis.com/v3/projects/{urllib.parse.quote(projeto)}/timeSeries?{urllib.parse.urlencode(consulta)}'
            resposta = self._pedir(urllib.request.Request(url, headers={'Authorization': f'Bearer {self._acesso()}'}))
            total += sum(int(ponto['value'].get('int64Value', 0)) for serie in resposta.get('timeSeries', []) for ponto in serie.get('points', []))
            pagina = resposta.get('nextPageToken')
            if not pagina:
                return total

    def contar(self, inicio, fim):
        """Tiles 2D usados em [inicio, fim] (datetimes com fuso, `inicio` em hora cheia). Ausência de série é zero medido:
        o Google responde 200 sem série quando não houve uso, e o 403/erro de rede vira exceção, nunca zero."""
        # Soma de horas em UTC: no fuso do Pacífico a troca de horário de verão deslocaria o corte.
        inicio, fim = inicio.astimezone(timezone.utc), fim.astimezone(timezone.utc)
        cheias = int((fim - inicio).total_seconds() // HORA)
        corte = inicio + timedelta(seconds=cheias * HORA)
        total = self._soma(inicio, corte, HORA) if cheias else 0
        if fim > corte:  # a hora corrente, minuto a minuto, para a soma chegar até agora
            total += self._soma(corte, fim, 60)
        return total
