import pytest
from django.db import IntegrityError, transaction

from territorio.models import Empresa, Fazenda, NivelDivisao, SubArea

pytestmark = pytest.mark.django_db


@pytest.fixture
def empresa():
    return Empresa.objects.create(nome='Empresa sintética A')


@pytest.fixture
def fazenda(empresa):
    return Fazenda.objects.create(empresa=empresa, nome='Fazenda sintética 1')


def _sub_area(fazenda, nivel, pai=None, empresa=None, nome='nó'):
    return SubArea.objects.create(
        empresa=empresa or fazenda.empresa, fazenda=fazenda, pai=pai, nivel=nivel, nome=nome
    )


def _recusa(**campos):
    with pytest.raises(IntegrityError), transaction.atomic():
        SubArea.objects.create(**campos)


def test_tres_niveis_com_caminho_dos_ancestrais(fazenda):
    gleba = _sub_area(fazenda, 1)
    talhao = _sub_area(fazenda, 2, pai=gleba)
    folha = _sub_area(fazenda, 3, pai=talhao)
    for no in (gleba, talhao, folha):
        no.refresh_from_db()
    assert gleba.caminho == '/'
    assert talhao.caminho == f'/{gleba.pk}/'
    assert folha.caminho == f'/{gleba.pk}/{talhao.pk}/'


def test_nivel_4_recusado(fazenda):
    gleba = _sub_area(fazenda, 1)
    talhao = _sub_area(fazenda, 2, pai=gleba)
    folha = _sub_area(fazenda, 3, pai=talhao)
    _recusa(empresa=fazenda.empresa, fazenda=fazenda, pai=folha, nivel=4, nome='quarto')


def test_pai_de_outra_fazenda_recusado(fazenda, empresa):
    outra = Fazenda.objects.create(empresa=empresa, nome='Fazenda sintética 2')
    gleba_da_outra = _sub_area(outra, 1)
    _recusa(empresa=empresa, fazenda=fazenda, pai=gleba_da_outra, nivel=2, nome='filho')


def test_fazenda_de_outra_empresa_recusada(fazenda):
    intrusa = Empresa.objects.create(nome='Empresa sintética B')
    _recusa(empresa=intrusa, fazenda=fazenda, pai=None, nivel=1, nome='raiz')


def test_nivel_incoerente_com_o_pai_recusado(fazenda):
    gleba = _sub_area(fazenda, 1)
    _recusa(empresa=fazenda.empresa, fazenda=fazenda, pai=gleba, nivel=3, nome='pulou')


def test_raiz_exige_nivel_1_e_filho_exige_pai(fazenda):
    gleba = _sub_area(fazenda, 1)
    _recusa(empresa=fazenda.empresa, fazenda=fazenda, pai=None, nivel=2, nome='órfão')
    _recusa(empresa=fazenda.empresa, fazenda=fazenda, pai=gleba, nivel=1, nome='raiz com pai')


def test_pai_nao_muda_depois_de_criado(fazenda):
    gleba = _sub_area(fazenda, 1)
    outra_gleba = _sub_area(fazenda, 1)
    talhao = _sub_area(fazenda, 2, pai=gleba)
    talhao.pai = outra_gleba
    with pytest.raises(IntegrityError), transaction.atomic():
        talhao.save()


def test_nivel_divisao_de_1_a_3_e_unico_por_empresa(empresa):
    NivelDivisao.objects.create(empresa=empresa, nivel=1, nome='gleba')
    for invalido in (0, 4):
        with pytest.raises(IntegrityError), transaction.atomic():
            NivelDivisao.objects.create(empresa=empresa, nivel=invalido, nome='x')
    with pytest.raises(IntegrityError), transaction.atomic():
        NivelDivisao.objects.create(empresa=empresa, nivel=1, nome='repetido')


def test_sub_area_nao_muda_de_fazenda_nem_de_empresa(fazenda, empresa):
    outra = Fazenda.objects.create(empresa=empresa, nome='Fazenda sintética 2')
    gleba = _sub_area(fazenda, 1)
    gleba.fazenda = outra
    with pytest.raises(IntegrityError), transaction.atomic():
        gleba.save()
    gleba.refresh_from_db()
    gleba.empresa = Empresa.objects.create(nome='Empresa sintética B')
    with pytest.raises(IntegrityError), transaction.atomic():
        gleba.save()


def test_fazenda_com_sub_area_nao_troca_de_empresa(fazenda):
    _sub_area(fazenda, 1)
    outra_empresa = Empresa.objects.create(nome='Empresa sintética B')
    with pytest.raises(IntegrityError), transaction.atomic():
        Fazenda.objects.filter(pk=fazenda.pk).update(empresa=outra_empresa)
