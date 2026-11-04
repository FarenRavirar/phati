import base64
import re
import runpy
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import ProgrammingError, connections

CAMINHO = Path(settings.DIRETORIO_BASE) / 'projeto' / 'settings.py'

# `app` lê o que o dono migrou e já foi confirmado no banco de teste; sem dado novo, sem `transaction=True`.
usa_app = pytest.mark.django_db(databases=['default', 'app'])


def test_chave_secreta_ausente_falha_alto(monkeypatch):
    monkeypatch.delenv('PHATI_CHAVE_SECRETA')
    with pytest.raises(KeyError):
        runpy.run_path(str(CAMINHO))


def test_processo_web_sem_senha_do_dono_usa_o_papel_app_como_padrao(monkeypatch):
    monkeypatch.delenv('PHATI_BANCO_DONO_SENHA')
    bancos = runpy.run_path(str(CAMINHO))['DATABASES']
    assert bancos['default']['USER'] == bancos['app']['USER']
    assert bancos['default']['PASSWORD'] == bancos['app']['PASSWORD']


def test_dois_papeis_distintos():
    assert settings.DATABASES['default']['USER'] != settings.DATABASES['app']['USER']


def _um(alias, sql):
    with connections[alias].cursor() as consulta:
        consulta.execute(sql)
        return consulta.fetchone()


@usa_app
def test_papel_app_nao_e_super_nem_ignora_rls_nem_cria():
    sql = 'SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user'
    assert _um('app', sql) == (False, False, False, False)


@usa_app
def test_papel_app_nao_e_dono_e_papel_dono_e():
    donas = "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = current_user"
    assert _um('app', donas) == (0,)
    assert _um('default', donas)[0] > 0


@usa_app
def test_papel_app_le_tabela_do_dono_mas_nao_cria_tabela():
    assert _um('app', 'SELECT count(*) FROM permissao') == (30,)
    with pytest.raises(ProgrammingError, match='permission denied'), connections['app'].cursor() as consulta:
        consulta.execute('CREATE TABLE intrusa (id int)')


def test_compose_repassa_toda_variavel_que_o_settings_le():
    # Achado do Codex (PR #1): variável do shell só chega ao contêiner se o compose a listar.
    lidas = set(re.findall(r'PHATI_[A-Z_]+', CAMINHO.read_text(encoding='utf-8')))
    listadas = set(re.findall(r'PHATI_[A-Z_]+', (CAMINHO.parents[1] / 'compose.yaml').read_text(encoding='utf-8')))
    assert lidas - listadas == set()


def test_estaticos_vao_para_o_volume_que_o_nginx_serve(monkeypatch):
    # D070: `collectstatic` grava no volume `estaticos` do compose, que o nginx monta somente leitura.
    monkeypatch.delenv('PHATI_ESTATICOS', raising=False)
    assert runpy.run_path(str(CAMINHO))['STATIC_ROOT'] == '/estaticos'
    monkeypatch.setenv('PHATI_ESTATICOS', '/outro')
    assert runpy.run_path(str(CAMINHO))['STATIC_ROOT'] == '/outro'
    compose = (CAMINHO.parents[1] / 'compose.yaml').read_text(encoding='utf-8')
    assert 'estaticos:/estaticos:ro' in compose


def test_healthcheck_do_banco_espera_o_servidor_tcp():
    # Achado do CodeRabbit (PR #1): sem `-h`, o pg_isready aceita o servidor temporário do initdb (só socket).
    compose = (CAMINHO.parents[1] / 'compose.yaml').read_text(encoding='utf-8')
    assert 'pg_isready -h 127.0.0.1' in compose


def test_smtp_tem_prazo_para_nao_prender_o_processo():
    # Achado do Qodo (PR #9): sem timeout, um SMTP mudo bloqueia o pedido de redefinição sem fim.
    # O pytest-django troca MAILERS por um backend em memória; por isso lê-se o arquivo, como nos testes acima.
    opcoes = runpy.run_path(str(CAMINHO))['MAILERS']['default']['OPTIONS']
    assert 0 < opcoes['timeout'] <= 30


