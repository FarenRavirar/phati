"""Listagens de território autorizadas (R14, R12): só o que a pessoa pode ver, pelo escopo de cada concessão ativa."""

from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import PermissionDenied
from django.core.paginator import Page, Paginator
from django.db.models import Count, Max, Q

from catalogo.models import VersaoCamada
from permissao.pode import com_permissao, escopos_da_acao, pode
from territorio.models import Empresa, Fazenda, SubArea
from territorio.niveis import nome_do_nivel

# Mesmo valor de `projeto/territorio_paginas.py`; não importado de lá, porque `projeto` importa `territorio` (ciclo).
ITENS_POR_PAGINA = 25
TAMANHO_MAXIMO_BUSCA = 100
NIVEL_TALHAO = 2
# Situação do segmentado (telas.md §3): valor ausente ou desconhecido cai em "todas" (None).
SITUACOES = {'todas': None, 'ativas': False, 'arquivadas': True}


def _filtrar_arquivadas(consulta, arquivadas):
    """`arquivadas`: False (padrão) só as de trabalho, True só as arquivadas, None todas (leitura por URL direta, R11)."""
    if arquivadas is None:
        return consulta
    return consulta.filter(arquivada_em__isnull=not arquivadas)


def _consulta_fazendas(escopos, pk=None, empresa_id=None, arquivadas: bool | None = False):
    """Fazendas da empresa inteira, da fazenda concedida ou da fazenda que contém a sub-área concedida (sem abrir bloco de RLS)."""
    if escopos.plataforma:
        consulta = Fazenda.objects.all()
    else:
        consulta = Fazenda.objects.filter(
            Q(empresa_id__in=escopos.empresas) | Q(pk__in=escopos.fazendas | escopos.fazendas_das_sub_areas)
        )
    consulta = _filtrar_arquivadas(consulta, arquivadas)
    if pk is not None:
        consulta = consulta.filter(pk=pk)
    if empresa_id is not None:
        consulta = consulta.filter(empresa_id=empresa_id)
    return consulta


def fazendas_autorizadas(pessoa, pk=None, empresa_id=None, arquivadas: bool | None = False):
    """Fazendas da empresa inteira, da fazenda concedida ou da fazenda que contém a sub-área concedida.

    Com `pk`, só a fazenda pedida (se autorizada): a URL de escopo não carrega a lista inteira (Qodo e Sourcery, PR #19).
    Com `empresa_id`, só as dela, filtradas na consulta e não depois de carregar tudo (Sourcery, PR #21)."""
    escopos = escopos_da_acao(pessoa, 'ver')
    # Avaliada dentro de `com_permissao`: o papel `app` não vê fazenda sem as variáveis, e a lista preguiçosa
    # só consultaria o banco depois de o bloco terminar.
    with com_permissao(pessoa, 'ver'):
        return list(_consulta_fazendas(escopos, pk, empresa_id, arquivadas).order_by('nome', 'pk'))


def empresas_autorizadas(pessoa, pk=None, arquivadas: bool | None = False):
    """Empresas em que a pessoa tem acesso de leitura, inclusive as que só contêm uma fazenda ou sub-área concedida.

    Com `pk`, só a empresa pedida (se autorizada)."""
    escopos = escopos_da_acao(pessoa, 'ver')
    if escopos.plataforma:
        consulta = Empresa.objects.all()
    else:
        consulta = Empresa.objects.filter(pk__in=escopos.empresas | escopos.empresas_das_fazendas)
    consulta = _filtrar_arquivadas(consulta, arquivadas)
    if pk is not None:
        consulta = consulta.filter(pk=pk)
    with com_permissao(pessoa, 'ver'):
        return list(consulta.order_by('nome', 'pk'))


def _tem_acesso_total(escopos, fazenda):
    """Vê todas as sub-áreas da fazenda: plataforma, empresa dela ou a própria fazenda concedida."""
    return escopos.plataforma or fazenda.empresa_id in escopos.empresas or fazenda.pk in escopos.fazendas


