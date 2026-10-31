"""Início (R9): convites pendentes da pessoa e as fazendas a que ela tem acesso. Aceitar e Recusar chamam os mesmos
serviços da API (`permissao.convite`); o id só alcança convite dirigido a quem chama, e outro id dá 404."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from permissao import convite
from permissao.models import Convite
from projeto.paginas_autenticadas import PROPRIA_PESSOA, exige_acao, exige_entrada, renderizar_na_casca
from territorio.listagem import fazendas_autorizadas

# O motivo vem do serviço (`ValidationError` já em português); recusa de autoridade não revela por quê.
SEM_AUTORIDADE = 'Não foi possível responder ao convite.'


def _pagina(requisicao, erro=None):
    contexto = {
        'convites': convite.convites_da_pessoa(requisicao.user),
        'fazendas': fazendas_autorizadas(requisicao.user),
        'erro': erro,
    }
    return renderizar_na_casca(requisicao, 'inicio.html', contexto)


@require_GET
@exige_entrada
@exige_acao(PROPRIA_PESSOA)
def inicio(requisicao):
    return _pagina(requisicao)


def _responder(requisicao, convite_id, resposta):
    try:
        resposta(requisicao.user, convite_id)
    except Convite.DoesNotExist as ausente:
        raise Http404 from ausente
    except ValidationError as erro:
        return _pagina(requisicao, erro.messages[0])
    except PermissionDenied:
        return _pagina(requisicao, SEM_AUTORIDADE)
    return redirect('/')


@require_POST
@exige_entrada
@exige_acao(PROPRIA_PESSOA)
def aceitar_convite(requisicao, convite_id):
    return _responder(requisicao, convite_id, convite.aceitar)


@require_POST
@exige_entrada
@exige_acao(PROPRIA_PESSOA)
def recusar_convite(requisicao, convite_id):
    return _responder(requisicao, convite_id, convite.recusar)
