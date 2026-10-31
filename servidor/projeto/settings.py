import base64
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP

DIRETORIO_BASE = Path(__file__).resolve().parent.parent

# Configuração só por variável de ambiente (nomes em .env.exemplo); nenhum segredo no repositório.
SECRET_KEY = os.environ['PHATI_CHAVE_SECRETA']
DEBUG = os.environ.get('PHATI_DEPURACAO') == '1'
ALLOWED_HOSTS = [h for h in os.environ.get('PHATI_HOSTS_PERMITIDOS', '').split(',') if h]

INSTALLED_APPS = [
    'comum',
    # contenttypes e auth: `django.contrib.auth.get_user` importa auth.models (AnonymousUser); sessions: sessão
    # de navegador com revogação no servidor (R15). Os três migram depois de `comum` (run_before em comum/0001).
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.sessions',
    # Painel (T5.2): `ConfiguracaoDoPainel` no lugar de `django.contrib.admin`, para o site ser o `PainelSite`.
    'projeto.apps.ConfiguracaoDoPainel',
    'django.contrib.messages',
    'projeto.apps.ConfiguracaoDosEstaticos',  # `django.contrib.staticfiles` sem publicar os testes de JS
    # API JSON `/api/v1/` (T5.1); precisa estar aqui para o comando `export_openapi_schema` existir.
    'ninja',
    'identidade',
    'territorio',
    'permissao',
]

# Sessão e CSRF só para a API (cookie de navegador); a ordem é a que o Django exige: sessão antes de autenticação.
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.csp.ContentSecurityPolicyMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    # `X-Frame-Options: DENY` (padrão do Django): o painel não pode ser embutido em outro site (Qodo, PR #16).
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
# A senha temporária criada no painel vai numa mensagem: na sessão do servidor, nunca no cookie `messages`, que o
# navegador lê e o proxy pode registrar (Qodo, PR #16).
MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # `projeto` não é app com `templates/` próprio (o app do painel é o do admin): a página de redefinição mora aqui.
        'DIRS': [Path(__file__).resolve().parent / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.csp',
            ],
        },
    },
]
STATIC_URL = 'static/'  # `collectstatic` e o servidor dos arquivos entram no deploy (T6.5)
# `projeto` não é app instalado (o app do painel é o do admin): o `AppDirectoriesFinder` não acharia `static/projeto/`.
STATICFILES_DIRS = [Path(__file__).resolve().parent / 'static']
STATIC_ROOT = os.environ.get('PHATI_ESTATICOS', '/estaticos')  # volume que o nginx serve (D070)

# Política de conteúdo (R14): script só do próprio site ou com nonce, sem `unsafe-inline`. O nonce é preguiçoso: só sai
# no cabeçalho se um template o toca, e os moldes o tocam em `{% csp_nonce_attr %}`. `style-src` leva o nonce porque o
# `change_list.html` do admin do Django 6.1 tem um `<style>` com nonce; as páginas do phati não usam estilo inline.
SECURE_CSP = {
    'default-src': [CSP.SELF],
    'script-src': [CSP.SELF, CSP.NONCE],
    'style-src': [CSP.SELF, CSP.NONCE],
    'img-src': [CSP.SELF, 'data:'],
    'object-src': [CSP.NONE],
    'form-action': [CSP.SELF],
    'frame-ancestors': [CSP.NONE],
    'base-uri': [CSP.SELF],
}
# As páginas de erro e de falha de CSRF recebem a requisição (o padrão do Django não a passa), para levar o nonce.
CSRF_FAILURE_VIEW = 'projeto.paginas.falha_csrf'

# O segredo do link de redefinição vai no fragmento da URL (nunca chega ao servidor) e, por garantia, nenhuma
# resposta deixa o navegador mandar a URL de origem a terceiros (T5.5a item 1; OWASP Forgot Password Cheat Sheet).
# `same-origin`, não `no-referrer`: com `no-referrer` o navegador manda `Origin: null` no POST de formulário e o Django
# recusa por CSRF (medido no Chromium em 2026-10-31: o login dava 403). `same-origin` não envia nada a terceiros.
SECURE_REFERRER_POLICY = 'same-origin'

ROOT_URLCONF = 'projeto.urls'

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


def _configuracao_banco(usuario, senha):
    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('PHATI_BANCO_NOME', 'phati'),
        'HOST': os.environ.get('PHATI_BANCO_HOST', '127.0.0.1'),
        'PORT': os.environ.get('PHATI_BANCO_PORTA', '5432'),
        'USER': os.environ[usuario],
        'PASSWORD': os.environ[senha],
    }