def _alcance_sub_areas(escopos, fazendas):
    """Filtro de `SubArea` que a pessoa alcança nas `fazendas`: todas nas que têm acesso total; nas outras, só as
    concedidas e as descendentes (D121). Única regra de alcance de sub-área: a usam `sub_areas_da_fazenda` e as leituras em lote.
    Vazio (`Q()`) quando a plataforma vê tudo."""
    if escopos.plataforma:
        return Q()
    inteiras = [fazenda.pk for fazenda in fazendas if _tem_acesso_total(escopos, fazenda)]
    filtro = Q(fazenda_id__in=inteiras) | Q(pk__in=escopos.sub_areas)
    for sub_area_id in escopos.sub_areas:
        filtro |= Q(caminho__contains=f'/{sub_area_id}/')
    return filtro


def sub_areas_da_fazenda(pessoa, fazenda, arquivadas: bool | None = False):
    """Sub-áreas da `fazenda` que a pessoa alcança: todas, se o acesso é da plataforma, da empresa ou da fazenda;
    com acesso só a sub-áreas, cada uma delas e as descendentes (o pai de uma raiz concedida não vem: monte a árvore
    tratando sub-área sem pai na lista como raiz)."""
    escopos = escopos_da_acao(pessoa, 'ver')
    consulta = _filtrar_arquivadas(SubArea.objects.filter(fazenda_id=fazenda.pk), arquivadas)
    with com_permissao(pessoa, 'ver'):
        return list(consulta.filter(_alcance_sub_areas(escopos, [fazenda])).order_by('nivel', 'nome', 'pk'))


def area_da_fazenda(fazenda):
    """Área (ha) da fazenda. Sem vigência ainda: `None` = "Sem dados", nunca 0.
    shortcut: área vem da revisão vigente quando a spec de vigência existir (spec 012, plan.md, Dados novos)."""
    return None


def _texto_da_busca(bruto):
    """Texto da busca: sem NUL (o PostgreSQL recusa), aparado e limitado. Valor que não é texto vira busca vazia."""
    if not isinstance(bruto, str):
        return ''
    return bruto.replace('\x00', '')[:TAMANHO_MAXIMO_BUSCA].strip()


def _situacao(bruta):
    return SITUACOES.get(bruta) if isinstance(bruta, str) else None


@dataclass(frozen=True)
class LinhaFazenda:
    fazenda: Fazenda
    area: float | None
    talhoes: int
    atualizado: datetime


@dataclass(frozen=True)
class PaginaDeFazendas:
    linhas: list[LinhaFazenda]
    pagina: Page
    total_filtrado: int
    total: int
    rotulo_talhoes: str


def _consulta_filtrada(escopos, texto, arquivadas, empresa_id):
    """Fazendas que o escopo alcança, filtradas por texto (nome ou município sem acento), situação e empresa: a única
    consulta da listagem e da exportação. Devolve `(base, filtrada)`; a base sem filtro de texto e situação conta o total."""
    base = _consulta_fazendas(escopos, empresa_id=empresa_id, arquivadas=None)
    consulta = base
    if texto:
        consulta = consulta.filter(Q(nome__unaccent__icontains=texto) | Q(municipio__unaccent__icontains=texto))
    return base, _filtrar_arquivadas(consulta, arquivadas)


def _linhas(escopos, fazendas):
    """Talhões e última atualização de cada fazenda, em duas leituras em lote (sem consulta por linha)."""
    ids = [fazenda.pk for fazenda in fazendas]
    restritas = [f for f in fazendas if not _tem_acesso_total(escopos, f)]

    talhoes = dict(
        SubArea.objects.filter(fazenda_id__in=ids, nivel=NIVEL_TALHAO, arquivada_em__isnull=True)
        .filter(_alcance_sub_areas(escopos, fazendas))
        .order_by()
        .values('fazenda_id').annotate(n=Count('pk')).values_list('fazenda_id', 'n')
    )
    # Versão é da fazenda; quem só alcança sub-áreas vê a versão que tem feição numa sub-área alcançada.
    alcance_versao = Q(fazenda_id__in=[f.pk for f in fazendas if _tem_acesso_total(escopos, f)])
    if restritas:
        alcance_versao |= Q(feicoes__sub_area__in=SubArea.objects.filter(_alcance_sub_areas(escopos, restritas)).values('pk'))
    ultimas = dict(
        VersaoCamada.objects.filter(fazenda_id__in=ids).filter(alcance_versao)
        .order_by().values('fazenda_id').annotate(ultima=Max('criada_em')).values_list('fazenda_id', 'ultima')
    )
    return [
        LinhaFazenda(
            fazenda=fazenda,
            area=area_da_fazenda(fazenda),
            talhoes=talhoes.get(fazenda.pk, 0),
            atualizado=max(v for v in (fazenda.criada_em, ultimas.get(fazenda.pk)) if v is not None),
        )
        for fazenda in fazendas
    ]