@pytest.mark.parametrize('invalida', ['', 'curta', 'AAAA' * 8, 'A' * 43, 'não-ascii-é' * 4])
def test_chave_do_cpf_fora_do_formato_derruba_o_servidor(monkeypatch, invalida):
    # Achado do CodeRabbit (PR #9): chave truncada ou com lixo trocaria o HMAC e perderia os CPFs já cadastrados.
    monkeypatch.setenv('PHATI_CHAVE_CPF', invalida)
    with pytest.raises(ImproperlyConfigured):
        runpy.run_path(str(CAMINHO))


def test_chave_do_cpf_ausente_derruba_o_servidor(monkeypatch):
    monkeypatch.delenv('PHATI_CHAVE_CPF')
    with pytest.raises(ImproperlyConfigured):
        runpy.run_path(str(CAMINHO))


def test_chave_do_cpf_de_32_bytes_e_aceita(monkeypatch):
    bruta = bytes(range(32))
    monkeypatch.setenv('PHATI_CHAVE_CPF', base64.urlsafe_b64encode(bruta).decode())
    assert runpy.run_path(str(CAMINHO))['CHAVE_CPF'] == bruta


def test_chave_do_cpf_com_caractere_estranho_derruba_o_servidor(monkeypatch):
    # A decodificação tolerante do Python descarta o "!" e devolveria os mesmos 32 bytes; a forma canônica barra.
    monkeypatch.setenv('PHATI_CHAVE_CPF', base64.urlsafe_b64encode(bytes(range(32))).decode() + '!')
    with pytest.raises(ImproperlyConfigured):
        runpy.run_path(str(CAMINHO))


@pytest.mark.parametrize('invalido', ['', 'curta', 'AAAA' * 8, 'A' * 43])
def test_segredo_da_rls_fora_do_formato_derruba_o_servidor(monkeypatch, invalido):
    # Segredo errado trocaria a assinatura do contexto de RLS: o banco negaria todo acesso sem aviso.
    monkeypatch.setenv('PHATI_SEGREDO_RLS', invalido)
    with pytest.raises(ImproperlyConfigured, match='PHATI_SEGREDO_RLS'):
        runpy.run_path(str(CAMINHO))


def test_segredo_da_rls_ausente_derruba_o_servidor(monkeypatch):
    monkeypatch.delenv('PHATI_SEGREDO_RLS')
    with pytest.raises(ImproperlyConfigured, match='PHATI_SEGREDO_RLS'):
        runpy.run_path(str(CAMINHO))


def test_segredo_da_rls_de_32_bytes_e_aceito(monkeypatch):
    bruto = bytes(range(32, 64))
    monkeypatch.setenv('PHATI_SEGREDO_RLS', base64.urlsafe_b64encode(bruto).decode())
    assert runpy.run_path(str(CAMINHO))['SEGREDO_RLS'] == bruto


def test_variaveis_de_email_chegam_ao_smtp_com_a_porta_inteira(monkeypatch):
    # Achado do CodeRabbit (PR #9): nada provava que o ambiente configura o SMTP.
    monkeypatch.setenv('PHATI_EMAIL_HOST', 'smtp.exemplo.test')
    monkeypatch.setenv('PHATI_EMAIL_PORTA', '2525')
    monkeypatch.setenv('PHATI_EMAIL_USUARIO', 'usuario-de-teste')
    monkeypatch.setenv('PHATI_EMAIL_SENHA', 'valor-de-teste')
    monkeypatch.setenv('PHATI_EMAIL_REMETENTE', 'remetente@exemplo.test')
    configuracao = runpy.run_path(str(CAMINHO))
    opcoes = configuracao['MAILERS']['default']['OPTIONS']
    assert opcoes['host'] == 'smtp.exemplo.test'
    assert opcoes['port'] == 2525
    assert opcoes['username'] == 'usuario-de-teste'
    assert opcoes['password'] == 'valor-de-teste'
    assert configuracao['DEFAULT_FROM_EMAIL'] == 'remetente@exemplo.test'


def test_politica_de_conteudo_so_aceita_script_do_proprio_site_ou_com_nonce():
    politica = runpy.run_path(str(CAMINHO))['SECURE_CSP']
    todos = [valor for valores in politica.values() for valor in valores]
    assert "'unsafe-inline'" not in todos
    assert "'unsafe-eval'" not in todos
    assert politica['script-src'] == ["'self'", '<CSP_NONCE_SENTINEL>']
    assert politica['object-src'] == ["'none'"]
    assert politica['frame-ancestors'] == ["'none'"]


