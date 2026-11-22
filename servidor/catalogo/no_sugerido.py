"""Nó sugerido de uma feição (008 R7, T2.2): o nó de maior área de interseção, sem sugestão quando empata.

Área por `ST_Area(geography)` e interseção feita no banco (T0.3).

Origem das geometrias dos nós: D117 (decisão do mantenedor). O contorno vem de uma camada de divisão publicada pela
própria 008 (Fase 3). A tabela `territorio.sub_area` não tem geometria e não ganha coluna nova por esta função.
RLS dos nós: é do chamador. Esta função não consulta o escopo; quem chama carrega os nós com o escopo da sessão
(`nos_da_fazenda` filtra pela fazenda, mas não substitui a RLS do banco)."""

from dataclasses import dataclass

from django.db import connection

from catalogo.models import Camada, Feicao, VersaoCamada
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


def contornos_da_divisao(fazenda):
    """{id do nó: geometria} da divisão da fazenda (D119): a camada marcada (`coluna_no`) e a versão mais recente dela.

    A versão mais recente é a que vale para a sugestão: uma divisão republicada troca o contorno sem apagar a anterior. Sem
    camada marcada (ou sem versão, ou sem feição ligada a nó), devolve {}: sem divisão, sem sugestão. Feição com o mesmo nó
    várias vezes entra como união. A RLS é a do chamador: fora do escopo, a consulta não traz linha."""
    divisao = Camada.objects.filter(fazenda=fazenda, coluna_no__isnull=False).first()
    if divisao is None:
        return {}
    ultima = VersaoCamada.objects.filter(camada=divisao).order_by('-numero').first()
    if ultima is None:
        return {}
    contornos = {}
    for feicao in Feicao.objects.filter(versao=ultima, sub_area__isnull=False).order_by('id'):
        atual = contornos.get(feicao.sub_area_id)
        contornos[feicao.sub_area_id] = feicao.geometria if atual is None else atual.union(feicao.geometria)
    return contornos


# Consultas fixas por tipo (008 R7): o SQL é constante, sem formatação; o único valor do cliente vai por %s.
# Polígono: área da interseção. Linha: comprimento da interseção (geography, metros). Ponto e multiponto: quantos componentes
# originais da feição caem no nó, borda inclusive (ST_Covers). Total e medida usam a mesma base (componentes da feição), então
# pontos repetidos contam cada ocorrência nos dois lados.
_SQL_TOTAL_AREA = 'SELECT COALESCE(ST_Area(feicao.f::geography), 0) FROM (SELECT ST_GeomFromEWKT(%s) AS f) AS feicao'
_SQL_TOTAL_COMPRIMENTO = 'SELECT COALESCE(ST_Length(feicao.f::geography), 0) FROM (SELECT ST_GeomFromEWKT(%s) AS f) AS feicao'
_SQL_TOTAL_COMPONENTES = 'SELECT COALESCE(ST_NumGeometries(feicao.f), 0) FROM (SELECT ST_GeomFromEWKT(%s) AS f) AS feicao'
_TOTAL_POR_TIPO = {
    'Polygon': _SQL_TOTAL_AREA,
    'MultiPolygon': _SQL_TOTAL_AREA,
    'LineString': _SQL_TOTAL_COMPRIMENTO,
    'MultiLineString': _SQL_TOTAL_COMPRIMENTO,
    'Point': _SQL_TOTAL_COMPONENTES,
    'MultiPoint': _SQL_TOTAL_COMPONENTES,
}
_SQL_MEDIDAS_AREA = (
    'SELECT t.id, COALESCE(ST_Area(ST_Intersection(feicao.f, no.g)::geography), 0) '
    'FROM unnest(%s::bigint[], %s::text[]) AS t(id, ewkt) '
    'CROSS JOIN (SELECT ST_GeomFromEWKT(%s) AS f) AS feicao '
    'CROSS JOIN LATERAL (SELECT ST_GeomFromEWKT(t.ewkt) AS g) AS no'
)
_SQL_MEDIDAS_COMPRIMENTO = (
    'SELECT t.id, COALESCE(ST_Length(ST_Intersection(feicao.f, no.g)::geography), 0) '
    'FROM unnest(%s::bigint[], %s::text[]) AS t(id, ewkt) '
    'CROSS JOIN (SELECT ST_GeomFromEWKT(%s) AS f) AS feicao '
    'CROSS JOIN LATERAL (SELECT ST_GeomFromEWKT(t.ewkt) AS g) AS no'
)
_SQL_MEDIDAS_COMPONENTES = (
    'SELECT t.id, COALESCE((SELECT count(*) FROM ST_Dump(feicao.f) AS d WHERE ST_Covers(no.g, d.geom)), 0) '
    'FROM unnest(%s::bigint[], %s::text[]) AS t(id, ewkt) '
    'CROSS JOIN (SELECT ST_GeomFromEWKT(%s) AS f) AS feicao '
    'CROSS JOIN LATERAL (SELECT ST_GeomFromEWKT(t.ewkt) AS g) AS no'
)
_MEDIDAS_POR_TIPO = {
    'Polygon': _SQL_MEDIDAS_AREA,
    'MultiPolygon': _SQL_MEDIDAS_AREA,
    'LineString': _SQL_MEDIDAS_COMPRIMENTO,
    'MultiLineString': _SQL_MEDIDAS_COMPRIMENTO,
    'Point': _SQL_MEDIDAS_COMPONENTES,
    'MultiPoint': _SQL_MEDIDAS_COMPONENTES,
}
# shortcut: coleção mista (GeometryCollection) não tem medida única; vai como sem_area até a spec dizer o que fazer com ela.
TIPOS_DE_PONTO = frozenset({'Point', 'MultiPoint'})
TIPOS_DE_LINHA = frozenset({'LineString', 'MultiLineString'})


