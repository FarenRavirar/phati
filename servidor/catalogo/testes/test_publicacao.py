"""Publicação de envio (008 T3.1; R4, R7, R9, R12, R13, R14, R15): caminho feliz, infeliz, RLS com papel `app`, falha no meio
e duas publicações simultâneas com transações reais. Dado sintético (R17)."""

import itertools
import uuid
import json
import threading
import time
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.contrib.gis.geos import GEOSGeometry
from django.db import connections, transaction
from django.utils import timezone

from catalogo import envios, original, publicacao
from catalogo.models import AtributoVersao, Camada, EnvioCamada, Estudo, Feicao, Tema, VersaoCamada
from catalogo.no_sugerido import contornos_da_divisao
from catalogo.publicacao import EnvioNaoEncontrado, RecusaPublicacao, publicar_envio
from catalogo.testes.test_ingestao import geojson, ponto_geojson
from comum.models import EventoAuditoria
from identidade.models import Pessoa
from permissao.models import Concessao
from permissao.pode import com_permissao
from territorio.models import SubArea

pytestmark = pytest.mark.django_db(transaction=True, databases=['default', 'app'])

METADADOS = {'nome': 'Camada sintetica', 'tema': 'Solo', 'origem': 'Levantamento sintetico'}
QUADRADO = [[-48.30, -10.70], [-48.29, -10.70], [-48.29, -10.69], [-48.30, -10.69], [-48.30, -10.70]]


@pytest.fixture
def camadas(settings, tmp_path):
    settings.CAMADAS_DIR = tmp_path / 'camadas'
    settings.CAMADAS_DIR.mkdir()
    return settings.CAMADAS_DIR


@pytest.fixture
def mundo(camadas, catalogo_da_corrida, cenario, fabrica_pessoa, conceder_direto):
    """Administrador da empresa X (com `publicar_camada`), estudo na F1, nós G1 > T1 e G2 na F1 (cenario)."""
    m = SimpleNamespace(x=cenario.x, y=cenario.y, f1=cenario.f1, f2=cenario.f2, g1=cenario.g1, t1=cenario.t1, g2=cenario.g2,
                        cargos=cenario.cargos_x)
    m.operador = fabrica_pessoa('Operadora Sintetica')
    conceder_direto(m.operador, cenario.cargos_x['administrador'], cenario.x)
    m.sem_permissao = fabrica_pessoa('Sem Permissao')
    m.tema = Tema.objects.create(empresa=cenario.x, nome='Solo')
    m.estudo = Estudo.objects.create(empresa=cenario.x, fazenda=cenario.f1, tema=m.tema, nome='Estudo F1')
    return m


def _pontos():
    """Duas feições: valor 0 e valor ausente (R10), e um atributo de texto que pode ser ocultado (R9)."""
    return geojson([
        {'type': 'Feature', 'properties': {'valor': 0, 'obs': 'sintetico'},
         'geometry': {'type': 'Point', 'coordinates': [-48.3, -10.7]}},
        {'type': 'Feature', 'properties': {'valor': None, 'obs': None},
         'geometry': {'type': 'Point', 'coordinates': [-48.29, -10.69]}},
    ])


BIG = [[-48.40, -10.80], [-48.20, -10.80], [-48.20, -10.60], [-48.40, -10.60], [-48.40, -10.80]]  # contém QUADRADO
FAR = [[-47.00, -9.00], [-46.90, -9.00], [-46.90, -8.90], [-47.00, -8.90], [-47.00, -9.00]]  # longe de QUADRADO


def _divisao(mapa):
    """Divisão sintética: {nome do nó: anel}. A coluna 'no' traz o nome; a geometria é o contorno do nó (D119)."""
    return geojson([
        {'type': 'Feature', 'properties': {'no': nome}, 'geometry': {'type': 'Polygon', 'coordinates': [anel]}}
        for nome, anel in mapa.items()
    ])


def _poligonos(quantidade=2):
    return geojson([
        {'type': 'Feature', 'properties': {'valor': n}, 'geometry': {'type': 'Polygon', 'coordinates': [QUADRADO]}}
        for n in range(quantidade)
    ])


def _criar(mundo, dados=None, pessoa=None, fazenda=None):
    return envios.criar_envio(pessoa or mundo.operador, fazenda or mundo.f1, dados if dados is not None else _pontos())


def _publicar(mundo, envio, pessoa=None, nome=None, **kwargs):
    kwargs.setdefault('nos', [mundo.g1.pk, mundo.g1.pk])
    kwargs.setdefault('sistema_confirmado', True)
    metadados = {**METADADOS, 'nome': nome} if nome else dict(METADADOS)
    return publicar_envio(pessoa or mundo.operador, envio.pk, estudo_id=mundo.estudo.pk, metadados=metadados, **kwargs)


@contextmanager
def _papel_app():
    """Como `como_app`, mas só no trecho que publica: a montagem do cenário grava com o dono, sem RLS."""
    dono = connections['default']
    connections['default'] = connections['app']
    try:
        yield
    finally:
        connections['default'] = dono


def _arquivar(no, mundo):
    """Arquiva o nó com as três colunas juntas, como a CHECK `sub_area_arquivamento_coerente` exige."""
    SubArea.objects.filter(pk=no.pk).update(arquivada_em=timezone.now(), arquivada_por=mundo.sem_permissao, arquivamento=uuid.uuid4())


