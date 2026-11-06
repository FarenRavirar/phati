"""Rotas do pacote (004b R3, R4, R11; A3, A4): acesso negado por URL direta, ação exigida, Range e nome de arquivo."""

import json
import re

import pytest
from django.test import Client, override_settings

from pacote.testes.conftest import REFERENCIA


def _url(cenario, fazenda, resto):
    return f'/empresa/{fazenda.empresa_id}/fazenda/{fazenda.pk}/pacote/{resto}'


def _sem_nonce(html):
    return re.sub(rb'nonce[-="\w]*', b'', html)  # cada resposta traz um nonce de CSP novo


def _corpo(resposta):
    return b''.join(resposta.streaming_content)


@pytest.fixture
def usuario(entrar, cenario):
    """Cargo Usuário de X na fazenda F1: `ver` e `baixar_pacote_offline`."""
    return entrar(cenario.cargos_x['usuario'], cenario.f1)


def test_manifesto_com_a_acao_devolve_o_vigente_privado(usuario, cenario, referencia_instalada):
    resposta = usuario.get(_url(cenario, cenario.f1, 'manifesto.json'))
    assert resposta.status_code == 200
    assert json.loads(resposta.content)['versao'] == 1
    assert json.loads(resposta.content)['fazenda_id'] == cenario.f1.pk
    assert 'private' in resposta['Cache-Control']


def test_sem_versao_vigente_e_404(usuario, cenario, pacotes):
    assert usuario.get(_url(cenario, cenario.f1, 'manifesto.json')).status_code == 404
    assert usuario.get(_url(cenario, cenario.f1, 'arquivo/fundo.pmtiles')).status_code == 404


def test_sem_alcance_o_404_e_igual_ao_de_fazenda_inexistente(entrar, cenario, referencia_instalada):
    de_y = entrar(cenario.cargos_y['administrador'], cenario.y)  # alcance só em Y
    sem_vinculo = entrar()
    inexistente = de_y.get(f'/empresa/{cenario.x.pk}/fazenda/999999/pacote/manifesto.json')
    for cliente in (de_y, sem_vinculo):
        for resto in ('manifesto.json', 'camadas.geojson', 'arquivo/fundo.pmtiles'):
            resposta = cliente.get(_url(cenario, cenario.f1, resto))
            assert resposta.status_code == inexistente.status_code == 404, resto
            assert _sem_nonce(resposta.content) == _sem_nonce(inexistente.content)


def test_deslogado_vai_ao_login(cenario, referencia_instalada):
    for resto in ('manifesto.json', 'camadas.geojson', 'arquivo/fundo.pmtiles'):
        resposta = Client().get(_url(cenario, cenario.f1, resto))
        assert resposta.status_code == 302, resto
        assert resposta['Location'].startswith('/entrar'), resto


def test_com_alcance_e_sem_baixar_pacote_offline_manifesto_e_camadas_dao_403_e_arquivos_200(entrar, cenario, cargo_so_ver, referencia_instalada):
    cliente = entrar(cargo_so_ver, cenario.f1)
    assert cliente.get(_url(cenario, cenario.f1, 'manifesto.json')).status_code == 403
    with override_settings(MAPA_TESTE_ATIVO=True):
        assert cliente.get(_url(cenario, cenario.f1, 'camadas.geojson')).status_code == 403
    # Limite registrado no R3: os bytes saem a quem tem `ver`, porque a web os lê por Range.
    assert cliente.get(_url(cenario, cenario.f1, 'arquivo/fundo.pmtiles')).status_code == 200


