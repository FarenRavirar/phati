import os
from pathlib import Path

DIRETORIO_BASE = Path(__file__).resolve().parent.parent

# Configuração só por variável de ambiente (nomes em .env.exemplo); nenhum segredo no repositório.
SECRET_KEY = os.environ['PHATI_CHAVE_SECRETA']
DEBUG = os.environ.get('PHATI_DEPURACAO') == '1'
ALLOWED_HOSTS = [h for h in os.environ.get('PHATI_HOSTS_PERMITIDOS', '').split(',') if h]

INSTALLED_APPS = [
    'comum',
    'identidade',
    'territorio',
    'permissao',
]

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
