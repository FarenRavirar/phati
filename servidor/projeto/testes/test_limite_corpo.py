"""Recusa de envio acima do limite antes do parse (008 R16; projeto/limite_corpo.py) e limite do nginx na rota de API."""

import math
import re
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.test import Client, RequestFactory

from catalogo.ingestao import LIMITES_PADRAO
from projeto.limite_corpo import FOLGA_MULTIPART, LimiteDeCorpoDoEnvio

ROTA = '/api/v1/fazendas/1/envios'
ACIMA = LIMITES_PADRAO.tamanho_bytes + FOLGA_MULTIPART + 1


def _passa(requisicao):
    return LimiteDeCorpoDoEnvio(lambda _: HttpResponse('ok'))(requisicao)


def test_content_length_acima_do_limite_e_recusado_com_413_antes_do_parse():
    # O corpo é pequeno: a recusa vem do cabeçalho, sem ler nem parsear o multipart. Sem sessão: nem chega à autenticação.
    resposta = Client().post(ROTA, data=b'x', content_type='multipart/form-data; boundary=x', CONTENT_LENGTH=str(ACIMA))
    assert resposta.status_code == 413
    assert resposta.json()['detalhe'] == 'recusado'
    assert resposta.json()['erros'] == ['arquivo acima do limite de tamanho']


def test_corpo_normal_passa_o_middleware_e_chega_a_autenticacao():
    resposta = Client().post(ROTA, data=b'x', content_type='multipart/form-data; boundary=x', CONTENT_LENGTH='10')
    assert resposta.status_code == 401  # passou pelo middleware e parou na autenticação, como deve


def test_limite_exato_passa_e_um_byte_acima_e_recusado():
    no_limite = RequestFactory().post(ROTA, data=b'', content_type='application/octet-stream')
    no_limite.META['CONTENT_LENGTH'] = str(LIMITES_PADRAO.tamanho_bytes + FOLGA_MULTIPART)
    assert _passa(no_limite).content == b'ok'
    acima = RequestFactory().post(ROTA, data=b'', content_type='application/octet-stream')
    acima.META['CONTENT_LENGTH'] = str(LIMITES_PADRAO.tamanho_bytes + FOLGA_MULTIPART + 1)
    assert _passa(acima).status_code == 413


def test_sem_content_length_ou_com_valor_invalido_segue_para_o_django():
    sem = RequestFactory().post(ROTA, data=b'', content_type='application/octet-stream')
    sem.META.pop('CONTENT_LENGTH', None)
    assert _passa(sem).content == b'ok'
    invalido = RequestFactory().post(ROTA, data=b'', content_type='application/octet-stream')
    invalido.META['CONTENT_LENGTH'] = 'nao-e-numero'
    assert _passa(invalido).content == b'ok'


def test_outras_rotas_e_metodos_nao_sao_afetados():
    grande = RequestFactory().get('/api/v1/fazendas/1/envios')
    grande.META['CONTENT_LENGTH'] = str(ACIMA)
    assert _passa(grande).content == b'ok'
    outra = RequestFactory().post('/api/v1/envios/x/publicar', data=b'', content_type='application/octet-stream')
    outra.META['CONTENT_LENGTH'] = str(ACIMA)
    assert _passa(outra).content == b'ok'


def test_nginx_aceita_na_rota_de_api_o_tamanho_do_envio_mais_a_folga():
    # Sem `client_max_body_size` o padrão do nginx é 1 MB e recusa o envio antes do app.
    texto = (Path(settings.DIRETORIO_BASE) / 'nginx' / 'default.conf').read_text(encoding='utf-8')
    bloco = re.search(r'location /api/ \{(.*?)\n    \}', texto, re.DOTALL)
    assert bloco, 'bloco location /api/ não encontrado'
    tamanho = re.search(r'client_max_body_size\s+(\d+)m;', bloco.group(1))
    assert tamanho, 'client_max_body_size não definido no bloco /api/'
    limite_mb = int(tamanho.group(1))
    assert limite_mb >= math.ceil((LIMITES_PADRAO.tamanho_bytes + FOLGA_MULTIPART) / (1024 * 1024))