def test_middleware_e_processador_da_politica_estao_ligados_e_na_ordem():
    antes_do_resto = settings.MIDDLEWARE.index('django.middleware.csp.ContentSecurityPolicyMiddleware')
    assert antes_do_resto == settings.MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1
    assert 'django.template.context_processors.csp' in settings.TEMPLATES[0]['OPTIONS']['context_processors']
    assert settings.CSRF_FAILURE_VIEW == 'projeto.paginas.falha_csrf'


def test_estaticos_do_projeto_sao_achados_sem_ser_app_instalado():
    from django.contrib.staticfiles import finders

    assert finders.find('projeto/tokens.css')


def test_collectstatic_nao_publica_testes_de_js():
    from django.apps import apps
    from django.contrib.staticfiles import finders

    ignorar = getattr(apps.get_app_config('staticfiles'), 'ignore_patterns')  # atributo do StaticFilesConfig, não do AppConfig
    assert '*.test.js' in ignorar
    publicados = [caminho.replace('\\', '/') for achador in finders.get_finders() for caminho, _ in achador.list(ignorar)]
    assert 'projeto/busca-fazendas.js' in publicados
    assert 'projeto/busca-fazendas.test.js' not in publicados


def _com_ambiente(monkeypatch, ambiente, flag):
    for nome, valor in (('PHATI_AMBIENTE', ambiente), ('PHATI_MAPA_TESTE_ATIVO', flag)):
        if valor is None:
            monkeypatch.delenv(nome, raising=False)
        else:
            monkeypatch.setenv(nome, valor)
    return runpy.run_path(str(CAMINHO))


def test_sem_variaveis_o_ambiente_e_producao_e_o_mapa_esta_desligado(monkeypatch):
    configuracao = _com_ambiente(monkeypatch, None, None)
    assert configuracao['AMBIENTE'] == 'producao'
    assert configuracao['MAPA_TESTE_ATIVO'] is False


@pytest.mark.parametrize('flag', [None, '', '0', '2', 'true', 'sim', ' 1'])
def test_so_o_valor_1_liga_o_mapa(monkeypatch, flag):
    assert _com_ambiente(monkeypatch, 'teste', flag)['MAPA_TESTE_ATIVO'] is False


@pytest.mark.parametrize('ambiente', ['local', 'homologacao', 'teste'])
def test_flag_ligada_nos_tres_ambientes_de_teste_sobe(monkeypatch, ambiente):
    configuracao = _com_ambiente(monkeypatch, ambiente, '1')
    assert configuracao['MAPA_TESTE_ATIVO'] is True
    assert configuracao['AMBIENTE'] == ambiente


@pytest.mark.parametrize('ambiente', [None, 'producao', 'Local', '', 'qualquer'])
def test_flag_ligada_fora_dos_ambientes_de_teste_derruba_o_servidor(monkeypatch, ambiente):
    with pytest.raises(ImproperlyConfigured, match='PHATI_MAPA_TESTE_ATIVO'):
        _com_ambiente(monkeypatch, ambiente, '1')


@pytest.mark.parametrize('ambiente', [None, 'producao', 'qualquer'])
def test_flag_desligada_em_qualquer_ambiente_sobe(monkeypatch, ambiente):
    assert _com_ambiente(monkeypatch, ambiente, '0')['MAPA_TESTE_ATIVO'] is False


def test_politica_do_mapa_e_a_da_002_mais_blob_so_no_img():
    configuracao = runpy.run_path(str(CAMINHO))
    base, mapa = configuracao['SECURE_CSP'], configuracao['SECURE_CSP_MAPA']
    assert {k: v for k, v in mapa.items() if k != 'img-src'} == {k: v for k, v in base.items() if k != 'img-src'}
    assert mapa['img-src'] == base['img-src'] + ['blob:']
    assert 'worker-src' not in mapa  # worker do próprio site: herda de `script-src` (doc 6.16, T2.2)
    assert "'unsafe-inline'" not in [v for valores in mapa.values() for v in valores]
    assert "'unsafe-eval'" not in [v for valores in mapa.values() for v in valores]


