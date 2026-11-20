"""Recusa de envio acima do limite antes do parse do multipart (008 R16; T3.8).

O nginx recusa antes (`client_max_body_size`, em `servidor/nginx/default.conf`). Este middleware cobre o app sem proxy:
lê só o cabeçalho `Content-Length` da rota de envio, nunca o corpo, e responde 413 com a mesma lista de erros da ingestão.
Sem o cabeçalho, ou com valor que não é número, a requisição segue (quem decide é o Django e a ingestão)."""

import re

from django.http import JsonResponse

from catalogo.ingestao import LIMITES_PADRAO, MENSAGEM_TAMANHO

FOLGA_MULTIPART = 64 * 1024  # campos, cabeçalhos e fronteira do multipart somados ao arquivo
ROTA_DE_ENVIO = re.compile(r'^/api/v1/fazendas/\d+/envios$')


class LimiteDeCorpoDoEnvio:
    def __init__(self, resposta):
        self.resposta = resposta

    def __call__(self, requisicao):
        if requisicao.method == 'POST' and ROTA_DE_ENVIO.match(requisicao.path):
            try:
                tamanho = int(requisicao.META.get('CONTENT_LENGTH', 0))
            except (TypeError, ValueError):
                tamanho = 0
            if tamanho > LIMITES_PADRAO.tamanho_bytes + FOLGA_MULTIPART:
                return JsonResponse({'detalhe': 'recusado', 'erros': [MENSAGEM_TAMANHO]}, status=413)
        return self.resposta(requisicao)
