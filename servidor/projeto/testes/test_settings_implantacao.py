"""Implantação atrás de proxy com TLS (006 R3, A2, A3): a flag liga proxy SSL, origem confiável e HSTS; sem ela nada muda."""

import runpy
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import Client

CAMINHO = Path(settings.DIRETORIO_BASE) / 'projeto' / 'settings.py'
FQDN = 'phati.exemplo.test'


def _carregar(monkeypatch, **ambiente):
    for nome, valor in ambiente.items():
        monkeypatch.setenv(nome, valor)
    return runpy.run_path(str(CAMINHO))


def _implantacao(monkeypatch, **mudancas):
    base = {'PHATI_IMPLANTACAO': '1', 'PHATI_URL_BASE': f'https://{FQDN}', 'PHATI_HOSTS_PERMITIDOS': FQDN}
    return _carregar(monkeypatch, **{**base, **mudancas})


def test_sem_a_flag_nada_de_proxy_muda(monkeypatch):
    monkeypatch.delenv('PHATI_IMPLANTACAO', raising=False)
    carregado = runpy.run_path(str(CAMINHO))
    assert carregado['IMPLANTACAO'] is False
    assert not {'SECURE_PROXY_SSL_HEADER', 'CSRF_TRUSTED_ORIGINS', 'SECURE_HSTS_SECONDS'} & carregado.keys()


def test_com_a_flag_liga_proxy_ssl_origem_confiavel_e_hsts(monkeypatch):
    carregado = _implantacao(monkeypatch)
    assert carregado['SECURE_PROXY_SSL_HEADER'] == ('HTTP_X_FORWARDED_PROTO', 'https')
    assert carregado['CSRF_TRUSTED_ORIGINS'] == [f'https://{FQDN}']
    assert carregado['SECURE_HSTS_SECONDS'] == 30 * 24 * 3600
    assert carregado['SESSION_COOKIE_SECURE'] is True


@pytest.mark.parametrize('url', ['http://phati.exemplo.test', 'phati.exemplo.test', 'https://', ''])
def test_flag_sem_url_https_recusa_subir(monkeypatch, url):
    with pytest.raises(ImproperlyConfigured, match='https'):
        _implantacao(monkeypatch, PHATI_URL_BASE=url)


def test_flag_com_host_fora_dos_permitidos_recusa_subir(monkeypatch):
    with pytest.raises(ImproperlyConfigured, match='PHATI_HOSTS_PERMITIDOS'):
        _implantacao(monkeypatch, PHATI_HOSTS_PERMITIDOS='outro.exemplo.test')


def _post_de_login(settings, origem):
    """GET para ganhar o cookie e o token de CSRF, depois POST com `Origin`; devolve a resposta do POST."""
    carregado = runpy.run_path(str(CAMINHO))
    settings.ALLOWED_HOSTS = [FQDN]
    settings.SECURE_PROXY_SSL_HEADER = carregado['SECURE_PROXY_SSL_HEADER']
    settings.CSRF_TRUSTED_ORIGINS = carregado['CSRF_TRUSTED_ORIGINS']
    cliente = Client(enforce_csrf_checks=True, HTTP_HOST=FQDN, HTTP_X_FORWARDED_PROTO='https')
    cliente.get('/entrar')
    token = cliente.cookies['csrftoken'].value
    return cliente.post('/entrar', {'cpf': '0', 'senha': 'x', 'csrfmiddlewaretoken': token}, HTTP_ORIGIN=origem)


def _foi_recusada_por_csrf(resposta):
    return '403_csrf.html' in [molde.name for molde in resposta.templates]


def _cliente_de_implantacao(settings, **cabecalhos):
    settings.ALLOWED_HOSTS = [FQDN]
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_REDIRECT_EXEMPT = [r'^saude$']
    settings.SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    return Client(HTTP_HOST=FQDN, **cabecalhos)