def _contagem():
    """Linhas de tudo que a publicação toca. Falha no meio tem de deixar tudo igual (R13)."""
    return (VersaoCamada.objects.count(), Feicao.objects.count(), AtributoVersao.objects.count(), Camada.objects.count(),
            EventoAuditoria.objects.count(), EnvioCamada.objects.count())


def _eventos(acao):
    return list(EventoAuditoria.objects.filter(acao=acao).order_by('id'))


# --- caminho feliz ---------------------------------------------------------------------------------------------------

def test_publica_em_analise_guarda_original_e_consome_o_envio(camadas, mundo):
    envio = _criar(mundo)
    nome_original, hash_original = envio.arquivo_temporario, envio.hash_original
    versao = _publicar(mundo, envio, nos=[mundo.g1.pk, mundo.g1.pk])
    assert versao.estado == 'em_analise'  # R2: nunca vigente
    assert versao.numero == 1
    assert versao.hash_original == hash_original
    assert versao.caminho_original == nome_original  # R15: o original é a versão, não some
    assert versao.sistema_original.startswith('EPSG:4326')
    assert versao.origem == 'Levantamento sintetico'
    assert Feicao.objects.filter(versao=versao).count() == 2
    assert not EnvioCamada.objects.filter(pk=envio.pk).exists()  # consumido só no sucesso
    assert (camadas / nome_original).exists()
    assert original.ler(nome_original, hash_original)  # confere ainda com o hash da versão


def test_ausente_fica_ausente_e_zero_fica_zero(camadas, mundo):
    versao = _publicar(mundo, _criar(mundo))
    valores = [f.valores for f in Feicao.objects.filter(versao=versao).order_by('id')]
    assert valores[0]['valor'] is not None  # zero não vira ausente
    assert valores[0]['valor'] == 0  # zero continua zero
    assert valores[1]['valor'] is None  # ausente continua ausente, nunca vira 0 ou texto vazio (R10)


def test_sistema_diferente_de_sirgas_so_publica_com_confirmacao(camadas, mundo):
    envio = _criar(mundo)
    antes = _contagem()
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio, sistema_confirmado=False)
    assert 'exige confirmação' in excinfo.value.erros[0]
    assert _contagem() == antes
    assert EnvioCamada.objects.filter(pk=envio.pk).exists()
    versao = _publicar(mundo, envio, sistema_confirmado=True)
    assert len(_eventos('sistema_confirmado')) == 1
    assert _eventos('sistema_confirmado')[0].detalhes['sistema'].startswith('EPSG:4326')
    assert versao.pk


def test_sirgas_no_arquivo_publica_sem_confirmar(camadas, mundo):
    envio = _criar(mundo, geojson([ponto_geojson()], crs='urn:ogc:def:crs:EPSG::4674'))
    _publicar(mundo, envio, nos=[mundo.g1.pk], sistema_confirmado=False)
    assert _eventos('sistema_confirmado') == []  # sem transformação, sem confirmação exigida (R4)


def test_nova_versao_da_mesma_camada_recebe_o_numero_seguinte(camadas, mundo):
    primeira = _publicar(mundo, _criar(mundo))
    camada = primeira.camada
    segunda = _publicar(mundo, _criar(mundo), camada_id=camada.pk)
    assert (primeira.numero, segunda.numero) == (1, 2)
    assert Camada.objects.filter(estudo=mundo.estudo).count() == 1  # não criou camada nova


def test_atributo_oculto_fica_invisivel_guarda_valor_e_audita_sem_valor(camadas, mundo):
    versao = _publicar(mundo, _criar(mundo), ocultos=('obs',))
    assert not AtributoVersao.objects.get(versao=versao, nome='obs').visivel
    assert AtributoVersao.objects.get(versao=versao, nome='valor').visivel
    evento = _eventos('atributo_ocultado')
    assert len(evento) == 1
    assert evento[0].detalhes == {'nome_atributo': 'obs', 'versao': 1, 'camada': versao.camada_id}
    assert 'sintetico' not in json.dumps(evento[0].detalhes)  # R14: sem valor de atributo no detalhe


def test_troca_de_no_sugerido_e_auditada_em_um_evento_com_a_contagem(camadas, mundo):
    _publicar(mundo, _criar(mundo, _divisao({'G1': BIG, 'G2': FAR})), nos=(), coluna_no='no', nome='Divisao')
    envio = _criar(mundo, _poligonos(3))
    versao = _publicar(mundo, envio, nos=[mundo.g2.pk, mundo.g2.pk, mundo.g1.pk])
    evento = _eventos('no_trocado')
    assert len(evento) == 1  # R14: um evento por publicação, não um por feição
    assert evento[0].detalhes == {'camada': versao.camada_id, 'versao': 1, 'quantidade': 2}


def test_sem_contornos_nao_ha_sugestao_nem_troca(camadas, mundo):
    envio = _criar(mundo, _poligonos())
    _publicar(mundo, envio, nos=[mundo.g2.pk, mundo.g1.pk])
    assert _eventos('no_trocado') == []


# --- caminho infeliz -------------------------------------------------------------------------------------------------

