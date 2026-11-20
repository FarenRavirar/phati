"""Nó sugerido (008 T2.2, R7): maior área de interseção, sem sugestão em empate, com limiares configuráveis.

Geometrias sintéticas em SRID 4674 perto de (-48,3; -10,7). A feição tem 0,01° de largura; os nós cortam a largura
em frações exatas, e a área de uma faixa de longitude é proporcional à largura no mesmo intervalo de latitude."""

import uuid

import pytest
from django.contrib.gis.geos import GEOSGeometry
from django.utils import timezone

from catalogo.no_sugerido import LimiarNo, contornos_da_divisao, nos_da_fazenda, sugerir_no
from territorio.models import SubArea

pytestmark = pytest.mark.django_db  # sugerir_no consulta o PostGIS para as áreas

FEICAO = GEOSGeometry('POLYGON((-48.30 -10.70,-48.29 -10.70,-48.29 -10.69,-48.30 -10.69,-48.30 -10.70))', srid=4674)


def no(x_inicio, x_fim):
    """Nó retangular que cobre a faixa de longitude [x_inicio, x_fim] e toda a latitude da feição (com folga)."""
    return GEOSGeometry(
        f'POLYGON(({x_inicio} -10.72,{x_fim} -10.72,{x_fim} -10.67,{x_inicio} -10.67,{x_inicio} -10.72))', srid=4674
    )


ESQUERDA_70 = (-48.31, -48.293)  # cobre 70% da largura da feição
DIREITA_30 = (-48.293, -48.28)  # cobre os 30% restantes
METADE_ESQ = (-48.31, -48.295)
METADE_DIR = (-48.295, -48.28)


def test_feicao_inteira_em_um_no_recebe_esse_no():
    resultado = sugerir_no(FEICAO, [(1, no(-48.31, -48.28)), (2, no(-48.4, -48.35))])
    assert resultado.motivo == 'unico'
    assert resultado.sub_area_id == 1


def test_cruzamento_sugere_o_no_de_maior_area():
    resultado = sugerir_no(FEICAO, [(1, no(*DIREITA_30)), (2, no(*ESQUERDA_70))])
    assert resultado.motivo == 'maior_area'
    assert resultado.sub_area_id == 2
    assert resultado.areas[2] > resultado.areas[1]


def test_areas_quase_iguais_nao_recebem_sugestao():
    resultado = sugerir_no(FEICAO, [(1, no(*METADE_ESQ)), (2, no(*METADE_DIR))])
    assert resultado.motivo == 'empate'
    assert resultado.sub_area_id is None


def test_diferenca_de_0_4_por_cento_entre_os_dois_maiores_e_empate():
    # 50,2% contra 49,8%: diferença relativa de 0,8% do maior, abaixo do limiar de 1%.
    meio_mais = (-48.30, -48.29498)  # 50,2% da largura
    meio_menos = (-48.29498, -48.28)  # 49,8%
    resultado = sugerir_no(FEICAO, [(1, no(*meio_mais)), (2, no(*meio_menos))])
    assert resultado.motivo == 'empate'


def test_areas_iguais_com_tolerancia_zero_sao_empate():
    # Achado 8: com diferenca_minima=0, a comparação `<` deixava áreas iguais virarem 'maior_area'.
    resultado = sugerir_no(FEICAO, [(1, no(-48.31, -48.28)), (2, no(-48.31, -48.28))], LimiarNo(diferenca_minima=0))
    assert resultado.motivo == 'empate'
    assert resultado.sub_area_id is None


def test_areas_distintas_com_tolerancia_zero_ainda_sugerem_o_maior():
    resultado = sugerir_no(FEICAO, [(1, no(*DIREITA_30)), (2, no(*ESQUERDA_70))], LimiarNo(diferenca_minima=0))
    assert resultado.motivo == 'maior_area'
    assert resultado.sub_area_id == 2


def test_feicao_sem_interseccao_nao_recebe_no():
    resultado = sugerir_no(FEICAO, [(1, no(-48.5, -48.4))])
    assert resultado.motivo == 'sem_intersecao'
    assert resultado.sub_area_id is None


def test_intersecao_abaixo_do_limiar_de_1_por_cento_nao_e_sugerida():
    # Cobre só 0,5% da área da feição (0,00005° de 0,01°): abaixo de 1%.
    resultado = sugerir_no(FEICAO, [(1, no(-48.29005, -48.28))])
    assert resultado.motivo == 'abaixo_do_limiar'
    assert resultado.sub_area_id is None


def test_limiar_de_fracao_configuravel_ignora_no_menor():
    # Com limiar de 40%, o nó de 30% some e o de 70% vira o único.
    resultado = sugerir_no(FEICAO, [(1, no(*DIREITA_30)), (2, no(*ESQUERDA_70))], LimiarNo(fracao_minima_do_no=0.40))
    assert resultado.motivo == 'unico'
    assert resultado.sub_area_id == 2


