"""Modelos do catálogo (008 R1, R2, R10): identificador público, versão só em análise, número único, ausente ≠ zero."""

import uuid

import pytest
from django.contrib.gis.geos import GEOSGeometry
from django.db import IntegrityError, transaction

from catalogo.models import AtributoVersao, Camada, EnvioCamada, Estudo, Feicao, Tema, VersaoCamada
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
    extra.setdefault('origem', 'Levantamento sintético')
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
    assert feicao.valores['codigo'] == 0  # zero e vazio continuam distintos de ausente
    assert feicao.valores['texto'] == ''
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
    assert da_fazenda.pk  # sub_area nulo = fazenda inteira (R7)
    assert inteira.pk


def test_tema_com_nome_repetido_na_empresa_e_recusado(cenario):
    # Revisão PR #66: nome de tema único por empresa (tema_nome_unico_na_empresa).
    Tema.objects.create(empresa=cenario.x, nome='Repetido')
    with pytest.raises(IntegrityError), transaction.atomic():
        Tema.objects.create(empresa=cenario.x, nome='Repetido')


def test_tema_com_mesmo_nome_em_outra_empresa_e_aceito(cenario):
    Tema.objects.create(empresa=cenario.x, nome='Solo')
    assert Tema.objects.create(empresa=cenario.y, nome='Solo').pk is not None


def test_camada_com_nome_repetido_no_estudo_e_recusada(camada):
    # Revisão PR #66: nome de camada único por estudo (camada_nome_unico_no_estudo).
    with pytest.raises(IntegrityError), transaction.atomic():
        Camada.objects.create(estudo=camada.estudo, empresa=camada.empresa, fazenda=camada.fazenda, nome='Camada sintética')


def test_camada_com_mesmo_nome_em_outro_estudo_e_aceita(cenario, camada):
    outro = Estudo.objects.create(empresa=cenario.x, fazenda=cenario.f1, tema=camada.estudo.tema, nome='Outro estudo')
    assert Camada.objects.create(estudo=outro, empresa=cenario.x, fazenda=cenario.f1, nome='Camada sintética').pk is not None


def test_sistema_original_aceita_nome_longo_sem_teto_de_50(camada, pessoa):
    # Revisão PR #66: sistema de origem é TextField; o antigo CharField(50) recusava nomes longos.
    longo = 'Sistema de referência ' + 'x' * 180
    versao = VersaoCamada.objects.create(
        camada=camada, empresa=camada.empresa, fazenda=camada.fazenda, numero=1, sistema_original=longo,
        origem='Levantamento sintético', hash_original='a' * 64, caminho_original='originais/x.bin', enviada_por=pessoa,
    )
    versao.refresh_from_db()
    assert versao.sistema_original == longo


# Metadados de §6.2 na versão (T2.3; R8): origem obrigatória no banco, opcionais NULL, datas como data


@pytest.mark.parametrize('origem', ['', '   ', '\t\n'])
def test_origem_vazia_ou_so_espacos_e_recusada_pelo_banco(camada, pessoa, origem):
    with pytest.raises(IntegrityError), transaction.atomic():
        _versao(camada, pessoa, origem=origem)


def test_origem_preenchida_e_aceita(camada, pessoa):
    assert _versao(camada, pessoa, origem='Levantamento sintético').origem == 'Levantamento sintético'


def test_opcional_nulo_e_sem_dados_e_nao_vira_texto_vazio(camada, pessoa):
    versao = _versao(camada, pessoa)
    versao.refresh_from_db()
    assert versao.metodo is None  # NULL é "Sem dados", não ''
    assert versao.data_coleta is None
    assert versao.escala_resolucao is None


def test_data_de_metadado_e_gravada_como_data(camada, pessoa):
    from datetime import date

    versao = _versao(camada, pessoa, data_coleta=date(2026, 5, 2))
    versao.refresh_from_db()
    assert versao.data_coleta == date(2026, 5, 2)


def test_todo_opcional_da_lista_e_campo_do_modelo():
    from catalogo.metadados import OPCIONAIS

    campos = {campo.name for campo in VersaoCamada._meta.get_fields()}
    assert set(OPCIONAIS) <= campos


@pytest.mark.parametrize('hash_original', ['', 'xyz', 'A' * 64, 'a' * 63, 'g' * 64])
def test_hash_de_envio_fora_do_formato_e_recusado_pelo_banco(cenario, pessoa, hash_original):
    from django.utils import timezone

    with pytest.raises(IntegrityError), transaction.atomic():
        EnvioCamada.objects.create(criado_por=pessoa, empresa=cenario.x, fazenda=cenario.f1, arquivo_temporario='a' * 32 + '.bin',
                                   hash_original=hash_original, expira_em=timezone.now())


def test_hash_sha256_de_envio_e_aceito(cenario, pessoa):
    from django.utils import timezone

    envio = EnvioCamada.objects.create(criado_por=pessoa, empresa=cenario.x, fazenda=cenario.f1, arquivo_temporario='a' * 32 + '.bin',
                                       hash_original='0' * 64, expira_em=timezone.now())
    assert envio.hash_original == '0' * 64