def test_envio_inexistente_responde_nao_encontrado_sem_gravar(camadas, mundo):
    antes = _contagem()
    with pytest.raises(EnvioNaoEncontrado):
        publicar_envio(mundo.operador, 999_999, estudo_id=mundo.estudo.pk, metadados=dict(METADADOS), nos=[mundo.g1.pk, mundo.g1.pk])
    assert _contagem() == antes


def test_sem_permissao_recebe_a_mesma_resposta_do_inexistente(camadas, mundo):
    envio = _criar(mundo)
    antes = _contagem()
    with pytest.raises(EnvioNaoEncontrado) as excinfo:
        _publicar(mundo, envio, pessoa=mundo.sem_permissao)
    assert str(excinfo.value) == ''  # mesma exceção sem detalhe do inexistente (R11)
    assert _contagem() == antes
    assert EnvioCamada.objects.filter(pk=envio.pk).exists()


def test_permissao_revogada_entre_previa_e_confirmacao_recusa(camadas, mundo):
    envio = _criar(mundo)  # `operador` carrega a memória de permissão até aqui
    Concessao.objects.filter(pessoa=mundo.operador).delete()
    antes = _contagem()
    with pytest.raises(EnvioNaoEncontrado):
        _publicar(mundo, envio)
    assert _contagem() == antes


def test_envio_expirado_recusa_e_mantem_o_envio(camadas, mundo):
    envio = _criar(mundo)
    antes = _contagem()
    depois = timezone.now() + timedelta(hours=25)
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio, agora=depois)
    assert excinfo.value.erros == ['envio expirado: envie o arquivo de novo']
    assert _contagem() == antes


def test_original_alterado_recusa_sem_criar_nada(camadas, mundo):
    envio = _criar(mundo)
    (camadas / envio.arquivo_temporario).write_bytes(b'alterado')
    antes = _contagem()
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio)
    assert excinfo.value.erros == ['original não confere com o hash guardado no envio']
    assert _contagem() == antes
    assert EnvioCamada.objects.filter(pk=envio.pk).exists()


def test_no_de_outra_fazenda_recusa(camadas, mundo):
    no_f2 = SubArea.objects.create(empresa=mundo.x, fazenda=mundo.f2, nivel=1, nome='G-F2')
    envio = _criar(mundo)
    antes = _contagem()
    with pytest.raises(RecusaPublicacao):
        _publicar(mundo, envio, nos=[no_f2.pk, no_f2.pk])
    assert _contagem() == antes


def test_no_arquivado_entre_previa_e_confirmacao_recusa(camadas, mundo):
    envio = _criar(mundo)
    _arquivar(mundo.g1, mundo)
    antes = _contagem()
    with pytest.raises(RecusaPublicacao):
        _publicar(mundo, envio, nos=[mundo.g1.pk, mundo.g1.pk])
    assert _contagem() == antes


def test_no_com_ancestral_arquivado_recusa(camadas, mundo):
    envio = _criar(mundo)
    _arquivar(mundo.g1, mundo)  # T1 é filho de G1
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio, nos=[mundo.t1.pk, mundo.t1.pk])
    assert 'ancestral arquivado' in excinfo.value.erros[0]


def test_feicao_fora_de_todo_no_fica_na_fazenda_mesmo_com_nos_na_fazenda(camadas, mundo):
    # Decisão do mantenedor: feição fora de todos os nós fica na própria fazenda (nó None) e a publicação não exige escolha.
    envio = _criar(mundo)
    publicada = _publicar(mundo, envio, nos=[None, mundo.g1.pk])
    assert publicada.numero == 1
    gravadas = Feicao.objects.filter(versao=publicada).order_by('id').values_list('sub_area_id', flat=True)
    assert list(gravadas) == [None, mundo.g1.pk]  # na ordem de gravação: a da fazenda e a do nó 1


def test_quantidade_de_nos_diferente_das_feicoes_recusa(camadas, mundo):
    envio = _criar(mundo)
    with pytest.raises(RecusaPublicacao):
        _publicar(mundo, envio, nos=[mundo.g1.pk])


def test_tema_do_arquivo_diferente_do_estudo_recusa(camadas, mundo):
    envio = _criar(mundo)
    antes = _contagem()
    with pytest.raises(RecusaPublicacao) as excinfo:
        publicar_envio(mundo.operador, envio.pk, estudo_id=mundo.estudo.pk, nos=[mundo.g1.pk, mundo.g1.pk],
                       metadados={**METADADOS, 'tema': 'Outro'}, sistema_confirmado=True)
    assert excinfo.value.erros == ['tema do arquivo diferente do tema do estudo']
    assert _contagem() == antes


def test_atributo_a_ocultar_inexistente_recusa(camadas, mundo):
    envio = _criar(mundo)
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio, ocultos=('nao_existe',))
    assert excinfo.value.erros == ['atributo a ocultar não existe no arquivo']


def test_nome_de_camada_ja_existente_sem_camada_id_recusa(camadas, mundo):
    _publicar(mundo, _criar(mundo))
    envio = _criar(mundo)
    antes = _contagem()
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio)
    assert excinfo.value.erros == ['já existe camada com este nome neste estudo']
    assert _contagem() == antes


