"""Páginas de acesso: entrar, sair, trocar senha e esqueci a senha (R4 a R8). A regra mora em `identidade`; aqui só
ficam o formulário, a mensagem e o destino."""

from urllib.parse import urlencode

from django.contrib.auth import logout
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from identidade import acesso, redefinicao, senha
from projeto.paginas_autenticadas import CAMINHO_ENTRAR, CAMINHO_TROCAR_SENHA, PROPRIA_PESSOA, destino_seguro, exige_acao, exige_entrada

MENSAGEM_DE_FALHA = 'CPF ou senha incorretos.'
# O que fazer em cada recusa da validação; o número do limite vem de `senha`, não é copiado aqui (T3.6 a).
TEXTOS_DA_SENHA = {
    'senha_curta': f'A senha precisa ter pelo menos {senha.COMPRIMENTO_MINIMO} caracteres.',
    'senha_longa': f'A senha pode ter no máximo {senha.COMPRIMENTO_MAXIMO} caracteres.',
    'senha_comum': 'Essa senha é comum demais. Escolha outra.',
    'senha_contexto': 'A senha não pode conter seu nome, e-mail ou CPF.',
}


def _com_proximo(caminho, proximo, **consulta):
    # `proximo` já validado por `destino_seguro`; só `/` (o padrão) fica de fora da URL.
    destino = destino_seguro(proximo)
    if destino != '/':
        consulta['proximo'] = destino
    return f'{caminho}?{urlencode(consulta)}' if consulta else caminho


@require_http_methods(['GET', 'POST'])
@never_cache
def entrar(requisicao):
    proximo = requisicao.POST.get('proximo') or requisicao.GET.get('proximo', '')
    contexto = {'proximo': proximo, 'expirou': requisicao.GET.get('expirou') == '1', 'trocada': requisicao.GET.get('trocada') == '1'}
    if requisicao.method == 'POST':
        entrada = acesso.entrar(requisicao, requisicao.POST.get('cpf', ''), requisicao.POST.get('senha', ''))
        if entrada is not None:
            pessoa, _ = entrada
            return redirect(_com_proximo(CAMINHO_TROCAR_SENHA, proximo) if pessoa.deve_trocar_senha else destino_seguro(proximo))
        contexto.update(erro=MENSAGEM_DE_FALHA, cpf=requisicao.POST.get('cpf', ''), expirou=False)
    return render(requisicao, 'entrar.html', contexto)


@require_POST
def sair(requisicao):
    logout(requisicao)
    return redirect(CAMINHO_ENTRAR)


@require_http_methods(['GET', 'POST'])
@exige_entrada
@exige_acao(PROPRIA_PESSOA)
def trocar_senha(requisicao):
    proximo = requisicao.POST.get('proximo') or requisicao.GET.get('proximo', '')
    contexto = {'obrigatoria': requisicao.user.deve_trocar_senha, 'proximo': proximo}
    if requisicao.method == 'POST':
        nova = requisicao.POST.get('senha_nova', '')
        if nova != requisicao.POST.get('repeticao', ''):
            contexto['erro'] = 'As senhas não são iguais.'
        else:
            try:
                senha.trocar_senha(requisicao.user, requisicao.POST.get('senha_atual', ''), nova)
            except ValidationError as erro:
                contexto['erro'] = TEXTOS_DA_SENHA.get(erro.code or '',erro.messages[0])
            else:
                # A troca invalida a sessão (R15 da 001): a pessoa entra de novo com a senha nova.
                logout(requisicao)
                return redirect(_com_proximo(CAMINHO_ENTRAR, proximo, trocada=1))
    return render(requisicao, 'trocar_senha.html', contexto)


@require_http_methods(['GET', 'POST'])
@never_cache
def esqueci_senha(requisicao):
    contexto = {}
    if requisicao.method == 'POST':
        redefinicao.pedir_redefinicao_anonimo(requisicao.POST.get('cpf', ''))
        contexto['pedido'] = True
    return render(requisicao, 'esqueci_senha.html', contexto)