def test_limiar_de_diferenca_configuravel_muda_o_empate():
    # 60% contra 40%: diferença de 33% do maior. Com limiar de 50% é empate; com o padrão de 1% não é.
    sessenta = (-48.31, -48.294)  # 60% da largura
    quarenta = (-48.294, -48.28)  # 40%
    assert sugerir_no(FEICAO, [(1, no(*sessenta)), (2, no(*quarenta))]).motivo == 'maior_area'
    assert sugerir_no(FEICAO, [(1, no(*sessenta)), (2, no(*quarenta))], LimiarNo(diferenca_minima=0.5)).motivo == 'empate'


def test_feicao_sem_area_nao_recebe_no():
    linha = GEOSGeometry('LINESTRING(-48.30 -10.70,-48.29 -10.69)', srid=4674)
    resultado = sugerir_no(linha, [(1, no(-48.31, -48.28))])
    assert resultado.motivo == 'sem_area'


def test_nos_de_outra_fazenda_nao_aparecem(cenario):
    no_da_outra = SubArea.objects.create(empresa=cenario.x, fazenda=cenario.f2, nivel=1, nome='No da F2')
    ids = nos_da_fazenda(cenario.f1)
    assert no_da_outra.pk not in ids
    assert cenario.g1.id in ids
    assert cenario.t1.id in ids
    assert cenario.g2.id in ids


def test_no_arquivado_nao_e_carregado(cenario, fabrica_pessoa):
    cenario.g2.arquivada_em = timezone.now()
    cenario.g2.arquivada_por = fabrica_pessoa('Quem arquivou')  # a constraint exige os três campos juntos
    cenario.g2.arquivamento = uuid.uuid4()
    cenario.g2.save(update_fields=['arquivada_em', 'arquivada_por', 'arquivamento'])
    assert cenario.g2.id not in nos_da_fazenda(cenario.f1)


def test_contornos_sem_divisao_marcada_devolvem_vazio(cenario):
    assert contornos_da_divisao(cenario.f1) == {}  # sem divisão, sem sugestão


def test_contorno_de_no_com_duas_feicoes_e_a_uniao(cenario, fabrica_pessoa):
    from catalogo.models import Camada, Estudo, Feicao, Tema, VersaoCamada
    pessoa = fabrica_pessoa('Autora Sintetica')
    tema = Tema.objects.create(empresa=cenario.x, nome='Solo')
    estudo = Estudo.objects.create(empresa=cenario.x, fazenda=cenario.f1, tema=tema, nome='Estudo F1')
    camada = Camada.objects.create(estudo=estudo, empresa=cenario.x, fazenda=cenario.f1, nome='Divisao', coluna_no='no')
    versao = VersaoCamada.objects.create(camada=camada, empresa=cenario.x, fazenda=cenario.f1, numero=1,
                                         sistema_original='EPSG:4674', origem='Levantamento sintetico',
                                         hash_original='a' * 64, caminho_original='x.bin', enviada_por=pessoa)
    esquerda = GEOSGeometry('POLYGON((-48.40 -10.80,-48.30 -10.80,-48.30 -10.60,-48.40 -10.60,-48.40 -10.80))', srid=4674)
    direita = GEOSGeometry('POLYGON((-48.30 -10.80,-48.20 -10.80,-48.20 -10.60,-48.30 -10.60,-48.30 -10.80))', srid=4674)
    for geometria in (esquerda, direita):
        Feicao.objects.create(versao=versao, empresa=cenario.x, fazenda=cenario.f1, geometria=geometria,
                              sub_area=cenario.g1)
    contorno = contornos_da_divisao(cenario.f1)[cenario.g1.pk]
    assert round(contorno.area, 6) == round(esquerda.area + direita.area, 6)
    assert contorno.intersection(esquerda).area == pytest.approx(esquerda.area)


# --- consultas em lote (medido: N×M consultas antes, 2 por feição depois; resultado igual) -------------------------------

def test_area_do_no_pela_metade_da_feicao_e_metade_da_area_total():
    resultado = sugerir_no(FEICAO, [(1, no(*METADE_ESQ)), (2, no(-48.5, -48.4))])
    assert resultado.areas.keys() == {1}  # o nó sem interseção não entra nas áreas
    total = sugerir_no(FEICAO, [(9, no(-48.31, -48.28))]).areas[9]
    assert resultado.areas[1] == pytest.approx(total / 2, rel=1e-3)


def test_consultas_por_feicao_sao_duas_com_varios_nos():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    nos = [(i, no(-48.31 + i * 0.001, -48.30 + i * 0.001)) for i in range(20)]
    with CaptureQueriesContext(connection) as contexto:
        resultado = sugerir_no(FEICAO, nos)
    assert len(contexto.captured_queries) == 2  # área da feição + interseções com todos os nós numa consulta
    assert resultado.sub_area_id is not None


def test_sem_nos_so_a_area_da_feicao_e_consultada():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    with CaptureQueriesContext(connection) as contexto:
        resultado = sugerir_no(FEICAO, [])
    assert len(contexto.captured_queries) == 1
    assert resultado.motivo == 'sem_intersecao'
    assert resultado.areas == {}


def test_no_fora_da_feicao_nao_entra_nas_areas():
    resultado = sugerir_no(FEICAO, [(1, no(-48.40, -48.35))])
    assert resultado.motivo == 'sem_intersecao'
    assert resultado.areas == {}
