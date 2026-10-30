"""Página de destino do link de redefinição de senha (R5, T5.5g). O segredo vem no fragmento `#segredo=` e o script da
própria página o envia por POST JSON a `/api/v1/redefinir-senha/confirmar`; o servidor nunca o vê na URL."""

from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
@never_cache
def redefinir_senha(requisicao):
    return render(requisicao, 'redefinir_senha.html')


def falha_csrf(requisicao, reason=''):
    return render(requisicao, '403_csrf.html', status=403)


def erro_500(requisicao):
    return render(requisicao, '500.html', status=500)
