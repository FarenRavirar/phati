"""API JSON `/api/v1/` (R17; plan.md §API e painel): instância, autenticação e tratamento de erro.

Duas formas de entrar, as duas gravam `requisicao.user` (é de onde `exige_permissao` lê a pessoa):
cookie de sessão do navegador (com CSRF, conferido pelo `APIKeyCookie`) e `Authorization: Bearer` do aplicativo.
Pessoa que ainda deve trocar a senha só alcança `trocar_senha` e `sair` (A4). `docs` e `openapi.json` ficam
desligados: o contrato é o arquivo commitado em `contrato/openapi.json`.
"""

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from ninja import NinjaAPI
from ninja.errors import HttpError
from ninja.errors import ValidationError as ErroDeEntrada
from ninja.parser import Parser
from ninja.security import APIKeyCookie, HttpBearer

from identidade import sessao
from identidade.api import roteador as roteador_identidade
from territorio.api import roteador as roteador_territorio

_ROTAS_DA_TROCA = frozenset({'trocar_senha', 'sair'})


def _liberar(requisicao, pessoa):
    nome = getattr(requisicao.resolver_match, 'url_name', None)
    if pessoa.deve_trocar_senha and nome not in _ROTAS_DA_TROCA:
        raise HttpError(403, 'troca_de_senha_obrigatoria')
    requisicao.user = pessoa
    return pessoa


class AutenticacaoNavegador(APIKeyCookie):
    param_name = settings.SESSION_COOKIE_NAME

    def authenticate(self, request, key):
        if key is None or not sessao.sessao_vigente(request) or not request.user.is_authenticated:
            return None
        return _liberar(request, request.user)


class AutenticacaoAplicativo(HttpBearer):
    def authenticate(self, request, token):
        pessoa = sessao.pessoa_do_acesso(token)
        if pessoa is None:
            return None
        return _liberar(request, pessoa)


class LeitorJson(Parser):
    """Só `application/json` entra. O ninja lê o corpo como JSON seja qual for o tipo, e um formulário `text/plain`
    de outro site passa por cima do CORS: sem este teste, `entrar` criaria sessão a pedido de qualquer página
    (login CSRF; achado do Qodo, PR #14)."""

    def parse_body(self, request):
        if request.content_type != 'application/json':
            raise ValueError('tipo_de_conteudo_invalido')  # o ninja responde 400 a qualquer falha de leitura do corpo
        return super().parse_body(request)


api = NinjaAPI(
    title='phati',
    version='1',
    urls_namespace='api_v1',
    docs_url=None,
    openapi_url=None,
    # Bearer primeiro: o `APIKeyCookie` confere o CSRF antes de olhar o cookie e, falhando, interrompe a cadeia; o
    # aplicativo não tem cookie e levaria 403 em toda escrita (achado do CodeRabbit, PR #14). O `HttpBearer` devolve
    # `None` sem o cabeçalho, e o navegador cai no cookie.
    auth=[AutenticacaoAplicativo(), AutenticacaoNavegador()],
    parser=LeitorJson(),
)
api.add_router('', roteador_identidade)
api.add_router('', roteador_territorio)


@api.exception_handler(ErroDeEntrada)
def entrada_invalida(requisicao, erro):
    # Sem `input` nem `msg`: o valor recusado pode ser uma senha, e o Pydantic o devolveria na resposta.
    campos = [{'campo': [str(parte) for parte in item['loc']], 'tipo': item['type']} for item in erro.errors]
    return api.create_response(requisicao, {'detalhe': 'entrada_invalida', 'campos': campos}, status=422)


# Uma forma só de erro: sem isto o ninja responde `detail` nos erros dele (401, 403 de CSRF) e `detalhe` nos nossos.
@api.exception_handler(HttpError)
def erro_http(requisicao, erro):
    return api.create_response(requisicao, {'detalhe': erro.message}, status=erro.status_code)


@api.exception_handler(ValidationError)
def regra_recusada(requisicao, erro):
    return api.create_response(requisicao, {'detalhe': getattr(erro, 'code', None) or 'invalido'}, status=400)


@api.exception_handler(PermissionDenied)
def negado(requisicao, erro):
    return api.create_response(requisicao, {'detalhe': 'negado'}, status=403)


# Sob a RLS o alvo fora do escopo nem existe para o papel `app`: responde como não encontrado, não como 500.
@api.exception_handler(ObjectDoesNotExist)
def nao_encontrado(requisicao, erro):
    return api.create_response(requisicao, {'detalhe': 'nao_encontrado'}, status=404)