def test_camada_de_outro_estudo_recusa(camadas, mundo):
    primeira = _publicar(mundo, _criar(mundo))
    outro = Estudo.objects.create(empresa=mundo.x, fazenda=mundo.f1, tema=mundo.tema, nome='Outro estudo')
    envio = _criar(mundo)
    with pytest.raises(RecusaPublicacao):
        publicar_envio(mundo.operador, envio.pk, estudo_id=outro.pk, metadados=dict(METADADOS), nos=[mundo.g1.pk, mundo.g1.pk],
                       camada_id=primeira.camada_id, sistema_confirmado=True)


def test_falha_no_meio_deixa_o_banco_como_estava_e_o_envio_serve_de_novo(camadas, mundo, monkeypatch):
    envio = _criar(mundo)
    antes = _contagem()
    arquivos = sorted(p.name for p in camadas.iterdir())
    def falha(*_a, **_k):
        raise RuntimeError('falha simulada no meio')

    monkeypatch.setattr(Feicao.objects, 'bulk_create', falha)
    with pytest.raises(RuntimeError):
        _publicar(mundo, envio)
    assert _contagem() == antes  # versão, atributos e camada já criados também somem
    assert sorted(p.name for p in camadas.iterdir()) == arquivos
    monkeypatch.undo()
    assert _publicar(mundo, envio).numero == 1  # o envio não foi consumido


# --- controle de acesso pelo papel `app` (RLS, R11) ------------------------------------------------------------------

def test_publica_com_o_papel_app_e_a_auditoria_passa_pela_rls(camadas, mundo):
    envio = _criar(mundo)
    with _papel_app():
        versao = _publicar(mundo, envio, ocultos=('obs',))
    assert versao.estado == 'em_analise'
    assert len(_eventos('camada_publicada')) == 1


def test_publicador_de_outra_empresa_nao_publica_envio_de_x_pelo_papel_app(camadas, mundo, fabrica_pessoa, conceder_direto,
                                                                          cenario):
    intruso = fabrica_pessoa('Intrusa de Y')
    conceder_direto(intruso, cenario.cargos_y['administrador'], cenario.y)
    envio = _criar(mundo)
    antes = _contagem()
    with _papel_app(), pytest.raises(EnvioNaoEncontrado):
        _publicar(mundo, envio, pessoa=intruso)
    assert _contagem() == antes


def test_escopo_so_de_outra_fazenda_nao_publica_pelo_papel_app(camadas, mundo, fabrica_pessoa, conceder_direto):
    so_f2 = fabrica_pessoa('Operadora so de F2')
    conceder_direto(so_f2, mundo.cargos['administrador'], mundo.f2)  # concessão só da F2
    envio = _criar(mundo)  # envio da F1
    antes = _contagem()
    with _papel_app(), pytest.raises(EnvioNaoEncontrado):
        _publicar(mundo, envio, pessoa=so_f2)
    assert _contagem() == antes


# --- duas publicações simultâneas (transações reais, R13) ------------------------------------------------------------

ESPERA_DE_TRAVA = '10s'  # teto de espera de trava por conexão de teste: um impasse vira erro, não teste pendurado


def _rodar_em_threads(alvos):
    """Roda cada função em sua thread, com conexões próprias, e devolve (resultado ou exceção) por thread.

    Cada conexão recebe `lock_timeout`: espera de trava acima dele vira erro de banco, em vez de travar o teste. Thread
    ainda viva depois do `join` falha o teste explicitamente."""
    barreira = threading.Barrier(len(alvos))
    resultados: list[object] = [None] * len(alvos)

    def corre(indice, alvo):
        try:
            try:
                for alias in connections:
                    with connections[alias].cursor() as cursor:
                        cursor.execute(f"SET lock_timeout = '{ESPERA_DE_TRAVA}'")
            except BaseException:
                barreira.abort()  # falha de preparo: as outras threads recebem BrokenBarrierError, não ficam presas
                raise
            barreira.wait(timeout=30)
            resultados[indice] = alvo()
        except BaseException as erro:  # noqa: BLE001 — o teste confere o que cada thread recebeu
            resultados[indice] = erro
        finally:
            connections.close_all()

    fios = [threading.Thread(target=corre, args=(i, alvo)) for i, alvo in enumerate(alvos)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join(timeout=60)
    vivas = [fio.name for fio in fios if fio.is_alive()]
    assert not vivas, f'thread ainda viva depois de 60 s: {vivas}'
    return resultados


def test_falha_de_preparo_numa_thread_nao_deixa_a_outra_presa_na_barreira(monkeypatch):
    """Achado CodeRabbit: a barreira sem timeout deixava as outras threads presas se uma falhasse ao preparar a conexão."""
    chamadas = []

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql):
            chamadas.append(sql)
            if len(chamadas) == 1:  # só a primeira preparação falha
                raise RuntimeError('preparo falhou')

    class _Conexao:
        def cursor(self):
            return _Cursor()

    class _Conexoes:
        def __iter__(self):
            return iter(['default'])

        def __getitem__(self, alias):
            return _Conexao()

        def close_all(self):
            pass

    monkeypatch.setitem(globals(), 'connections', _Conexoes())
    inicio = time.monotonic()
    resultados = _rodar_em_threads([lambda: 'ok', lambda: 'ok'])
    assert time.monotonic() - inicio < 20, 'a outra thread ficou presa na barreira'
    erros = [r for r in resultados if isinstance(r, BaseException)]
    assert any(isinstance(e, RuntimeError) and str(e) == 'preparo falhou' for e in erros), resultados
    assert all(isinstance(e, (RuntimeError, threading.BrokenBarrierError)) for e in erros), resultados


