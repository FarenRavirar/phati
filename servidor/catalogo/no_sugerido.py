"""Nó sugerido de uma feição (008 R7, T2.2): o nó de maior área de interseção, sem sugestão quando empata.

Área por `ST_Area(geography)` e interseção feita no banco (T0.3).

Origem das geometrias dos nós: D117 (decisão do mantenedor). O contorno vem de uma camada de divisão publicada pela
própria 008 (Fase 3). A tabela `territorio.sub_area` não tem geometria e não ganha coluna nova por esta função.
RLS dos nós: é do chamador. Esta função não consulta o escopo; quem chama carrega os nós com o escopo da sessão
(`nos_da_fazenda` filtra pela fazenda, mas não substitui a RLS do banco)."""

from dataclasses import dataclass

from django.db import connection

from territorio.models import SubArea


@dataclass(frozen=True)
class LimiarNo:
    """Valores iniciais do plano (spec 008 §Sugestão de nó).

    shortcut: 1% e 1% são valores iniciais; medir com dado sintético antes de fechar a Fase 2."""

    fracao_minima_do_no: float = 0.01  # nó com menos desta fração da área da feição não é sugerido
    diferenca_minima: float = 0.01  # diferença relativa entre os dois maiores abaixo disto é empate


@dataclass(frozen=True)
class SugestaoNo:
    sub_area_id: int | None
    motivo: str  # 'unico', 'maior_area', 'empate', 'sem_intersecao', 'abaixo_do_limiar', 'sem_area'
    areas: dict  # id do nó -> área de interseção em m² (só nós com interseção)


def nos_da_fazenda(fazenda):
    """Ids dos nós ativos da fazenda (R7: só nós dela; nó arquivado fica de fora)."""
    return list(SubArea.objects.filter(fazenda=fazenda, arquivada_em__isnull=True).order_by('id').values_list('id', flat=True))


def _area(cursor, ewkt_a, ewkt_b=None):
    if ewkt_b is None:
        cursor.execute('SELECT ST_Area(ST_GeomFromEWKT(%s)::geography)', [ewkt_a])
    else:
        cursor.execute(
            'SELECT ST_Area(ST_Intersection(ST_GeomFromEWKT(%s)::geography, ST_GeomFromEWKT(%s)::geography))',
            [ewkt_a, ewkt_b],
        )
    return float(cursor.fetchone()[0] or 0.0)


def sugerir_no(feicao, nos, limiar=LimiarNo()):
    """`feicao`: GEOSGeometry em SRID 4674 (polígono). `nos`: pares (id, GEOSGeometry) da mesma fazenda."""
    with connection.cursor() as cursor:
        area_feicao = _area(cursor, feicao.ewkt)
        if area_feicao <= 0:
            return SugestaoNo(None, 'sem_area', {})
        areas = {}
        for id_no, geometria in nos:
            area = _area(cursor, feicao.ewkt, geometria.ewkt)
            if area > 0:
                areas[id_no] = area
    if not areas:
        return SugestaoNo(None, 'sem_intersecao', areas)
    relevantes = sorted(
        ((id_no, area) for id_no, area in areas.items() if area >= limiar.fracao_minima_do_no * area_feicao),
        key=lambda par: par[1],
        reverse=True,
    )
    if not relevantes:
        return SugestaoNo(None, 'abaixo_do_limiar', areas)
    if len(relevantes) == 1:
        return SugestaoNo(relevantes[0][0], 'unico', areas)
    (id_1, area_1), (_, area_2) = relevantes[0], relevantes[1]
    if area_1 == area_2 or area_1 - area_2 < limiar.diferenca_minima * area_1:  # áreas iguais empatam mesmo com tolerância zero
        return SugestaoNo(None, 'empate', areas)
    return SugestaoNo(id_1, 'maior_area', areas)
