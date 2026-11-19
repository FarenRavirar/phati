"""Modelos do catálogo (008 R1, R2, R10): identificador público, versão só em análise, número único, ausente ≠ zero."""

import uuid

import pytest
from django.contrib.gis.geos import GEOSGeometry
from django.db import IntegrityError, transaction

from catalogo.models import AtributoVersao, Camada, Estudo, Feicao, Tema, VersaoCamada
from identidade.models import Pessoa

POLIGONO = 'POLYGON((-48.30 -10.70,-48.29 -10.70,-48.29 -10.69,-48.30 -10.69,-48.30 -10.70))'


@pytest.fixture
def camada(cenario):
    tema = Tema.objects.create(empresa=cenario.x, nome='Solo')
    estudo = Estudo.objects.create(empresa=cenario.x, fazenda=cenario.f1, tema=tema, nome='Estudo sintético')
    return Camada.objects.create(estudo=estudo, empresa=cenario.x, fazenda=cenario.f1, nome='Camada sintética')


@pytest.fixture
def pessoa(cenario, cpf_novo):
    return Pessoa.objects.criar('Pessoa Sintética', 'p@exemplo.test', cpf_novo(), empresa_origem=cenario.x)


def _versao(camada, pessoa, numero=1, **extra):
    return VersaoCamada.objects.create(
        camada=camada, empresa=camada.empresa, fazenda=camada.fazenda, numero=numero, sistema_original='EPSG:4674', hash_original='a' * 64,
        caminho_original='originais/x.bin', enviada_por=pessoa, **extra,
    )


def test_versao_nasce_em_analise(camada, pessoa):
    assert _versao(camada, pessoa).estado == 'em_analise'


def test_estado_diferente_de_em_analise_e_recusado_pelo_banco(camada, pessoa):
    # R2: esta spec nunca torna versão vigente; o banco recusa o estado, não só o código.
    with pytest.raises(IntegrityError), transaction.atomic():
        _versao(camada, pessoa, estado='vigente')


def test_numero_repetido_na_mesma_camada_e_recusado(camada, pessoa):
    _versao(camada, pessoa, numero=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        _versao(camada, pessoa, numero=1)


def test_mesmo_numero_em_camada_diferente_e_aceito(cenario, camada, pessoa):
    outra = Camada.objects.create(estudo=camada.estudo, empresa=camada.empresa, fazenda=camada.fazenda, nome='Outra camada')
    _versao(camada, pessoa, numero=1)
    assert _versao(outra, pessoa, numero=1).numero == 1


def test_numero_zero_e_recusado(camada, pessoa):
    with pytest.raises(IntegrityError), transaction.atomic():
        _versao(camada, pessoa, numero=0)


def test_identificador_publico_e_uuid_opaco_e_diferente_do_interno(cenario, camada):
    assert isinstance(camada.publico_id, uuid.UUID)
    assert camada.publico_id != camada.pk
    outra = Camada.objects.create(estudo=camada.estudo, empresa=camada.empresa, fazenda=camada.fazenda, nome='Outra')
    assert outra.publico_id != camada.publico_id


def test_ausente_nao_vira_zero_nos_valores_da_feicao(camada, pessoa):
    versao = _versao(camada, pessoa)
    feicao = Feicao.objects.create(
        versao=versao, empresa=versao.empresa, fazenda=versao.fazenda, geometria=GEOSGeometry(POLIGONO, srid=4674),
        valores={'area_ha': None, 'codigo': 0, 'texto': ''},
    )
    feicao.refresh_from_db()
    assert feicao.valores['area_ha'] is None  # ausente guardado como ausente
    assert feicao.valores['codigo'] == 0 and feicao.valores['texto'] == ''  # zero e vazio continuam distintos de ausente
    assert 'nao_informado' not in feicao.valores


def test_feicao_sem_geometria_e_recusada(camada, pessoa):
    versao = _versao(camada, pessoa)
    with pytest.raises(IntegrityError), transaction.atomic():
        Feicao.objects.create(versao=versao, empresa=versao.empresa, fazenda=versao.fazenda, geometria=None, valores={})


def test_geometria_guardada_em_sirgas_2000(camada, pessoa):
    versao = _versao(camada, pessoa)
    feicao = Feicao.objects.create(versao=versao, empresa=versao.empresa, fazenda=versao.fazenda, geometria=GEOSGeometry(POLIGONO, srid=4674), valores={})
    feicao.refresh_from_db()
    assert feicao.geometria.srid == 4674


def test_atributo_repetido_na_versao_e_recusado(camada, pessoa):
    versao = _versao(camada, pessoa)
    AtributoVersao.objects.create(versao=versao, empresa=versao.empresa, fazenda=versao.fazenda, nome='area_ha', rotulo='Área', unidade='ha')
    with pytest.raises(IntegrityError), transaction.atomic():
        AtributoVersao.objects.create(versao=versao, empresa=versao.empresa, fazenda=versao.fazenda, nome='area_ha')


def test_feicao_com_sub_area_de_outra_fazenda_e_recusada(cenario, camada, pessoa):
    # Regressão (008 T1.3, pendência fechada): a sub-área tem de ser da mesma fazenda da feição; o banco recusa.
    from territorio.models import SubArea
    sub_area_de_outra = SubArea.objects.create(empresa=cenario.x, fazenda=cenario.f2, nivel=1, nome='De outra fazenda')
    versao = _versao(camada, pessoa)
    with pytest.raises(IntegrityError), transaction.atomic():
        Feicao.objects.create(versao=versao, empresa=versao.empresa, fazenda=versao.fazenda, sub_area=sub_area_de_outra,
                              geometria=GEOSGeometry(POLIGONO, srid=4674), valores={})


def test_feicao_com_sub_area_da_mesma_fazenda_e_sem_sub_area_sao_aceitas(cenario, camada, pessoa):
    from territorio.models import SubArea
    sub_area = SubArea.objects.create(empresa=cenario.x, fazenda=cenario.f1, nivel=1, nome='Da fazenda')
    versao = _versao(camada, pessoa)
    da_fazenda = Feicao.objects.create(versao=versao, empresa=versao.empresa, fazenda=versao.fazenda, sub_area=sub_area,
                                       geometria=GEOSGeometry(POLIGONO, srid=4674), valores={})
    inteira = Feicao.objects.create(versao=versao, empresa=versao.empresa, fazenda=versao.fazenda, sub_area=None,
                                    geometria=GEOSGeometry(POLIGONO, srid=4674), valores={})
    assert da_fazenda.pk and inteira.pk  # sub_area nulo = fazenda inteira (R7)