def listar_fazendas(pessoa, busca: object = '', situacao: object = 'todas', empresa_id=None, pagina: int | str | None = None) -> PaginaDeFazendas:
    """Página da listagem de fazendas (R20): só as que a pessoa vê, filtradas por nome ou município sem acento, por
    situação e, se houver, por empresa. Número de consultas fixo por página: uma leitura em lote para os talhões e
    outra para a última atualização, sem consulta por linha."""
    escopos = escopos_da_acao(pessoa, 'ver')
    with com_permissao(pessoa, 'ver'):
        base, consulta = _consulta_filtrada(escopos, _texto_da_busca(busca), _situacao(situacao), empresa_id)
        total = base.count()
        paginador = Paginator(consulta.select_related('empresa').order_by('nome', 'pk'), ITENS_POR_PAGINA)
        pagina_pedida = paginador.get_page(pagina)
        linhas = _linhas(escopos, list(pagina_pedida.object_list))
        rotulo = nome_do_nivel(Empresa(pk=empresa_id), NIVEL_TALHAO) if empresa_id is not None else 'Talhões'
        return PaginaDeFazendas(
            linhas=linhas, pagina=pagina_pedida, total_filtrado=paginador.count, total=total, rotulo_talhoes=rotulo,
        )


def pode_exportar_fazendas(pessoa) -> bool:
    """Tem `exportar_dados` em alguma fazenda (plataforma, empresa ou fazenda concedida). Concessão só de sub-área não conta:
    `pode()` exige a fazenda inteira. Quem não tem não vê o botão Exportar nem a rota (R30)."""
    exportar = escopos_da_acao(pessoa, 'exportar_dados')
    return bool(exportar.plataforma or exportar.empresas or exportar.fazendas)


def empresas_com_nova_fazenda(pessoa) -> list[Empresa]:
    """Empresas em que a pessoa pode cadastrar fazenda, por `pode()` em cada uma (arquivada não entra, R11)."""
    with com_permissao(pessoa, 'ver', 'criar_fazenda'):
        return [empresa for empresa in empresas_autorizadas(pessoa) if pode(pessoa, 'criar_fazenda', empresa)]


def exportar_fazendas(pessoa, busca: object = '', situacao: object = 'todas', empresa_id=None) -> list[LinhaFazenda]:
    """Todas as linhas filtradas que a pessoa vê e pode exportar (R30), sem paginação. Mesma consulta da listagem; a
    permissão de exportar entra por `pode()` em cada fazenda, em memória (ação de leitura, sem consulta extra).
    Sem exportar em fazenda nenhuma (plataforma, empresa ou fazenda concedida): `PermissionDenied`. Concessão só de
    sub-área não exporta a fazenda que a contém (`pode()` exige a fazenda inteira)."""
    if not pode_exportar_fazendas(pessoa):
        raise PermissionDenied
    escopos = escopos_da_acao(pessoa, 'ver')
    with com_permissao(pessoa, 'ver', 'exportar_dados'):
        _, consulta = _consulta_filtrada(escopos, _texto_da_busca(busca), _situacao(situacao), empresa_id)
        fazendas = [f for f in consulta.select_related('empresa').order_by('nome', 'pk') if pode(pessoa, 'exportar_dados', f)]
        return _linhas(escopos, fazendas)