def test_camadas_so_com_a_flag_e_iguais_as_da_api_de_camadas(usuario, cenario, referencia_instalada):
    with override_settings(MAPA_TESTE_ATIVO=False):
        assert usuario.get(_url(cenario, cenario.f1, 'camadas.geojson')).status_code == 404  # flag desligada
    with override_settings(MAPA_TESTE_ATIVO=True):
        do_pacote = usuario.get(_url(cenario, cenario.f1, 'camadas.geojson'))
        da_api = usuario.get(f'/empresa/{cenario.x.pk}/fazenda/{cenario.f1.pk}/camadas.geojson')
    assert do_pacote.status_code == da_api.status_code == 200
    assert do_pacote.content == da_api.content  # A4: a mesma função, a mesma resposta
    assert 'private' in do_pacote['Cache-Control']


def test_arquivo_inteiro_traz_os_bytes_do_disco_e_aceita_faixa(usuario, cenario, referencia_instalada):
    esperado = (REFERENCIA / 'ortofoto.pmtiles').read_bytes()
    resposta = usuario.get(_url(cenario, cenario.f1, 'arquivo/ortofoto.pmtiles'))
    assert resposta.status_code == 200
    assert _corpo(resposta) == esperado
    assert resposta['Accept-Ranges'] == 'bytes'
    assert 'private' in resposta['Cache-Control']


TAMANHO = (REFERENCIA / 'ortofoto.pmtiles').stat().st_size


@pytest.mark.parametrize('cabecalho, inicio, fim', [
    ('bytes=0-9', 0, 9), ('bytes=100-199', 100, 199), ('bytes=-5', TAMANHO - 5, TAMANHO - 1),
    ('bytes=60000-', 60000, TAMANHO - 1), ('bytes=10-99999999', 10, TAMANHO - 1),  # fim além do arquivo é cortado no último byte
])
def test_range_devolve_206_com_o_trecho_certo(usuario, cenario, referencia_instalada, cabecalho, inicio, fim):
    esperado = (REFERENCIA / 'ortofoto.pmtiles').read_bytes()[inicio:fim + 1]
    resposta = usuario.get(_url(cenario, cenario.f1, 'arquivo/ortofoto.pmtiles'), headers={'Range': cabecalho})
    assert resposta.status_code == 206
    assert _corpo(resposta) == esperado
    assert resposta['Content-Range'] == f'bytes {inicio}-{fim}/{TAMANHO}'
    assert resposta['Content-Length'] == str(len(esperado))


@pytest.mark.parametrize('cabecalho', ['bytes=999999999-', 'bytes=9-3', 'bytes=-0'])
def test_range_impossivel_da_416(usuario, cenario, referencia_instalada, cabecalho):
    resposta = usuario.get(_url(cenario, cenario.f1, 'arquivo/ortofoto.pmtiles'), headers={'Range': cabecalho})
    assert resposta.status_code == 416
    assert resposta['Content-Range'] == f'bytes */{(REFERENCIA / "ortofoto.pmtiles").stat().st_size}'


@pytest.mark.parametrize('cabecalho', ['bytes=0-1,5-6', 'items=0-9', 'bytes=a-b', 'bytes=-', 'bytes=' + '9' * 5000 + '-', 'bytes=0-' + '9' * 5000])
def test_range_que_nao_e_de_um_trecho_serve_o_arquivo_inteiro(usuario, cenario, referencia_instalada, cabecalho):
    resposta = usuario.get(_url(cenario, cenario.f1, 'arquivo/fundo.pmtiles'), headers={'Range': cabecalho})
    assert resposta.status_code == 200
    assert _corpo(resposta) == (REFERENCIA / 'fundo.pmtiles').read_bytes()


def test_etag_igual_devolve_304_sem_corpo_e_so_depois_do_controle_de_acesso(usuario, entrar, cenario, referencia_instalada):
    primeira = usuario.get(_url(cenario, cenario.f1, 'arquivo/fundo.pmtiles'))
    etag = primeira['ETag']
    repetida = usuario.get(_url(cenario, cenario.f1, 'arquivo/fundo.pmtiles'), headers={'If-None-Match': etag})
    assert repetida.status_code == 304
    assert repetida.content == b''
    intruso = entrar()  # sem alcance: 404 mesmo com o ETag certo, nunca 304
    assert intruso.get(_url(cenario, cenario.f1, 'arquivo/fundo.pmtiles'), headers={'If-None-Match': etag}).status_code == 404


