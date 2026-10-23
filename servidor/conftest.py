import pytest
from django.db import connections


@pytest.fixture(autouse=True)
def _fechar_conexao_app():
    # Conexão aberta do papel `app` impede o pytest-django de descartar o banco de teste.
    yield
    connections['app'].close()