_banco_app = _configuracao_banco('PHATI_BANCO_APP_USUARIO', 'PHATI_BANCO_APP_SENHA')

# `app` é o papel da aplicação: não é dono das tabelas e não tem BYPASSRLS, então a RLS da Fase 4 vale
# para ele (plan.md §Camada de banco). O papel dono só entra no processo que recebe a senha dele
# (migração e testes); no processo web o `default` é o próprio `app`, e `.using()` omitido nunca roda como dono.
DATABASES = {
    'default': (
        _configuracao_banco('PHATI_BANCO_DONO_USUARIO', 'PHATI_BANCO_DONO_SENHA')
        if 'PHATI_BANCO_DONO_SENHA' in os.environ
        else _banco_app
    ),
    'app': {**_banco_app, 'TEST': {'MIRROR': 'default'}},
}

# Pessoa é o usuário do sistema (R1); a senha usa só Argon2id (R3; parâmetros e fonte em identidade/senha.py).
AUTH_USER_MODEL = 'identidade.Pessoa'
PASSWORD_HASHERS = ['identidade.senha.GeradorHashArgon2']
URL_BASE = os.environ.get('PHATI_URL_BASE', 'http://localhost:8000')  # link de redefinição nunca usa o cabeçalho Host (R5)

# Raiz da chave do CPF (plan.md §Autenticação): 32 bytes em base64 urlsafe; as subchaves de busca e de cifra saem
# dela por HKDF (identidade/cpf.py). Gerar: python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
def _chave_de_32_bytes(nome):
    try:
        bruta = base64.urlsafe_b64decode(os.environ[nome].encode('ascii'))
        # Decodificação tolerante descarta caractere inválido sem avisar; a recodificação confere a forma canônica.
        if len(bruta) != 32 or base64.urlsafe_b64encode(bruta).decode() != os.environ[nome]:
            raise ValueError
    except (KeyError, ValueError) as erro:
        raise ImproperlyConfigured(f'{nome} ausente ou fora do formato base64 urlsafe de 32 bytes.') from erro
    return bruta


CHAVE_CPF = _chave_de_32_bytes('PHATI_CHAVE_CPF')
# Segredo da assinatura do contexto de RLS (permissao/contexto.py): a migração 0004 grava uma cópia em `rls_segredo`,
# que o papel `app` não lê. Mesmo formato da chave do CPF; gerar com o mesmo comando.
SEGREDO_RLS = _chave_de_32_bytes('PHATI_SEGREDO_RLS')

# Sessão de navegador (R15): ociosidade e duração absoluta; o cookie é emitido pela API (Fase 5).
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 12 * 3600  # teto absoluto de 12 h; a ociosidade de 30 min vem em sessao.py
SESSAO_OCIOSIDADE_SEGUNDOS = 30 * 60
ACESSO_APLICATIVO_DIAS = 30  # deslizante e teto absoluto desde o login (NIST SP 800-63B-4, AAL1)
# Depois da rotação, o segredo antigo ainda troca por outro durante esta janela (resposta perdida, retry); passada
# a janela, usá-lo é reuso e derruba a sequência. Okta usa 30 s por padrão (0 a 60); Auth0 chama de overlap.
ACESSO_APLICATIVO_JANELA_SEGUNDOS = 30

# Bloqueio por conta (R2): após LIMITE falhas seguidas, BASE segundos, dobrando a cada falha até TETO.
AUTENTICACAO_FALHAS_LIMITE = 5
AUTENTICACAO_BLOQUEIO_BASE_SEGUNDOS = 30
AUTENTICACAO_BLOQUEIO_TETO_SEGUNDOS = 15 * 60

# `ModelBackend` fica porque `sessao.iniciar_sessao` grava o caminho dele; o do CPF vem antes (T5.5a item 2).
AUTHENTICATION_BACKENDS = ['identidade.backend.BackendCpf', 'django.contrib.auth.backends.ModelBackend']

# E-mail só para credenciais (R6); SMTP por configuração.
MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
        'OPTIONS': {
            'host': os.environ.get('PHATI_EMAIL_HOST', 'localhost'),
            'port': int(os.environ.get('PHATI_EMAIL_PORTA', '587')),
            'username': os.environ.get('PHATI_EMAIL_USUARIO', ''),
            'password': os.environ.get('PHATI_EMAIL_SENHA', ''),
            'use_tls': True,
            'timeout': int(os.environ.get('PHATI_EMAIL_PRAZO', '10')),  # sem prazo, SMTP mudo prenderia o processo (achado do Qodo, PR #9)
        },
    },
}
DEFAULT_FROM_EMAIL = os.environ.get('PHATI_EMAIL_REMETENTE', 'phati@localhost')
