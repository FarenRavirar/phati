"""RLS e chave composta do catálogo (008 R11, R13): o papel `app` lê só o escopo assinado; FK composta recusa divergência.

Gravado pelo dono (conexão padrão), lido pelo papel `app` (conexão `app`), como em `permissao/testes/test_rls.py`."""

from types import SimpleNamespace

import pytest
from django.db import DatabaseError, IntegrityError, connections, transaction

from catalogo.models import AtributoVersao, Camada, Estudo, Feicao, Tema, VersaoCamada, EnvioCamada
from django.contrib.gis.geos import GEOSGeometry
from identidade.models import Pessoa
from permissao.contexto import fixar_contexto
from territorio.models import Empresa, Fazenda

pytestmark = pytest.mark.django_db(transaction=True, databases=['default', 'app'])

TABELAS = ('catalogo_estudo', 'catalogo_camada', 'catalogo_versao_camada', 'catalogo_atributo_versao',
           'catalogo_feicao', 'catalogo_envio_camada')
POLIGONO = GEOSGeometry('POLYGON((-48.30 -10.70,-48.29 -10.70,-48.29 -10.69,-48.30 -10.69,-48.30 -10.70))', srid=4674)


@pytest.fixture
def mundo(cpf_novo):
    m = SimpleNamespace()
    m.x, m.y = Empresa.objects.create(nome='Empresa X'), Empresa.objects.create(nome='Empresa Y')
    m.f1 = Fazenda.objects.create(empresa=m.x, nome='F1')
    m.f2 = Fazenda.objects.create(empresa=m.x, nome='F2')
    m.fy = Fazenda.objects.create(empresa=m.y, nome='FY')
    m.pessoa = Pessoa.objects.criar('Sintética', 's@exemplo.test', cpf_novo(), empresa_origem=m.x)
    m.tema_x = Tema.objects.create(empresa=m.x, nome='Solo')
    m.tema_y = Tema.objects.create(empresa=m.y, nome='Solo')
    m.estudo_x1 = _estudo(m.x, m.f1, m.tema_x)
    m.estudo_x2 = _estudo(m.x, m.f2, m.tema_x)
    m.estudo_y = _estudo(m.y, m.fy, m.tema_y)
    for estudo in (m.estudo_x1, m.estudo_x2, m.estudo_y):
        camada = Camada.objects.create(estudo=estudo, empresa=estudo.empresa, fazenda=estudo.fazenda, nome='C')
        versao = VersaoCamada.objects.create(
            camada=camada, empresa=estudo.empresa, fazenda=estudo.fazenda, numero=1, sistema_original='EPSG:4674', origem='Levantamento sintético',
            hash_original='a' * 64, caminho_original='originais/x.bin', enviada_por=m.pessoa)
        AtributoVersao.objects.create(versao=versao, empresa=estudo.empresa, fazenda=estudo.fazenda, nome='area')
        Feicao.objects.create(versao=versao, empresa=estudo.empresa, fazenda=estudo.fazenda, geometria=POLIGONO)
        EnvioCamada.objects.create(criado_por=m.pessoa, empresa=estudo.empresa, fazenda=estudo.fazenda,
                                   arquivo_temporario='envios/x', hash_original='0' * 64, expira_em='2030-01-01T00:00:00Z')
    return m


def _estudo(empresa, fazenda, tema):
    return Estudo.objects.create(empresa=empresa, fazenda=fazenda, tema=tema, nome=f'Estudo {fazenda.nome}')


def _ids_visiveis(tabela, *, empresas='', fazendas='', plataforma='', assinado=True):
    """Ids que o papel `app` enxerga na tabela, com as variáveis dadas. `assinado=False` fixa só as variáveis soltas."""
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        consulta.execute("SELECT set_config('app.plataforma', %s, true), set_config('app.empresas', %s, true), "
                         "set_config('app.empresas_de_fazendas', '', true), set_config('app.fazendas', %s, true)",
                         [plataforma, empresas, fazendas])
        if assinado:
            fixar_contexto(consulta, plataforma, empresas, '', fazendas)
        consulta.execute(f'SELECT id FROM {tabela}')
        return {linha[0] for linha in consulta.fetchall()}


def _ids_do_dono(tabela, **filtro):
    with connections['default'].cursor() as consulta:
        consulta.execute(f'SELECT id FROM {tabela} WHERE ' + ' AND '.join(f'{k} = %s' for k in filtro),
                         list(filtro.values()))
        return {linha[0] for linha in consulta.fetchall()}


@pytest.mark.parametrize('tabela', TABELAS)
def test_sem_assinatura_o_papel_app_le_zero_linhas(mundo, tabela):
    # Variável solta, sem `app_contexto` assinado (0004): a RLS nega, mesmo com o escopo certo na variável.
    assert _ids_visiveis(tabela, empresas=str(mundo.x.pk), assinado=False) == set()


@pytest.mark.parametrize('tabela', TABELAS)
def test_escopo_de_empresa_le_as_linhas_dela_e_so_elas(mundo, tabela):
    esperado = _ids_do_dono(tabela, empresa_id=mundo.x.pk)
    assert esperado  # o teste não passa vazio por acaso
    assert _ids_visiveis(tabela, empresas=str(mundo.x.pk)) == esperado


