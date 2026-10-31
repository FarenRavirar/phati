"""Páginas de acesso: entrar, sair, trocar senha e esqueci a senha (R4 a R8). A regra mora em `identidade`; aqui só
ficam o formulário, a mensagem e o destino."""

from django.contrib.auth import logout
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from identidade import acesso, redefinicao, senha
from projeto.paginas_autenticadas import CAMINHO_ENTRAR, CAMINHO_TROCAR_SENHA, destino_seguro, exige_entrada

MENSAGEM_DE_FALHA = 'CPF ou senha incorretos.'
MENSAGEM_NEUTRA = 'Se o CPF estiver cadastrado, enviamos um link de redefinição para o e-mail da conta.'


@require_http_methods(['GET', 'POST'])
@never_cache
def entrar(requisicao):
    proximo = requisicao.POST.get('proximo') or requisicao.GET.get('proximo', '')
    contexto = {'proximo': proximo, 'expirou': requisicao.GET.get('expirou') == '1', 'trocada': requisicao.GET.get('trocada') == '1'}
    if requisicao.method == 'POST':
        entrada = acesso.entrar(requisicao, requisicao.POST.get('cpf', ''), requisicao.POST.get('senha', ''))
        if entrada is not None:
            pessoa, _ = entrada
            return redirect(CAMINHO_TROCAR_SENHA if pessoa.deve_trocar_senha else destino_seguro(proximo))
        contexto.update(erro=MENSAGEM_DE_FALHA, cpf=requisicao.POST.get('cpf', ''), expirou=False)
    return render(requisicao, 'entrar.html', contexto)


@require_POST
def sair(requisicao):
    logout(requisicao)
    return redirect(CAMINHO_ENTRAR)


@require_http_methods(['GET', 'POST'])
@exige_entrada
def trocar_senha(requisicao):
    contexto = {'obrigatoria': requisicao.user.deve_trocar_senha}
    if requisicao.method == 'POST':
        nova = requisicao.POST.get('senha_nova', '')
        if nova != requisicao.POST.get('repeticao', ''):
            contexto['erro'] = 'As senhas não são iguais.'
        else:
            try:
                senha.trocar_senha(requisicao.user, requisicao.POST.get('senha_atual', ''), nova)
            except ValidationError as erro:
                contexto['erro'] = erro.messages[0]
            else:
                # A troca invalida a sessão (R15 da 001): a pessoa entra de novo com a senha nova.
                logout(requisicao)
                return redirect(f'{CAMINHO_ENTRAR}?trocada=1')
    return render(requisicao, 'trocar_senha.html', contexto)


@require_http_methods(['GET', 'POST'])
@never_cache
def esqueci_senha(requisicao):
    contexto = {}
    if requisicao.method == 'POST':
        redefinicao.pedir_redefinicao(requisicao.POST.get('cpf', ''))
        contexto['pedido'] = True
    return render(requisicao, 'esqueci_senha.html', contexto)
