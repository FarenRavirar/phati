"""Backend de autenticação por CPF para o `authenticate()` do Django, que o admin usa (T5.5a item 2).

Passa por `login.autenticar` (bloqueio por conta, senha temporária). Falhou: `PermissionDenied` encerra a cadeia, senão o
`ModelBackend` chamaria `get_by_natural_key`, que `GerentePessoa` não tem. O `ModelBackend` continua na lista de
`AUTHENTICATION_BACKENDS` porque `sessao.iniciar_sessao` grava o caminho dele na sessão.
"""

from django.contrib.auth.backends import BaseBackend
from django.core.exceptions import PermissionDenied

from identidade import login
from identidade.models import Pessoa


class BackendCpf(BaseBackend):
    def authenticate(self, request, username=None, password=None, **_):
        if username is None or password is None:
            return None
        pessoa = login.autenticar(username, password)
        if pessoa is None:
            raise PermissionDenied
        return pessoa

    def get_user(self, user_id):
        return Pessoa.objects.filter(pk=user_id).first()