def _atrasar_a_primeira_numeracao(monkeypatch, atraso=0.5):
    """Segura a primeira publicação logo depois de calcular o número, para a outra entrar no meio."""
    original_numero = publicacao._proximo_numero
    primeira = itertools.count()

    def numero_com_atraso(camada):
        valor = original_numero(camada)
        if next(primeira) == 0:
            time.sleep(atraso)
        return valor

    monkeypatch.setattr(publicacao, '_proximo_numero', numero_com_atraso)


def _publicador(mundo, envio_pk, **kwargs):
    def publicar():
        pessoa = Pessoa.objects.get(pk=mundo.operador.pk)
        kwargs.setdefault('nos', [mundo.g1.pk, mundo.g1.pk])
        return publicar_envio(pessoa, envio_pk, estudo_id=mundo.estudo.pk, metadados=dict(METADADOS),
                              sistema_confirmado=True, **kwargs)
    return publicar


def test_mesmo_envio_publicado_duas_vezes_publica_uma(camadas, mundo, monkeypatch):
    envio = _criar(mundo)
    _atrasar_a_primeira_numeracao(monkeypatch)
    resultados = _rodar_em_threads([_publicador(mundo, envio.pk), _publicador(mundo, envio.pk)])
    publicadas = [r for r in resultados if isinstance(r, VersaoCamada)]
    recusadas = [r for r in resultados if isinstance(r, EnvioNaoEncontrado)]
    assert len(publicadas) == 1, resultados
    assert len(recusadas) == 1, resultados
    assert VersaoCamada.objects.count() == 1  # o envio não gera duas versões


def test_dois_envios_da_mesma_camada_geram_numeros_distintos(camadas, mundo, monkeypatch):
    primeira = _publicar(mundo, _criar(mundo))
    envio_a, envio_b = _criar(mundo), _criar(mundo)
    _atrasar_a_primeira_numeracao(monkeypatch)
    alvo = lambda envio: _publicador(mundo, envio.pk, camada_id=primeira.camada_id)
    resultados = _rodar_em_threads([alvo(envio_a), alvo(envio_b)])
    assert all(isinstance(r, VersaoCamada) for r in resultados), resultados
    numeros = sorted(v.numero for v in VersaoCamada.objects.filter(camada_id=primeira.camada_id))
    assert numeros == [1, 2, 3]  # sem a trava no estudo, as duas pegam o mesmo máximo e uma falha


# --- divisão da fazenda (D119): marcação, sugestão pelos contornos publicados ----------------------------------------

def test_marca_divisao_e_liga_cada_feicao_ao_no_pelo_nome(camadas, mundo):
    antes = (Tema.objects.count(), Estudo.objects.count())  # D119: tema e estudo são só lidos, nunca criados
    versao = _publicar(mundo, _criar(mundo, _divisao({'G1': BIG, 'G2': FAR})), nos=(), coluna_no='no', nome='Divisao')
    assert (Tema.objects.count(), Estudo.objects.count()) == antes
    assert Camada.objects.get(pk=versao.camada_id).coluna_no == 'no'
    ligadas = {f.valores['no']: f.sub_area_id for f in Feicao.objects.filter(versao=versao)}
    assert ligadas == {'G1': mundo.g1.pk, 'G2': mundo.g2.pk}


def test_duas_divisoes_na_mesma_fazenda_recusam(camadas, mundo):
    _publicar(mundo, _criar(mundo, _divisao({'G1': BIG})), nos=(), coluna_no='no', nome='Divisao')
    outro = Estudo.objects.create(empresa=mundo.x, fazenda=mundo.f1, tema=mundo.tema, nome='Outro estudo')
    envio = _criar(mundo, _divisao({'G2': FAR}))
    antes = _contagem()
    with pytest.raises(RecusaPublicacao) as excinfo:
        publicar_envio(mundo.operador, envio.pk, estudo_id=outro.pk, metadados={**METADADOS, 'nome': 'Outra'},
                       nos=(), coluna_no='no', sistema_confirmado=True)
    assert excinfo.value.erros == ['já existe divisão desta fazenda']
    assert _contagem() == antes


def test_divisao_de_outra_fazenda_nao_conflita_com_a_de_f1(camadas, mundo):
    _publicar(mundo, _criar(mundo, _divisao({'G1': BIG})), nos=(), coluna_no='no', nome='Divisao F1')
    estudo_f2 = Estudo.objects.create(empresa=mundo.x, fazenda=mundo.f2, tema=mundo.tema, nome='Estudo F2')
    no_f2 = SubArea.objects.create(empresa=mundo.x, fazenda=mundo.f2, nivel=1, nome='GF2')
    envio = _criar(mundo, _divisao({'GF2': FAR}), fazenda=mundo.f2)
    versao = publicar_envio(mundo.operador, envio.pk, estudo_id=estudo_f2.pk, metadados={**METADADOS, 'nome': 'Divisao F2'},
                            nos=(), coluna_no='no', sistema_confirmado=True)
    assert Feicao.objects.get(versao=versao).sub_area_id == no_f2.pk