def _total(cursor, ewkt, tipo):
    """Medida total da feição (área, comprimento ou quantidade de componentes). 0 para tipo sem medida (coleção mista)."""
    consulta = _TOTAL_POR_TIPO.get(tipo)
    if consulta is None:
        return 0.0
    cursor.execute(consulta, [ewkt])
    return float(cursor.fetchone()[0] or 0.0)


def _medidas(cursor, ewkt_feicao, tipo, nos):
    """Medida da feição em cada nó, numa consulta só (medido antes: N×M consultas eram o problema, 1051 para 50×20).
    Pares (id do nó, medida) na ordem de `nos`."""
    cursor.execute(
        _MEDIDAS_POR_TIPO[tipo],
        [[id_no for id_no, _ in nos], [geometria.ewkt for _, geometria in nos], ewkt_feicao],
    )
    brutas = {id_no: float(valor or 0.0) for id_no, valor in cursor.fetchall()}
    return [(id_no, brutas[id_no]) for id_no, _ in nos]


def _relevantes(medidas, total, limiar):
    """Nós com medida de pelo menos a fração mínima do total, do maior para o menor."""
    return sorted(
        ((id_no, valor) for id_no, valor in medidas.items() if valor >= limiar.fracao_minima_do_no * total),
        key=lambda par: par[1],
        reverse=True,
    )


def _decidir(tipo, relevantes, medidas, limiar):
    """Classificação com os dois maiores: sem nó relevante, abaixo do limiar; um só, contido ou único; iguais ou quase
    iguais, empate; senão o maior, pelo critério do tipo."""
    if not relevantes:
        return SugestaoNo(None, 'abaixo_do_limiar', medidas)
    (id_1, valor_1) = relevantes[0]
    if len(relevantes) == 1:
        return SugestaoNo(id_1, 'contido' if tipo in TIPOS_DE_PONTO else 'unico', medidas)
    valor_2 = relevantes[1][1]
    if valor_1 == valor_2 or valor_1 - valor_2 < limiar.diferenca_minima * valor_1:  # iguais empatam mesmo com tolerância zero
        return SugestaoNo(None, 'empate', medidas)
    if tipo in TIPOS_DE_PONTO:
        return SugestaoNo(id_1, 'maior_contagem', medidas)
    if tipo in TIPOS_DE_LINHA:
        return SugestaoNo(id_1, 'maior_comprimento', medidas)
    return SugestaoNo(id_1, 'maior_area', medidas)


def sugerir_no(feicao, nos, limiar=LimiarNo()):
    """`feicao`: GEOSGeometry em SRID 4674. `nos`: pares (id, GEOSGeometry) da mesma fazenda.

    Regra única por tipo, com os mesmos limiares: fração mínima de 1% do total, e diferença de 1% entre os dois maiores para
    empate. Ponto vai ao nó que o contém (borda conta); linha vai ao nó de maior comprimento; polígono, ao de maior área."""
    tipo = feicao.geom_type
    if feicao.empty:
        return SugestaoNo(None, 'sem_area', {})
    with connection.cursor() as cursor:
        total = _total(cursor, feicao.ewkt, tipo)
        if total <= 0:
            return SugestaoNo(None, 'sem_area', {})
        medidas = {}
        if nos:
            for id_no, valor in _medidas(cursor, feicao.ewkt, tipo, nos):
                if valor > 0:
                    medidas[id_no] = valor
    if not medidas:
        return SugestaoNo(None, 'sem_intersecao', medidas)
    return _decidir(tipo, _relevantes(medidas, total, limiar), medidas, limiar)