@pytest.mark.parametrize('tabela', TABELAS)
def test_escopo_de_outra_empresa_le_zero_linhas_dela(mundo, tabela):
    # Caso negativo: o escopo de Y não vê nada de X.
    assert not (_ids_visiveis(tabela, empresas=str(mundo.y.pk)) & _ids_do_dono(tabela, empresa_id=mundo.x.pk))


@pytest.mark.parametrize('tabela', TABELAS)
def test_escopo_de_fazenda_nao_ve_a_irma_da_mesma_empresa(mundo, tabela):
    visiveis = _ids_visiveis(tabela, fazendas=str(mundo.f1.pk))
    assert visiveis == _ids_do_dono(tabela, fazenda_id=mundo.f1.pk)
    assert not (visiveis & _ids_do_dono(tabela, fazenda_id=mundo.f2.pk))


def test_fk_composta_recusa_empresa_divergente_da_fazenda(mundo):
    # Camada com a empresa de Y, mas estudo e fazenda de X: o banco recusa, sem gatilho.
    with pytest.raises(IntegrityError), transaction.atomic():
        Camada.objects.create(estudo=mundo.estudo_x1, empresa=mundo.y, fazenda=mundo.f1, nome='divergente')


def test_fk_composta_recusa_fazenda_divergente_do_estudo(mundo):
    with pytest.raises(IntegrityError), transaction.atomic():
        Camada.objects.create(estudo=mundo.estudo_x1, empresa=mundo.x, fazenda=mundo.f2, nome='divergente')


def test_fk_composta_aceita_a_combinacao_coerente(mundo):
    camada = Camada.objects.create(estudo=mundo.estudo_x1, empresa=mundo.x, fazenda=mundo.f1, nome='coerente')
    assert camada.pk is not None


def test_insert_com_empresa_fora_do_escopo_falha_no_papel_app(mundo):
    # Escrita fora do escopo: a política também vale para INSERT (WITH CHECK implícito).
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        consulta.execute("SELECT set_config('app.plataforma', '', true), set_config('app.empresas', %s, true), "
                         "set_config('app.empresas_de_fazendas', '', true), set_config('app.fazendas', '', true)",
                         [str(mundo.x.pk)])
        fixar_contexto(consulta, '', str(mundo.x.pk), '', '')
        with pytest.raises(DatabaseError, match='row-level security'), transaction.atomic(using='app'):
            consulta.execute('INSERT INTO catalogo_tema (empresa_id, nome) VALUES (%s, %s)', [mundo.y.pk, 'fora'])


def test_estudo_com_tema_de_outra_empresa_e_recusado(mundo):
    # Revisão PR #66: o tema do estudo tem de ser da mesma empresa; FK composta (tema_id, empresa_id), sem gatilho.
    with pytest.raises(IntegrityError), transaction.atomic():
        Estudo.objects.create(empresa=mundo.x, fazenda=mundo.f1, tema=mundo.tema_y, nome='tema de outra empresa')


def test_estudo_com_fazenda_de_outra_empresa_e_recusado(mundo):
    with pytest.raises(IntegrityError), transaction.atomic():
        Estudo.objects.create(empresa=mundo.x, fazenda=mundo.fy, tema=mundo.tema_x, nome='fazenda de outra empresa')


def test_estudo_com_tema_e_fazenda_da_mesma_empresa_e_aceito(mundo):
    estudo = Estudo.objects.create(empresa=mundo.x, fazenda=mundo.f2, tema=mundo.tema_x, nome='coerente')
    assert estudo.pk is not None


def test_escopo_so_de_fazenda_le_o_tema_da_empresa(mundo):
    # Revisão PR #66: `leitura_por_fazenda` no tema. Quem tem fazenda da empresa lê o tema dela.
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        fixar_contexto(consulta, '', '', str(mundo.x.pk), str(mundo.f1.pk))
        consulta.execute('SELECT id FROM catalogo_tema')
        visiveis = {linha[0] for linha in consulta.fetchall()}
    assert visiveis == {mundo.tema_x.pk}


def test_escopo_so_de_fazenda_nao_altera_nem_cria_tema(mundo):
    # Só a leitura é por fazenda: a escrita segue a empresa. UPDATE some sem erro (0 linhas); INSERT é recusado.
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        fixar_contexto(consulta, '', '', str(mundo.x.pk), str(mundo.f1.pk))
        consulta.execute("UPDATE catalogo_tema SET nome = 'mudado' WHERE id = %s", [mundo.tema_x.pk])
        assert consulta.rowcount == 0
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        fixar_contexto(consulta, '', '', str(mundo.x.pk), str(mundo.f1.pk))
        with pytest.raises(DatabaseError, match='row-level security'), transaction.atomic(using='app'):
            consulta.execute('INSERT INTO catalogo_tema (empresa_id, nome) VALUES (%s, %s)', [mundo.x.pk, 'novo'])
    with connections['default'].cursor() as consulta:
        consulta.execute('SELECT nome FROM catalogo_tema WHERE id = %s', [mundo.tema_x.pk])
        assert consulta.fetchone()[0] == 'Solo'


def test_select_related_do_tema_no_escopo_de_fazenda(mundo):
    # O tema vem no mesmo JOIN do estudo: sem a leitura por fazenda, o INNER JOIN derrubaria o estudo.
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        fixar_contexto(consulta, '', '', str(mundo.x.pk), str(mundo.f1.pk))
        estudos = list(Estudo.objects.using('app').select_related('tema'))
    assert [e.pk for e in estudos] == [mundo.estudo_x1.pk]
    assert estudos[0].tema.nome == 'Solo'
