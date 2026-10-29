import base64
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

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
    # API JSON `/api/v1/` (T5.1); precisa estar aqui para o comando `export_openapi_schema` existir.
    'ninja',
    'identidade',
    'territorio',
    'permissao',
]

# Sessão e CSRF só para a API (cookie de navegador); a ordem é a que o Django exige: sessão antes de autenticação.
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
]
# O segredo do link de redefinição vai no fragmento da URL (nunca chega ao servidor) e, por garantia, nenhuma
# resposta deixa o navegador mandar a URL de origem a terceiros (T5.5a item 1; OWASP Forgot Password Cheat Sheet).
SECURE_REFERRER_POLICY = 'no-referrer'

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
try:
    CHAVE_CPF = base64.urlsafe_b64decode(os.environ['PHATI_CHAVE_CPF'].encode('ascii'))
    # Decodificação tolerante descarta caractere inválido sem avisar; a recodificação confere a forma canônica.
    if len(CHAVE_CPF) != 32 or base64.urlsafe_b64encode(CHAVE_CPF).decode() != os.environ['PHATI_CHAVE_CPF']:
        raise ValueError
except (KeyError, ValueError) as erro:
    raise ImproperlyConfigured('PHATI_CHAVE_CPF ausente ou fora do formato base64 urlsafe de 32 bytes.') from erro

# Sessão de navegador (R15): ociosidade e duração absoluta; o cookie é emitido pela API (Fase 5).
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 12 * 3600  # teto absoluto de 12 h; a ociosidade de 30 min vem em sessao.py
SESSAO_OCIOSIDADE_SEGUNDOS = 30 * 60
ACESSO_APLICATIVO_DIAS = 30  # deslizante e teto absoluto desde o login (NIST SP 800-63B-4, AAL1)

# Bloqueio por conta (R2): após LIMITE falhas seguidas, BASE segundos, dobrando a cada falha até TETO.
AUTENTICACAO_FALHAS_LIMITE = 5
AUTENTICACAO_BLOQUEIO_BASE_SEGUNDOS = 30
AUTENTICACAO_BLOQUEIO_TETO_SEGUNDOS = 15 * 60

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
            'timeout': 10,  # sem prazo, SMTP mudo prenderia o processo (achado do Qodo, PR #9)
        },
    },
}
DEFAULT_FROM_EMAIL = os.environ.get('PHATI_EMAIL_REMETENTE', 'phati@localhost')