def test_nome_sem_correspondente_recusa_a_marcacao_sem_gravar(camadas, mundo):
    envio = _criar(mundo, _divisao({'G1': BIG, 'X9': FAR}))
    antes = _contagem()
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio, nos=(), coluna_no='no', nome='Divisao')
    assert excinfo.value.erros == ['feição 2: nome do nó sem correspondente na fazenda']
    assert _contagem() == antes
    assert EnvioCamada.objects.filter(pk=envio.pk).exists()


def test_nome_de_no_repetido_na_fazenda_recusa_a_marcacao(camadas, mundo):
    SubArea.objects.create(empresa=mundo.x, fazenda=mundo.f1, pai=mundo.g2, nivel=2, nome='G1')  # mesmo nome, outro ramo
    envio = _criar(mundo, _divisao({'G1': BIG}))
    antes = _contagem()
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio, nos=(), coluna_no='no', nome='Divisao')
    assert excinfo.value.erros == ['nome de nó repetido na fazenda: a divisão não pode ser marcada']
    assert _contagem() == antes


def test_coluna_do_no_inexistente_recusa(camadas, mundo):
    envio = _criar(mundo, _divisao({'G1': BIG}))
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio, nos=(), coluna_no='nao_existe', nome='Divisao')
    assert excinfo.value.erros == ['coluna do nó não existe no arquivo']


def test_no_escolhido_diferente_do_nome_na_coluna_recusa(camadas, mundo):
    envio = _criar(mundo, _divisao({'G1': BIG, 'G2': FAR}))
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio, nos=[mundo.g2.pk, mundo.g2.pk], coluna_no='no', nome='Divisao')
    assert excinfo.value.erros == ['nó escolhido diverge do nome na coluna marcada']


def test_camada_marcada_sem_a_coluna_do_no_recusa(camadas, mundo):
    primeira = _publicar(mundo, _criar(mundo, _divisao({'G1': BIG})), nos=(), coluna_no='no', nome='Divisao')
    envio = _criar(mundo, _divisao({'G1': BIG}))
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio, nos=[mundo.g1.pk], camada_id=primeira.camada_id, nome='Divisao')
    assert excinfo.value.erros == ['camada é a divisão da fazenda: publique com a coluna do nó marcada']


def test_sugestao_por_maior_area_usa_a_divisao_publicada(camadas, mundo):
    _publicar(mundo, _criar(mundo, _divisao({'G1': BIG, 'G2': FAR})), nos=(), coluna_no='no', nome='Divisao')
    versao = _publicar(mundo, _criar(mundo, _poligonos(1)), nos=[mundo.g2.pk])  # o contorno de G1 cobre a feição
    evento = _eventos('no_trocado')
    assert len(evento) == 1
    assert evento[0].detalhes['quantidade'] == 1
    assert evento[0].detalhes['camada'] == versao.camada_id


def test_empate_entre_dois_nos_nao_sugere_e_nao_audita_troca(camadas, mundo):
    _publicar(mundo, _criar(mundo, _divisao({'G1': BIG, 'T1': BIG})), nos=(), coluna_no='no', nome='Divisao')
    _publicar(mundo, _criar(mundo, _poligonos(1)), nos=[mundo.g2.pk])
    assert _eventos('no_trocado') == []  # áreas iguais: sem sugestão, o Administrador escolhe (R7)


def test_sugestao_usa_a_versao_mais_recente_da_divisao(camadas, mundo):
    v1 = _publicar(mundo, _criar(mundo, _divisao({'G1': BIG, 'G2': FAR})), nos=(), coluna_no='no', nome='Divisao')
    _publicar(mundo, _criar(mundo, _divisao({'G1': FAR, 'G2': BIG})), nos=(), coluna_no='no', camada_id=v1.camada_id,
              nome='Divisao')
    versao = _publicar(mundo, _criar(mundo, _poligonos(1)), nos=[mundo.g1.pk])  # a v2 põe o contorno de G2 sobre a feição
    evento = _eventos('no_trocado')
    assert len(evento) == 1
    assert evento[0].detalhes['quantidade'] == 1
    assert evento[0].detalhes['camada'] == versao.camada_id


def test_contornos_da_divisao_respeitam_o_escopo_do_chamador(camadas, mundo, fabrica_pessoa, conceder_direto):
    _publicar(mundo, _criar(mundo, _divisao({'G1': BIG})), nos=(), coluna_no='no', nome='Divisao')
    so_f2 = fabrica_pessoa('So F2')
    conceder_direto(so_f2, mundo.cargos['administrador'], mundo.f2)
    with _papel_app(), com_permissao(so_f2, 'ver'):
        assert contornos_da_divisao(mundo.f1) == {}  # fora do escopo: a RLS não traz a divisão da F1
    with _papel_app(), com_permissao(mundo.operador, 'ver'):
        assert set(contornos_da_divisao(mundo.f1)) == {mundo.g1.pk}


def test_divisao_de_pontos_ou_linhas_e_recusada_sem_gravar(camadas, mundo):
    ponto = geojson([{'type': 'Feature', 'properties': {'no': 'G1'}, 'geometry': {'type': 'Point', 'coordinates': [-48.3, -10.7]}}])
    envio = _criar(mundo, ponto)
    antes = _contagem()
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio, nos=(), coluna_no='no', nome='Divisao')
    assert excinfo.value.erros == ['a divisão da fazenda precisa de polígonos, não de ponto']
    assert _contagem() == antes
    linha = geojson([{'type': 'Feature', 'properties': {'no': 'G1'}, 'geometry': {'type': 'LineString',
                      'coordinates': [[-48.3, -10.7], [-48.29, -10.69]]}}])
    envio_linha = _criar(mundo, linha)
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio_linha, nos=(), coluna_no='no', nome='Divisao')
    assert excinfo.value.erros == ['a divisão da fazenda precisa de polígonos, não de linha']


