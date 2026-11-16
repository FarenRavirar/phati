"""Página /auditoria/ (005 R6, R7; A2): lista, filtra e pagina a auditoria.

A regra de escopo e o texto dos eventos ficam em `permissao/auditoria_leitura.py`, a mesma função da API (R3). Aqui só se
valida o formulário com `ParametrosDaAuditoria` (a mesma regra da rota) e se monta a tela. Ordem: acesso antes de qualquer
validação, então quem não lê recebe 404 mesmo com filtro ruim; filtro inválido é aviso na página, sem consulta e sem gravação.
"""

from datetime import date, datetime, time
from urllib.parse import urlencode

from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from django.utils import timezone
from django.views.decorators.http import require_GET

from comum.auditoria import ACOES
from comum.auditoria_rotulos import rotulo_e_resumo
from permissao import auditoria_leitura
from permissao.api import ParametrosDaAuditoria, pessoas_do_escopo
from permissao.pode import com_permissao, escopos_da_acao
from projeto.paginas_autenticadas import campo, exige_acao, exige_entrada, renderizar_na_casca
from territorio.models import Empresa

# Filtros do formulário, na ordem em que aparecem; só estes saem para o link "Mais antigos".
FILTROS = ('desde', 'ate', 'acao', 'pessoa_id', 'alvo_pessoa_id', 'empresa_id')
COLUNAS = ('Hora', 'Ação', 'Quem', 'Alvo', 'Empresa', 'Resumo')
MENSAGEM_DO_FILTRO = 'Filtro inválido: confira as datas, a ação, as pessoas e a empresa escolhidas.'
SEM_EMPRESA = 'Sem empresa'  # evento da plataforma, sem empresa (A3); vazio na célula seria ambíguo
OPCOES_DE_ACAO = [{'valor': '', 'rotulo': 'Todas as ações'}, *sorted(
    ({'valor': acao, 'rotulo': rotulo_e_resumo(acao, None)[0]} for acao in ACOES), key=lambda opcao: opcao['rotulo'])]


def _dia(texto):
    """`<input type=date>` (AAAA-MM-DD) vira data; vazio vira None; outro formato levanta ValueError."""
    return date.fromisoformat(texto) if texto else None


def _parametros(get):
    """`(parâmetros, None)` ou `(None, mensagem)`. As datas viram datetime aware no fuso local: início do dia em `desde`, fim
    do dia em `ate` (o filtro é `<=`, então meia-noite deixaria o próprio dia de fora)."""
    try:
        desde, ate = _dia(get.get('desde', '')), _dia(get.get('ate', ''))
        dados = {
            'depois': get.get('depois') or 0,
            'desde': timezone.make_aware(datetime.combine(desde, time.min)) if desde else None,
            'ate': timezone.make_aware(datetime.combine(ate, time.max)) if ate else None,
            'acao': get.get('acao') or None,
            # Ids vazios viram None (sem filtro); id que não é inteiro positivo falha na mesma validação do pydantic.
            'pessoa_id': get.get('pessoa_id') or None,
            'alvo_pessoa_id': get.get('alvo_pessoa_id') or None,
            'empresa_id': get.get('empresa_id') or None,
        }
        return ParametrosDaAuditoria.model_validate(dados), None
    except (ValueError, OverflowError):  # `ValidationError` do pydantic também é ValueError
        return None, MENSAGEM_DO_FILTRO


def _linha(evento):
    return [
        timezone.localtime(evento['hora']).strftime('%d/%m/%Y %H:%M:%S'), evento['rotulo'], evento['quem'], evento['alvo'],
        evento['empresa'] or SEM_EMPRESA, evento['resumo'],
    ]


def _opcoes_de_pessoa(pessoas, rotulo_vazio):
    return [{'valor': '', 'rotulo': rotulo_vazio}, *({'valor': pk, 'rotulo': nome} for pk, nome in pessoas)]


def _campos(get, pessoas, empresas):
    """`pessoas` e `empresas` são `(id, nome)` do escopo de quem olha (dado, não lista fixa). O filtro de empresa só aparece
    a quem enxerga mais de uma: com uma só, filtrar por ela não acrescenta nada."""
    campos = [
        campo('desde', 'Desde', get.get('desde', ''), tipo='date'),
        campo('ate', 'Até', get.get('ate', ''), tipo='date'),
        campo('acao', 'Ação', get.get('acao', ''), tipo='select', opcoes=OPCOES_DE_ACAO),
        campo('pessoa_id', 'Quem agiu', get.get('pessoa_id', ''), tipo='select', opcoes=_opcoes_de_pessoa(pessoas, 'Todas as pessoas')),
        campo('alvo_pessoa_id', 'Pessoa afetada', get.get('alvo_pessoa_id', ''), tipo='select', opcoes=_opcoes_de_pessoa(pessoas, 'Todas as pessoas')),
    ]
    if len(empresas) > 1:
        opcoes = [{'valor': '', 'rotulo': 'Todas as empresas'}, *({'valor': pk, 'rotulo': nome} for pk, nome in empresas)]
        campos.append(campo('empresa_id', 'Empresa', get.get('empresa_id', ''), tipo='select', opcoes=opcoes))
    return campos


def _pessoas_e_empresas(pessoa):
    """Listas dos selects, materializadas dentro de `com_permissao` (a RLS vale só no bloco). Nome, nunca CPF."""
    pessoas = list(pessoas_do_escopo(pessoa, (auditoria_leitura.ACAO,)).order_by('nome', 'pk').values_list('pk', 'nome'))
    escopos = escopos_da_acao(pessoa, auditoria_leitura.ACAO)
    consulta = Empresa.objects.all() if escopos.plataforma else Empresa.objects.filter(pk__in=escopos.empresas)
    return pessoas, list(consulta.order_by('nome', 'pk').values_list('pk', 'nome'))


def _mais_antigos(get, linhas, mais):
    """Link da página seguinte pelo cursor (último id). Usa só os filtros que já passaram na validação."""
    if not mais:
        return None
    consulta = {nome: get[nome] for nome in FILTROS if get.get(nome)}
    consulta['depois'] = linhas[-1]['id']
    return '?' + urlencode(consulta)


@require_GET
@exige_entrada
@exige_acao('ver_auditoria')
def auditoria(requisicao):
    """Quem não lê a auditoria em empresa alguma recebe 404 (A2), por URL direta inclusive."""
    with com_permissao(requisicao.user, 'ver_auditoria'):
        if not auditoria_leitura.pode_ver_auditoria(requisicao.user):
            raise Http404
        parametros, erro = _parametros(requisicao.GET)
        eventos, mais_antigos = [], None
        if parametros is not None:
            try:
                eventos, mais = auditoria_leitura.consultar(requisicao.user, **parametros.model_dump())
            except ObjectDoesNotExist:  # empresa pedida fora do escopo: 404 comum, igual à API (005 R3)
                raise Http404
            mais_antigos = _mais_antigos(requisicao.GET, eventos, mais)
        pessoas, empresas = _pessoas_e_empresas(requisicao.user)
        contexto = {
            'campos': _campos(requisicao.GET, pessoas, empresas), 'erro': erro, 'colunas': COLUNAS,
            'linhas': [_linha(evento) for evento in eventos], 'mais_antigos': mais_antigos,
        }
        return renderizar_na_casca(requisicao, 'auditoria.html', contexto)
