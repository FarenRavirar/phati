"""Mapa de teste de layout (004 R1, R3, R21; A1, A3): flag, acesso e política de conteúdo só na resposta que leva o mapa."""

import re

import pytest
from django.test import Client, override_settings

from projeto import mapa


def _caminho(empresa, fazenda):
    return f'/empresa/{empresa.pk}/fazenda/{fazenda.pk}/'


def _politica(resposta):
    return resposta['Content-Security-Policy']


def _diretiva(politica, nome):
    return next(p for p in politica.split('; ') if p.startswith(nome + ' '))


@pytest.fixture
def pagina(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    return lambda: cliente_logado.get(_caminho(cenario.x, cenario.f1))


def test_flag_desligada_e_o_padrao_e_a_pagina_nao_traz_o_mapa(pagina):
    assert mapa.mapa_ativo() is False
    resposta = pagina()
    html = resposta.content.decode()
    assert resposta.status_code == 200
    for rastro in ('maplibre', 'projeto/mapa.js', 'data-mapa'):
        assert rastro not in html, rastro
    assert 'O mapa aparece quando a fazenda tiver camadas.' in html


def test_flag_desligada_deixa_a_politica_da_002_sem_blob_nem_worker(pagina):
    politica = _politica(pagina())
    assert 'blob:' not in politica
    assert 'worker-src' not in politica


@override_settings(MAPA_TESTE_ATIVO=True)
def test_flag_ligada_a_pagina_carrega_o_mapa_como_modulo_com_o_nonce_da_resposta(pagina):
    resposta = pagina()
    html = resposta.content.decode()
    assert resposta.status_code == 200
    nonce = re.findall(r"'nonce-([\w-]+)'", _diretiva(_politica(resposta), 'script-src'))[0]
    assert re.search(rf'<script type="module" src="/static/projeto/mapa\.js" nonce="{nonce}">', html)
    assert re.search(rf'<link rel="stylesheet" href="/static/projeto/terceiros/maplibre/maplibre-gl\.css" nonce="{nonce}">', html)
    assert 'data-mapa' in html
    # O aviso de falha nasce visível (sem `hidden`): o `mapa.js` o esconde quando o mapa abre.
    assert re.search(r'<div data-mapa-aviso>.*Não foi possível abrir o mapa', html, re.S)
    assert 'O mapa aparece quando a fazenda tiver camadas.' not in html


@override_settings(MAPA_TESTE_ATIVO=True)
def test_botao_de_recentralizar_nasce_desabilitado_ate_o_script_ligar_o_clique(pagina):
    assert re.search(r'<button[^>]*data-recentralizar disabled>', pagina().content.decode())


@override_settings(MAPA_TESTE_ATIVO=True)
def test_flag_ligada_a_politica_do_mapa_so_acrescenta_blob_no_img(pagina):
    politica = _politica(pagina())
    assert _diretiva(politica, 'img-src') == "img-src 'self' data: blob:"
    assert 'worker-src' not in politica
    for sem in ('unsafe-eval', 'unsafe-inline'):
        assert sem not in politica
    assert "script-src 'self' 'nonce-" in politica
    assert "object-src 'none'" in politica
    assert "frame-ancestors 'none'" in politica


@override_settings(MAPA_TESTE_ATIVO=True)
def test_flag_ligada_as_outras_respostas_ficam_com_a_politica_da_002(cliente_logado):
    for caminho in ('/', '/empresas/', '/entrar'):
        politica = _politica(cliente_logado.get(caminho))
        assert 'blob:' not in politica, caminho
        assert 'worker-src' not in politica, caminho


@override_settings(MAPA_TESTE_ATIVO=True)
def test_flag_ligada_sem_alcance_da_o_mesmo_404_de_fazenda_inexistente(cliente_logado, cenario):
    # Controle de acesso negativo (AGENTS §Testes): a pessoa não tem concessão em X; por URL direta, 404 sem o mapa.
    sem_alcance = cliente_logado.get(_caminho(cenario.x, cenario.f1))
    inexistente = cliente_logado.get(f'/empresa/{cenario.x.pk}/fazenda/999999/')
    assert sem_alcance.status_code == inexistente.status_code == 404
    assert 'data-mapa' not in sem_alcance.content.decode()
    assert 'blob:' not in _politica(sem_alcance)


@override_settings(MAPA_TESTE_ATIVO=True)
def test_flag_ligada_deslogado_vai_para_a_entrada(cenario):
    resposta = Client().get(_caminho(cenario.x, cenario.f1))
    assert resposta.status_code == 302
    assert resposta['Location'].startswith('/entrar')


# --- Fundo Google (004 R17, R18; A12) ----------------------------------------------------------------------------

GOOGLE = 'https://tile.googleapis.com'
com_google = override_settings(MAPA_TESTE_ATIVO=True, MAPA_FUNDO_GOOGLE_ATIVO=True, MAPA_GOOGLE_CHAVE='chave-sintetica-de-teste')


def test_sem_a_flag_do_google_a_pagina_nao_traz_chave_modulo_nem_dominio(pagina):
    with override_settings(MAPA_TESTE_ATIVO=True, MAPA_GOOGLE_CHAVE='chave-sintetica-de-teste'):
        resposta = pagina()
    html = resposta.content.decode()
    assert 'data-fundo-online' not in html
    assert 'chave-sintetica-de-teste' not in html
    assert 'data-mapa-atribuicao' not in html
    assert 'data-mapa-fundo-aviso' not in html
    assert 'googleapis' not in _politica(resposta)


@override_settings(MAPA_FUNDO_GOOGLE_ATIVO=True, MAPA_GOOGLE_CHAVE='chave-sintetica-de-teste')
def test_flag_do_google_sem_o_mapa_de_teste_nao_liga_nada(pagina):
    resposta = pagina()
    assert mapa.fundo_google_ativo() is False
    assert 'chave-sintetica-de-teste' not in resposta.content.decode()
    assert 'googleapis' not in _politica(resposta)


@com_google
def test_flag_do_google_entrega_chave_modulo_e_atribuicao_na_pagina(pagina):
    html = pagina().content.decode()
    assert 'data-fundo-online-chave="chave-sintetica-de-teste"' in html
    assert re.search(r'data-fundo-online-modulo="/static/projeto/fundo-google\.js"', html)
    assert re.search(r'<p class="mapa-atribuicao" data-mapa-atribuicao hidden>.*Google Maps', html, re.S)  # só aparece depois de ligar o satélite
    assert re.search(r'<img[^>]*data-atribuicao-logo[^>]*src="/static/projeto/google-maps-logo[^"]*\.svg"[^>]*alt="Google Maps"', html)  # logo oficial, com rótulo de acessibilidade
    assert re.search(r'<button[^>]*data-satelite disabled[^>]*>Ativar satélite</button>', html)  # nasce desabilitado: habilita com o mapa pronto
    assert re.search(r'<div data-mapa-fundo-aviso hidden>', html)  # aviso próprio: o da posição do aparelho o apagaria


@com_google
def test_flag_do_google_acrescenta_so_a_origem_dos_tiles_a_politica_do_mapa(pagina):
    politica = _politica(pagina())
    assert _diretiva(politica, 'connect-src') == f"connect-src 'self' {GOOGLE}"
    assert _diretiva(politica, 'img-src') == f"img-src 'self' data: blob: {GOOGLE}"
    assert politica.count('googleapis') == 2
    for sem in ('unsafe-eval', 'unsafe-inline'):
        assert sem not in politica


@com_google
def test_flag_do_google_manda_so_a_origem_como_referenciador_e_o_resto_segue_same_origin(pagina, cliente_logado):
    assert pagina()['Referrer-Policy'] == 'strict-origin-when-cross-origin'
    assert cliente_logado.get('/empresas/')['Referrer-Policy'] == 'same-origin'


def test_sem_a_flag_do_google_a_pagina_nao_traz_botao_nem_atribuicao_do_satelite(pagina):
    with override_settings(MAPA_TESTE_ATIVO=True):
        html = pagina().content.decode()
    assert 'data-satelite' not in html
    assert 'data-mapa-atribuicao' not in html


def test_sem_a_flag_do_google_o_referenciador_segue_same_origin(pagina):
    with override_settings(MAPA_TESTE_ATIVO=True):
        assert pagina()['Referrer-Policy'] == 'same-origin'


@com_google
def test_flag_do_google_nao_vaza_o_dominio_para_as_outras_respostas(cliente_logado):
    for caminho in ('/', '/empresas/', '/entrar'):
        assert 'googleapis' not in _politica(cliente_logado.get(caminho)), caminho


@com_google
def test_flag_do_google_sem_alcance_nao_entrega_a_chave(cliente_logado, cenario):
    resposta = cliente_logado.get(_caminho(cenario.x, cenario.f1))
    assert resposta.status_code == 404
    assert b'chave-sintetica-de-teste' not in resposta.content
    assert 'googleapis' not in _politica(resposta)


# --- Rota das camadas (004 R4; A4) ---------------------------------------------------------------------------------

def _camadas(empresa, fazenda):
    return f'/empresa/{empresa.pk}/fazenda/{fazenda.pk}/camadas.geojson'


@pytest.fixture
def camadas(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    return lambda: cliente_logado.get(_camadas(cenario.x, cenario.f1))


def test_camadas_com_a_flag_desligada_da_404(camadas):
    assert mapa.mapa_ativo() is False
    assert camadas().status_code == 404


@override_settings(MAPA_TESTE_ATIVO=True)
def test_camadas_com_alcance_devolvem_feature_collection_em_wgs84(camadas):
    resposta = camadas()
    corpo = resposta.json()
    assert resposta.status_code == 200
    assert resposta['Content-Type'] == 'application/geo+json'
    assert corpo['type'] == 'FeatureCollection'
    assert len(corpo['features']) == 6
    for feicao in corpo['features']:
        for lon, lat in feicao['geometry']['coordinates'][0]:
            assert -180 <= lon <= 180
            assert -90 <= lat <= 90


@override_settings(MAPA_TESTE_ATIVO=True)
def test_camadas_sem_alcance_dao_o_mesmo_404_de_fazenda_inexistente(cliente_logado, cenario):
    sem_alcance = cliente_logado.get(_camadas(cenario.x, cenario.f1))
    inexistente = cliente_logado.get(f'/empresa/{cenario.x.pk}/fazenda/999999/camadas.geojson')
    assert sem_alcance.status_code == inexistente.status_code == 404
    assert b'FeatureCollection' not in sem_alcance.content


@override_settings(MAPA_TESTE_ATIVO=True)
def test_camadas_deslogado_vai_para_a_entrada(cenario):
    resposta = Client().get(_camadas(cenario.x, cenario.f1))
    assert resposta.status_code == 302
    assert resposta['Location'].startswith('/entrar')


@override_settings(MAPA_TESTE_ATIVO=True)
def test_camadas_recusam_escrita_com_405(cliente_logado, cenario):
    assert cliente_logado.post(_camadas(cenario.x, cenario.f1)).status_code == 405


# --- Cache do navegador e do aplicativo na rota das camadas (dado próprio) -------------------------------------------

@override_settings(MAPA_TESTE_ATIVO=True)
def test_camadas_levam_etag_e_cache_so_privado_com_revalidacao(camadas):
    resposta = camadas()
    diretivas = {d.strip() for d in resposta['Cache-Control'].split(',')}
    assert {'private', 'no-cache'} <= diretivas
    assert 'public' not in diretivas
    assert 'no-store' not in diretivas, resposta['Cache-Control']  # achado Greptile: `never_cache` do exige_entrada sobrescrevia
    assert resposta['ETag'].startswith('"')


@override_settings(MAPA_TESTE_ATIVO=True)
def test_camadas_com_etag_vigente_dao_304_sem_corpo_e_com_etag_velho_dao_200(cliente_logado, camadas, cenario):
    etag = camadas()['ETag']
    igual = cliente_logado.get(_camadas(cenario.x, cenario.f1), headers={'If-None-Match': etag})
    assert igual.status_code == 304
    assert igual.content == b''
    assert igual['ETag'] == etag
    assert 'private' in igual['Cache-Control']
    velho = cliente_logado.get(_camadas(cenario.x, cenario.f1), headers={'If-None-Match': '"velho"'})
    assert velho.status_code == 200
    assert velho.json()['type'] == 'FeatureCollection'


@override_settings(MAPA_TESTE_ATIVO=True)
def test_camadas_etag_vigente_nao_abre_304_sem_alcance_nem_deslogado_nem_com_flag_desligada(cliente_logado, camadas, cenario):
    etag = camadas()['ETag']
    cabecalho = {'If-None-Match': etag}
    # Fazenda que existe (de outra empresa) e a conta não alcança: o ETag vigente não abre 304 (achado Sourcery, média).
    sem_alcance = cliente_logado.get(_camadas(cenario.y, cenario.fy), headers=cabecalho)
    assert sem_alcance.status_code == 404
    assert b'FeatureCollection' not in sem_alcance.content
    assert Client().get(_camadas(cenario.x, cenario.f1), headers=cabecalho).status_code == 302
    with override_settings(MAPA_TESTE_ATIVO=False):
        assert cliente_logado.get(_camadas(cenario.x, cenario.f1), headers=cabecalho).status_code == 404


def test_as_outras_paginas_e_o_redirecionamento_seguem_sem_cache(cliente_logado):
    assert 'no-store' in cliente_logado.get('/')['Cache-Control']
    assert 'no-store' in Client().get('/')['Cache-Control']  # deslogado: redirecionamento ao login, também sem cache