def test_divisao_de_poligonos_e_aceita(camadas, mundo):
    versao = _publicar(mundo, _criar(mundo, _divisao({'G1': BIG})), nos=(), coluna_no='no', nome='Divisao')
    assert versao.estado == 'em_analise'


def test_corrida_entre_estudos_da_mesma_fazenda_marca_so_uma_divisao(camadas, mundo, monkeypatch):
    """Duas threads, estudos diferentes, mesma fazenda. Sincronizadas: a primeira gravação da divisão espera a segunda
    passar pelo `exists()` (que ainda não vê nada) e gravar. Quem grava depois bate no índice único parcial."""
    outro = Estudo.objects.create(empresa=mundo.x, fazenda=mundo.f1, tema=mundo.tema, nome='Estudo corrida')
    envio_a, envio_b = _criar(mundo, _divisao({'G1': BIG})), _criar(mundo, _divisao({'G2': FAR}))
    gravacao_original = Camada.save
    segunda_passou = threading.Event()
    gravacoes = itertools.count()

    def gravar_com_pausa(self, *args, **kwargs):
        if 'update_fields' in kwargs:  # só a marcação da divisão (create() também chama save)
            if next(gravacoes) == 0:
                # Pausa curta: a trava dos nós da fazenda (008 T3.1) faz a segunda publicação esperar esta; a pausa
                # precisa ficar abaixo do lock_timeout do teste (10 s), senão a espera vira erro de banco.
                segunda_passou.wait(timeout=1)
            else:
                segunda_passou.set()
        return gravacao_original(self, *args, **kwargs)

    monkeypatch.setattr(Camada, 'save', gravar_com_pausa)

    def publicador(envio, estudo_pk, nome):
        def publicar():
            pessoa = Pessoa.objects.get(pk=mundo.operador.pk)
            return publicar_envio(pessoa, envio.pk, estudo_id=estudo_pk, metadados={**METADADOS, 'nome': nome},
                                  nos=(), coluna_no='no', sistema_confirmado=True)
        return publicar

    resultados = _rodar_em_threads([publicador(envio_a, mundo.estudo.pk, 'Div A'), publicador(envio_b, outro.pk, 'Div B')])
    publicadas = [r for r in resultados if isinstance(r, VersaoCamada)]
    recusadas = [r for r in resultados if isinstance(r, RecusaPublicacao)]
    assert len(publicadas) == 1, resultados
    assert len(recusadas) == 1, resultados
    assert recusadas[0].erros == ['já existe divisão desta fazenda']
    assert Camada.objects.filter(fazenda=mundo.f1, coluna_no__isnull=False).count() == 1


# --- trava x revogação, arquivamento, limpeza e expiração (R13) ---------------------------------------------------------

def _capturar(alvo):
    try:
        return alvo()
    except BaseException as erro:  # noqa: BLE001 — o teste confere o que cada thread recebeu
        return erro
    finally:
        connections.close_all()


def _esperar_trava(timeout=10):
    """Espera até alguma sessão do banco ficar bloqueada por trava (pg_stat_activity), sem depender de tempo fixo."""
    prazo = time.monotonic() + timeout
    while time.monotonic() < prazo:
        with connections['default'].cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND datname = current_database()")
            if cursor.fetchone()[0]:
                return True
        time.sleep(0.05)
    return False


def _travar_envio(envio_pk, segurando, soltar):
    """Thread que trava o envio numa transação até `soltar`: a publicação concorrente fica esperando a trava."""
    def segura():
        try:
            with transaction.atomic():
                EnvioCamada.objects.select_for_update().get(pk=envio_pk)
                segurando.set()
                soltar.wait(timeout=30)
        finally:
            connections.close_all()
    return segura


def test_revogacao_durante_a_espera_da_trava_impede_a_publicacao(camadas, mundo):
    envio = _criar(mundo)
    antes = _contagem()
    segurando, soltar = threading.Event(), threading.Event()
    dono = threading.Thread(target=_travar_envio(envio.pk, segurando, soltar))
    dono.start()
    assert segurando.wait(timeout=10)
    resultados = []
    publicadora = threading.Thread(target=lambda: resultados.append(_capturar(_publicador(mundo, envio.pk))))
    publicadora.start()
    assert _esperar_trava(), 'a publicação não chegou à trava'  # ela já leu a permissão antes de esperar
    Concessao.objects.filter(pessoa=mundo.operador).delete()  # revoga enquanto espera
    soltar.set()
    dono.join(timeout=10)
    publicadora.join(timeout=10)
    assert not publicadora.is_alive()
    assert isinstance(resultados[0], EnvioNaoEncontrado), resultados
    assert _contagem() == antes  # sem versão, feição, atributo, camada nem auditoria