@pytest.mark.parametrize('nome', ['manifesto.json', 'nao-listado.pmtiles', '..%2Ffundo.pmtiles', '%2e%2e%2f%2e%2e%2fsettings.py', 'FUNDO.pmtiles'])
def test_nome_fora_do_manifesto_ou_com_travessia_e_404(usuario, cenario, referencia_instalada, nome):
    assert usuario.get(_url(cenario, cenario.f1, f'arquivo/{nome}')).status_code == 404


def test_arquivo_que_sumiu_do_disco_e_404_e_nao_erro(usuario, cenario, pacotes, referencia_instalada):
    (pacotes / str(cenario.f1.pk) / 'v1' / 'fundo.pmtiles').unlink()
    assert usuario.get(_url(cenario, cenario.f1, 'arquivo/fundo.pmtiles')).status_code == 404


def _segunda_versao_vigente(pacotes, cenario, referencia_instalada):
    """Instala a versão 2 (fundo com outros bytes) como vigente; a 1 segue no disco e no banco."""
    import copy
    import shutil

    from pacote.models import VersaoPacote

    origem = pacotes / str(cenario.f1.pk)
    shutil.copytree(origem / 'v1', origem / 'v2')
    (origem / 'v2' / 'fundo.pmtiles').write_bytes(b'versao-dois')
    manifesto = copy.deepcopy(referencia_instalada.manifesto)
    manifesto['versao'] = 2
    VersaoPacote.objects.filter(pk=referencia_instalada.pk).update(vigente=False)
    return VersaoPacote.objects.create(empresa=cenario.x, fazenda=cenario.f1, numero=2, manifesto=manifesto, vigente=True)


def test_versao_pedida_serve_os_bytes_dela_mesmo_depois_que_outra_vira_vigente(usuario, cenario, pacotes, referencia_instalada):
    # CodeRabbit, PR #50: manifesto da v1 em mãos, v2 vira vigente no meio do download; os arquivos têm de ser os da v1.
    _segunda_versao_vigente(pacotes, cenario, referencia_instalada)
    url = _url(cenario, cenario.f1, 'arquivo/fundo.pmtiles')
    assert _corpo(usuario.get(url + '?versao=1')) == (REFERENCIA / 'fundo.pmtiles').read_bytes()
    assert _corpo(usuario.get(url + '?versao=2')) == b'versao-dois'
    assert _corpo(usuario.get(url)) == b'versao-dois'  # sem parâmetro, a vigente


@pytest.mark.parametrize('pedida', ['99', '0', 'abc', '-1', '1.5', '', '1' * 10, '１'])
def test_versao_inexistente_ou_invalida_e_404(usuario, cenario, referencia_instalada, pedida):
    assert usuario.get(_url(cenario, cenario.f1, 'arquivo/fundo.pmtiles') + f'?versao={pedida}').status_code == 404


def test_versao_de_outra_fazenda_nao_vaza_pelo_numero(entrar, cenario, pacotes, referencia_instalada):
    # A versão 1 existe só na F1; quem tem a F2 pede `?versao=1` na F2 e leva 404, nunca os bytes da F1.
    de_f2 = entrar(cenario.cargos_x['usuario'], cenario.f2)
    assert de_f2.get(_url(cenario, cenario.f2, 'arquivo/fundo.pmtiles') + '?versao=1').status_code == 404


def test_so_a_versao_vigente_e_servida(usuario, cenario, pacotes, referencia_instalada):
    from pacote.models import VersaoPacote

    VersaoPacote.objects.filter(pk=referencia_instalada.pk).update(vigente=False)
    assert usuario.get(_url(cenario, cenario.f1, 'manifesto.json')).status_code == 404