def test_com_a_flag_o_settings_liga_o_redirecionamento_e_isenta_so_a_sonda(monkeypatch):
    carregado = _implantacao(monkeypatch)
    assert carregado['SECURE_SSL_REDIRECT'] is True
    assert carregado['SECURE_REDIRECT_EXEMPT'] == [r'^saude$']


def test_pedido_http_e_redirecionado_para_https_e_o_https_passa(db, settings):
    http = _cliente_de_implantacao(settings).get('/entrar')
    assert (http.status_code, http['Location']) == (301, f'https://{FQDN}/entrar')
    https = _cliente_de_implantacao(settings, HTTP_X_FORWARDED_PROTO='https').get('/entrar')
    assert https.status_code == 200


def test_sonda_de_saude_responde_sem_cabecalho_de_proxy_e_sem_redirecionar(db, settings):
    assert _cliente_de_implantacao(settings).get('/saude').status_code == 200


def test_post_com_origem_do_fqdn_passa_o_csrf_e_com_outra_origem_e_recusado(db, settings, monkeypatch):
    monkeypatch.setenv('PHATI_IMPLANTACAO', '1')
    monkeypatch.setenv('PHATI_URL_BASE', f'https://{FQDN}')
    monkeypatch.setenv('PHATI_HOSTS_PERMITIDOS', FQDN)
    assert not _foi_recusada_por_csrf(_post_de_login(settings, f'https://{FQDN}'))
    assert _foi_recusada_por_csrf(_post_de_login(settings, 'https://intruso.exemplo.test'))


RAIZ = Path(settings.DIRETORIO_BASE)


def test_nginx_conta_o_ip_real_do_cliente_so_de_quem_esta_na_rede_privada():
    conf = (RAIZ / 'nginx' / 'default.conf').read_text(encoding='utf-8')
    ativas = [linha.strip() for linha in conf.splitlines() if not linha.strip().startswith('#')]  # comentário não vale
    assert 'real_ip_header CF-Connecting-IP;' in ativas
    assert 'set_real_ip_from 172.29.250.0/24;' in ativas
    assert 'set_real_ip_from 0.0.0.0/0;' not in ativas  # confiar em qualquer origem deixaria forjar o cabeçalho


def test_sub_rede_confiada_pelo_nginx_e_a_fixada_no_compose_de_implantacao():
    compose = (RAIZ / 'compose.implantacao.yaml').read_text(encoding='utf-8')
    assert '        - subnet: 172.29.250.0/24' in compose.splitlines()


def _bloco(texto, servico):
    """Linhas do serviço no compose (do `  nome:` até o próximo filho de `services`); sem YAML, que o `!reset` quebra."""
    linhas = texto.splitlines()
    inicio = linhas.index(f'  {servico}:') + 1
    fim = next((i for i in range(inicio, len(linhas)) if linhas[i].startswith('  ') and not linhas[i].startswith('   ') and linhas[i].strip() and not linhas[i].lstrip().startswith('#')), len(linhas))
    return linhas[inicio:fim]


def test_compose_de_implantacao_zera_as_portas_de_app_e_nginx_e_so_o_tunel_entra():
    # A1: o job `docker` do CI repete a prova com `docker compose config`, que expande o arquivo de verdade.
    texto = (RAIZ / 'compose.implantacao.yaml').read_text(encoding='utf-8')
    for servico in ('app', 'nginx'):
        assert '    ports: !reset []' in _bloco(texto, servico)
    assert not any(linha.strip() == 'ports:' or linha.strip().startswith('- "') for linha in texto.splitlines())  # nada publica porta
    assert '      PHATI_IMPLANTACAO: "1"' in _bloco(texto, 'app')
    assert '      TUNNEL_TOKEN: ${PHATI_TUNEL_TOKEN:?}' in _bloco(texto, 'cloudflared')
    assert any('@sha256:' in linha for linha in _bloco(texto, 'cloudflared'))  # imagem do túnel fixada por digest