def test_arquivamento_durante_a_publicacao_espera_a_trava(camadas, mundo, monkeypatch):
    envio = _criar(mundo)
    pausado, arquivou = threading.Event(), threading.Event()
    visto_na_publicacao = []
    numero_original = publicacao._proximo_numero

    def numero_com_pausa(camada):
        valor = numero_original(camada)  # os nós já estão travados aqui
        pausado.set()
        arquivou.wait(timeout=3)
        visto_na_publicacao.append(arquivou.is_set())
        return valor

    monkeypatch.setattr(publicacao, '_proximo_numero', numero_com_pausa)

    def arquiva():
        try:
            _arquivar(mundo.g1, mundo)
        finally:
            arquivou.set()
            connections.close_all()

    resultados = []
    publicadora = threading.Thread(target=lambda: resultados.append(_capturar(_publicador(mundo, envio.pk))))
    publicadora.start()
    assert pausado.wait(timeout=10)
    arquivadora = threading.Thread(target=arquiva)
    arquivadora.start()
    publicadora.join(timeout=30)
    arquivadora.join(timeout=30)
    assert not publicadora.is_alive() and not arquivadora.is_alive()
    assert visto_na_publicacao == [False], 'o arquivamento não podia terminar durante a publicação'
    assert isinstance(resultados[0], VersaoCamada), resultados
    assert SubArea.objects.get(pk=mundo.g1.pk).arquivada_em is not None


def test_limpeza_de_vencidos_pula_envio_em_publicacao(camadas, mundo, monkeypatch):
    envio = _criar(mundo)
    antes_do_vencimento = timezone.now()
    depois_do_vencimento = antes_do_vencimento + timedelta(hours=48)
    pausado, liberar = threading.Event(), threading.Event()
    numero_original = publicacao._proximo_numero

    def numero_com_pausa(camada):
        valor = numero_original(camada)
        pausado.set()
        liberar.wait(timeout=30)
        return valor

    monkeypatch.setattr(publicacao, '_proximo_numero', numero_com_pausa)
    resultados = []
    publicadora = threading.Thread(
        target=lambda: resultados.append(_capturar(_publicador(mundo, envio.pk, agora=antes_do_vencimento))))
    publicadora.start()
    assert pausado.wait(timeout=10)
    # A publicação começou antes do vencimento e segura a trava: a limpeza pula o envio e o original fica.
    assert envios.limpar_expirados(mundo.operador, depois_do_vencimento) == (0, 1)
    liberar.set()
    publicadora.join(timeout=30)
    assert not publicadora.is_alive()
    versao = resultados[0]
    assert isinstance(versao, VersaoCamada), resultados
    assert (camadas / versao.caminho_original).exists()  # sem versão apontando para arquivo apagado
    assert original.ler(versao.caminho_original, versao.hash_original)


def test_expiracao_e_conferida_depois_da_espera_pela_trava(camadas, mundo):
    envio = _criar(mundo)
    EnvioCamada.objects.filter(pk=envio.pk).update(expira_em=timezone.now() + timedelta(seconds=2))
    segurando, soltar = threading.Event(), threading.Event()
    dono = threading.Thread(target=_travar_envio(envio.pk, segurando, soltar))
    dono.start()
    assert segurando.wait(timeout=10)
    resultados = []
    publicadora = threading.Thread(target=lambda: resultados.append(_capturar(_publicador(mundo, envio.pk))))
    publicadora.start()
    assert _esperar_trava()
    time.sleep(2.5)  # o envio vence enquanto a publicação espera a trava
    soltar.set()
    dono.join(timeout=10)
    publicadora.join(timeout=10)
    assert isinstance(resultados[0], RecusaPublicacao), resultados
    assert resultados[0].erros == ['envio expirado: envie o arquivo de novo']
    assert VersaoCamada.objects.count() == 0


# --- empate exige escolha; fora de todos os nós segue na fazenda (R7; spec 008:55 e A3) --------------------------------------

def test_empate_sem_escolha_e_recusado_com_erro_claro(camadas, mundo):
    _publicar(mundo, _criar(mundo, _divisao({'G1': BIG, 'T1': BIG})), nos=(), coluna_no='no', nome='Divisao')
    envio = _criar(mundo, _poligonos(1))
    antes = _contagem()
    with pytest.raises(RecusaPublicacao) as excinfo:
        _publicar(mundo, envio, nos=[None])
    assert excinfo.value.erros == ['feição em empate entre dois nós: escolha o nó']
    assert _contagem() == antes  # nada gravado


def test_empate_com_no_escolhido_e_aceito(camadas, mundo):
    _publicar(mundo, _criar(mundo, _divisao({'G1': BIG, 'T1': BIG})), nos=(), coluna_no='no', nome='Divisao')
    versao = _publicar(mundo, _criar(mundo, _poligonos(1)), nos=[mundo.g2.pk])
    assert versao.numero == 1


def test_sem_intersecao_com_none_continua_aceito(camadas, mundo):
    _publicar(mundo, _criar(mundo, _divisao({'G1': BIG})), nos=(), coluna_no='no', nome='Divisao')
    longe = geojson([{'type': 'Feature', 'properties': {'valor': 1}, 'geometry': {'type': 'Polygon', 'coordinates': [FAR]}}])
    versao = _publicar(mundo, _criar(mundo, longe), nos=[None])
    assert versao.numero == 1  # fora de todo nó: fica na fazenda (decisão do mantenedor)