def test_o_servidor_nunca_mostra_o_caminho_do_disco(usuario, cenario, pacotes, referencia_instalada):
    corpo = usuario.get(_url(cenario, cenario.f1, 'manifesto.json')).content.decode()
    assert str(pacotes) not in corpo


def test_so_get_e_aceito(usuario, cenario, referencia_instalada):
    assert usuario.post(_url(cenario, cenario.f1, 'manifesto.json')).status_code == 405


def _bearer(pessoa):
    from identidade import sessao

    return {'Authorization': f'Bearer {sessao.emitir_acesso(pessoa, "celular sintetico")}'}


def test_aplicativo_com_bearer_e_sem_cookie_baixa_manifesto_e_arquivo(cenario, fabrica_pessoa, conceder_direto, referencia_instalada):
    # Greptile, PR #50, P1: o Android não tem cookie, só `Authorization: Bearer`.
    pessoa = fabrica_pessoa('Aplicativo')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    cabecalho = _bearer(pessoa)
    manifesto = Client().get(_url(cenario, cenario.f1, 'manifesto.json'), headers=cabecalho)
    assert manifesto.status_code == 200
    assert json.loads(manifesto.content)['versao'] == 1
    arquivo = Client().get(_url(cenario, cenario.f1, 'arquivo/fundo.pmtiles'), headers={**cabecalho, 'Range': 'bytes=0-6'})
    assert arquivo.status_code == 206
    assert _corpo(arquivo) == b'PMTiles'


@pytest.mark.parametrize('cabecalho, status', [
    ({'Authorization': 'Bearer token-que-nao-existe'}, 401),  # Bearer inválido: 401, sem redirecionar
    ({'Authorization': 'Bearer'}, 302),  # sem token: cai no portão de sessão e vai ao login
    ({'Authorization': 'Basic abc'}, 302),
])
def test_bearer_invalido_nao_entra(cenario, referencia_instalada, cabecalho, status):
    resposta = Client().get(_url(cenario, cenario.f1, 'manifesto.json'), headers=cabecalho)
    assert resposta.status_code == status
    assert b'versao' not in resposta.content


def test_bearer_de_pessoa_sem_alcance_leva_404_como_o_navegador(cenario, fabrica_pessoa, conceder_direto, referencia_instalada):
    de_y = fabrica_pessoa('Aplicativo de Y')
    conceder_direto(de_y, cenario.cargos_y['administrador'], cenario.y)
    assert Client().get(_url(cenario, cenario.f1, 'manifesto.json'), headers=_bearer(de_y)).status_code == 404


def test_quem_so_tem_uma_sub_area_nao_baixa_os_arquivos_da_fazenda(entrar, cenario, referencia_instalada):
    # Greptile, PR #50, P1: `resolver_escopo` admite a sub-área, mas fundo e ortofoto são da fazenda inteira.
    so_sub_area = entrar(cenario.cargos_x['usuario'], cenario.g1)
    for resto in ('arquivo/fundo.pmtiles', 'arquivo/ortofoto.pmtiles', 'manifesto.json'):
        assert so_sub_area.get(_url(cenario, cenario.f1, resto)).status_code in (403, 404), resto


def test_if_range_de_outra_versao_devolve_o_arquivo_inteiro(usuario, cenario, referencia_instalada):
    # RFC 9110 §13.1.5: validador que não bate obriga a ignorar `Range`.
    etag = usuario.get(_url(cenario, cenario.f1, 'arquivo/ortofoto.pmtiles'))['ETag']
    velho = usuario.get(_url(cenario, cenario.f1, 'arquivo/ortofoto.pmtiles'), headers={'Range': 'bytes=0-9', 'If-Range': '"versao-antiga"'})
    assert velho.status_code == 200
    assert len(_corpo(velho)) == TAMANHO
    igual = usuario.get(_url(cenario, cenario.f1, 'arquivo/ortofoto.pmtiles'), headers={'Range': 'bytes=0-9', 'If-Range': etag})
    assert igual.status_code == 206
