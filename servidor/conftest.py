from itertools import count

import pytest
from django.db import connections


@pytest.fixture(autouse=True)
def _fechar_conexao_app():
    # Conexão aberta do papel `app` impede o pytest-django de descartar o banco de teste.
    yield
    connections['app'].close()


@pytest.fixture(autouse=True)
def _email_na_hora(request, monkeypatch):
    """O teste comum roda numa transação que nunca faz commit, então `on_commit` não dispararia e `mailoutbox`
    ficaria vazia: aqui o envio sai na hora. Teste que exercita o commit pede `django_capture_on_commit_callbacks`
    e fica com o `on_commit` verdadeiro."""
    if 'django_capture_on_commit_callbacks' not in request.fixturenames:
        from types import SimpleNamespace

        monkeypatch.setattr('identidade.email.transaction', SimpleNamespace(on_commit=lambda funcao: funcao()))


def _digito_verificador(digitos):
    soma = sum(digito * peso for digito, peso in zip(digitos, range(len(digitos) + 1, 1, -1)))
    return soma * 10 % 11 % 10


@pytest.fixture
def cpf_novo():
    """Gera CPFs sintéticos válidos e distintos (dado de teste, nunca de cliente: AGENTS.md §Testes)."""
    contador = count(1)

    def gerar():
        base = [int(letra) for letra in f'{next(contador) * 987654321 % 10**9:09d}']
        base.append(_digito_verificador(base))
        base.append(_digito_verificador(base))
        return ''.join(map(str, base))

    return gerar


@pytest.fixture
def fabrica_pessoa(db, cpf_novo):
    from identidade.models import Pessoa

    def criar(nome='Fulana Sintetica', **campos):
        return Pessoa.objects.criar(nome=nome, email='fulana@exemplo.test', cpf=cpf_novo(), **campos)

    return criar


@pytest.fixture
def plataforma(fabrica_pessoa):
    """Administrador da plataforma: pessoa marcada, sem cargo nem concessão."""
    pessoa = fabrica_pessoa('Admin da Plataforma')
    pessoa.administrador_plataforma = True
    pessoa.save(update_fields=['administrador_plataforma'])
    return pessoa


@pytest.fixture
def conceder_direto(db):
    """Grava a concessão sem passar por `pode_conceder`: monta o cenário do teste, não exercita a delegação."""
    from permissao.models import Concessao, ConcessaoCategoria

    def conceder(pessoa, cargo, escopo, categorias=(), **campos):
        from territorio.models import Empresa, Fazenda

        if isinstance(escopo, Empresa):
            lugar = {'empresa': escopo}
        elif isinstance(escopo, Fazenda):
            lugar = {'empresa': escopo.empresa, 'fazenda': escopo}
        else:
            lugar = {'empresa': escopo.empresa, 'fazenda': escopo.fazenda, 'sub_area': escopo}
        campos.setdefault('concedida_por', pessoa)
        concessao = Concessao.objects.create(pessoa=pessoa, cargo=cargo, **lugar, **campos)
        for categoria in categorias:
            ConcessaoCategoria.objects.create(concessao=concessao, categoria=categoria)
        return concessao

    return conceder


@pytest.fixture
def cenario(db):
    """Duas empresas sintéticas. X: fazendas F1 (glebas G1 > talhão T1, e a irmã G2) e F2. Y: fazenda FY."""
    from types import SimpleNamespace

    from permissao.cargos_base import criar_cargos_base
    from territorio.models import Empresa, Fazenda, SubArea

    x = Empresa.objects.create(nome='Empresa X')
    y = Empresa.objects.create(nome='Empresa Y')
    f1 = Fazenda.objects.create(empresa=x, nome='F1')
    f2 = Fazenda.objects.create(empresa=x, nome='F2')
    fy = Fazenda.objects.create(empresa=y, nome='FY')
    g1 = SubArea.objects.create(empresa=x, fazenda=f1, nivel=1, nome='G1')
    t1 = SubArea.objects.create(empresa=x, fazenda=f1, pai=g1, nivel=2, nome='T1')
    g2 = SubArea.objects.create(empresa=x, fazenda=f1, nivel=1, nome='G2')
    for sub_area in (g1, t1, g2):
        sub_area.refresh_from_db()  # o gatilho preenche `caminho`
    return SimpleNamespace(
        x=x, y=y, f1=f1, f2=f2, fy=fy, g1=g1, t1=t1, g2=g2, cargos_x=criar_cargos_base(x), cargos_y=criar_cargos_base(y)
    )


@pytest.fixture
def como_app(transactional_db):
    """Roda o ORM como o papel `app` (o de produção, sujeito à RLS), não como o dono que o teste usa por padrão.

    O papel `app` é outra conexão e só enxerga dado já gravado: use com `django_db(transaction=True)`. O banco do
    teste mantém `default` como dono para as migrações; aqui o alias `default` aponta para a conexão `app`.
    """
    original = connections['default']
    connections['default'] = connections['app']
    yield
    connections['default'] = original


@pytest.fixture
def entrar_no_painel(db):
    """Devolve `entrar(pessoa)`: define uma senha, faz o login pela tela do painel e devolve o cliente já com a sessão."""
    from django.test import Client

    from identidade import cpf as modulo_cpf
    from identidade import senha

    def entrar(pessoa):
        texto = 'uma senha longa e unica 2026'
        senha.definir_senha(pessoa, texto)
        cliente = Client()
        resposta = cliente.post('/painel/login/', {'username': modulo_cpf.decifrar(pessoa.cpf_cifrado), 'password': texto})
        assert resposta.status_code == 302, resposta.content.decode()[:300]
        return cliente

    return entrar
