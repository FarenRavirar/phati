"""Backend por CPF no `authenticate()` do Django (T5.5a item 2) e timeout do SMTP configurável (item 6)."""

from importlib import reload

from django.contrib.auth import authenticate

from identidade import senha
from identidade.models import Pessoa

SENHA = 'uma senha longa e unica 2026'
ERRADA = 'outra senha qualquer 2026'


def _pessoa_com_senha(fabrica_pessoa, texto):
    pessoa = fabrica_pessoa('Ana')
    senha.definir_senha(pessoa, texto)
    return pessoa


def test_authenticate_do_django_entra_pelo_cpf_formatado(fabrica_pessoa, cpf_novo):
    from identidade import cpf as modulo_cpf

    pessoa = _pessoa_com_senha(fabrica_pessoa, SENHA)
    cpf = modulo_cpf.decifrar(pessoa.cpf_cifrado)
    assert authenticate(username=cpf, password=SENHA) == pessoa


def test_senha_errada_ou_cpf_inexistente_devolve_none_sem_erro_do_gerente(fabrica_pessoa, cpf_novo):
    from identidade import cpf as modulo_cpf

    pessoa = _pessoa_com_senha(fabrica_pessoa, SENHA)
    assert authenticate(username=modulo_cpf.decifrar(pessoa.cpf_cifrado), password=ERRADA) is None
    assert authenticate(username=cpf_novo(), password=ERRADA) is None
    assert Pessoa.objects.get(pk=pessoa.pk).falhas_consecutivas == 1


def test_timeout_do_smtp_vem_do_ambiente(monkeypatch):
    import projeto.settings as configuracao

    monkeypatch.setenv('PHATI_EMAIL_PRAZO', '3')
    try:
        assert reload(configuracao).MAILERS['default']['OPTIONS']['timeout'] == 3
        monkeypatch.delenv('PHATI_EMAIL_PRAZO')
        assert reload(configuracao).MAILERS['default']['OPTIONS']['timeout'] == 10
    finally:
        monkeypatch.delenv('PHATI_EMAIL_PRAZO', raising=False)
        reload(configuracao)