def _com_google(monkeypatch, ambiente, mapa, google, chave):
    for nome, valor in (('PHATI_AMBIENTE', ambiente), ('PHATI_MAPA_TESTE_ATIVO', mapa), ('PHATI_MAPA_FUNDO_GOOGLE_ATIVO', google), ('PHATI_MAPA_GOOGLE_CHAVE', chave)):
        if valor is None:
            monkeypatch.delenv(nome, raising=False)
        else:
            monkeypatch.setenv(nome, valor)
    return runpy.run_path(str(CAMINHO))


def test_google_desligado_e_o_padrao_e_nao_expoe_chave_sobrando(monkeypatch):
    configuracao = _com_google(monkeypatch, None, None, None, None)
    assert configuracao['MAPA_FUNDO_GOOGLE_ATIVO'] is False
    assert configuracao['MAPA_GOOGLE_CHAVE'] == ''


@pytest.mark.parametrize('flag', [None, '', '0', '2', 'true', ' 1'])
def test_so_o_valor_1_liga_o_google(monkeypatch, flag):
    assert _com_google(monkeypatch, 'teste', '1', flag, 'k')['MAPA_FUNDO_GOOGLE_ATIVO'] is False


@pytest.mark.parametrize('ambiente', ['local', 'homologacao', 'teste'])
def test_google_ligado_com_mapa_e_chave_nos_ambientes_de_teste_sobe(monkeypatch, ambiente):
    configuracao = _com_google(monkeypatch, ambiente, '1', '1', 'k')
    assert configuracao['MAPA_FUNDO_GOOGLE_ATIVO'] is True
    assert configuracao['MAPA_GOOGLE_CHAVE'] == 'k'


@pytest.mark.parametrize('chave', [None, ''])
def test_google_ligado_sem_chave_derruba_o_servidor(monkeypatch, chave):
    with pytest.raises(ImproperlyConfigured, match='PHATI_MAPA_GOOGLE_CHAVE'):
        _com_google(monkeypatch, 'teste', '1', '1', chave)


@pytest.mark.parametrize('mapa', [None, '0'])
def test_google_ligado_sem_o_mapa_de_teste_derruba_o_servidor(monkeypatch, mapa):
    with pytest.raises(ImproperlyConfigured, match='PHATI_MAPA_TESTE_ATIVO'):
        _com_google(monkeypatch, 'teste', mapa, '1', 'k')


@pytest.mark.parametrize('ambiente', [None, 'producao', 'qualquer'])
def test_google_ligado_fora_dos_ambientes_de_teste_derruba_o_servidor(monkeypatch, ambiente):
    # Cai na trava do mapa de teste, que vem antes: o Google nunca chega a ligar em produção.
    with pytest.raises(ImproperlyConfigured):
        _com_google(monkeypatch, ambiente, '1', '1', 'k')


def test_politica_do_google_so_acrescenta_a_origem_dos_tiles_em_connect_e_img():
    configuracao = runpy.run_path(str(CAMINHO))
    mapa, google = configuracao['SECURE_CSP_MAPA'], configuracao['SECURE_CSP_MAPA_GOOGLE']
    origem = 'https://tile.googleapis.com'
    assert {k: v for k, v in google.items() if k not in ('connect-src', 'img-src')} == {k: v for k, v in mapa.items() if k != 'img-src'}
    assert google['connect-src'] == ["'self'", origem]
    assert google['img-src'] == mapa['img-src'] + [origem]
    assert all('unsafe-' not in v and v != '*' for valores in google.values() for v in valores)


def test_nginx_entrega_mjs_como_javascript_sem_perder_os_outros_tipos():
    # O mime.types do nginx (1.30 e 1.31.8) não tem `mjs`: sem a regra o MapLibre sai como octet-stream e o módulo é recusado (PR #35).
    # `types` dentro do location substitui o mapa herdado, por isso o bloco inclui o padrão e acrescenta `mjs` ao lado.
    conf = (CAMINHO.parents[1] / 'nginx' / 'default.conf').read_text(encoding='utf-8')
    bloco = re.search(r'location /static/ \{(.*?)\n    \}', conf, re.S)
    assert bloco, 'sem location /static/'
    assert re.search(r'^\s*include mime\.types;', bloco.group(1), re.M)
    assert re.search(r'^\s*types \{ text/javascript mjs; \}', bloco.group(1), re.M)
    # O `mime.types` do nginx já traz o próprio `types { }`: aninhar derruba o nginx na partida.
    assert not re.search(r'types \{[^}]*include', bloco.group(1))
