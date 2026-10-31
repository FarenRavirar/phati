"""Entrada com CPF e senha: o corpo único que a rota `entrar` da API e a tela de login chamam (R4, D061)."""

from django.db import transaction
from django.middleware.csrf import get_token

from identidade import login, sessao


def entrar(requisicao, cpf, senha, dispositivo=None):
    """Autentica e abre o acesso: `(pessoa, segredo)` ou `None`.

    `None` vale para CPF inexistente, de dígito inválido, senha errada, conta bloqueada e senha temporária vencida (A2):
    quem chama não distingue os casos. Com `dispositivo` o aplicativo recebe um `segredo`; sem, o navegador abre a
    sessão e recebe o cookie CSRF (o `segredo` volta `None`).
    """
    segredo = None
    # Autenticar e emitir na mesma transação: a trava da pessoa segue até o fim, então senha temporária consumida
    # não se perde se a emissão falhar, e troca de senha no meio não deixa a senha antiga gerar acesso (Sourcery, PR #14).
    with transaction.atomic():
        pessoa = login.autenticar(cpf, senha)
        if pessoa is None:
            return None
        if dispositivo:
            segredo = sessao.emitir_acesso(pessoa, dispositivo)
        else:
            sessao.iniciar_sessao(requisicao, pessoa)
    if segredo is None:
        get_token(requisicao)  # o CsrfViewMiddleware grava o cookie `csrftoken` na resposta
    return pessoa, segredo
