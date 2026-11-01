"""Início (R9, 003 R7): convites pendentes da pessoa, atalhos de gestão e as fazendas (ou, na plataforma, as empresas). Aceitar e Recusar chamam os mesmos
serviços da API (`permissao.convite`); o id só alcança convite dirigido a quem chama, e outro id dá 404."""

from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from permissao import convite
from permissao.models import Convite
from projeto.paginas_autenticadas import PROPRIA_PESSOA, exige_acao, exige_entrada, renderizar_na_casca
from projeto.menu import atalhos_do_inicio
from territorio.listagem import empresas_autorizadas, fazendas_autorizadas

# A recusa volta ao Início por redirecionamento (`/?erro=<código>`): recarregar a página não repete o POST. O texto vem
# desta tabela, nunca do parâmetro. Convite sem autoridade de quem convidou não revela o motivo à pessoa convidada.
TEXTOS_DO_CONVITE = {
    'convite_encerrado': 'Convite já respondido.',
    'convite_vencido': 'Convite vencido.',
    'convite_indisponivel': 'Não foi possível responder ao convite.',
}


@require_GET
@exige_entrada
@exige_acao(PROPRIA_PESSOA)
def inicio(requisicao):
    contexto = {
        'convites': convite.convites_da_pessoa(requisicao.user),
        'atalhos': atalhos_do_inicio(requisicao.user),
        # O Administrador da plataforma vê as empresas, não todas as fazendas da casa (R7).
        'empresas': empresas_autorizadas(requisicao.user) if requisicao.user.administrador_plataforma else [],
        'fazendas': [] if requisicao.user.administrador_plataforma else fazendas_autorizadas(requisicao.user),
        'erro': TEXTOS_DO_CONVITE.get(requisicao.GET.get('erro', '')),
    }
    return renderizar_na_casca(requisicao, 'inicio.html', contexto)


def _recusado(codigo):
    codigo = codigo if codigo in TEXTOS_DO_CONVITE else 'convite_indisponivel'
    return redirect(f'/?{urlencode({"erro": codigo})}')


def _responder(requisicao, convite_id, resposta):
    try:
        resposta(requisicao.user, convite_id)
    except Convite.DoesNotExist as ausente:
        raise Http404 from ausente
    except ValidationError as erro:
        return _recusado(erro.code)
    except PermissionDenied:
        return _recusado(None)
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
