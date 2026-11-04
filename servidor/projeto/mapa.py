"""Mapa de teste de layout (004 R1, R3): a flag e a política de conteúdo só da resposta que leva o mapa.

Flag desligada: a página da fazenda é a da 003 e a CSP é a da 002. A flag nunca liga fora de `AMBIENTES_DE_TESTE`
(trava na partida, `settings.py`)."""

from django.conf import settings


def mapa_ativo():
    return settings.MAPA_TESTE_ATIVO


def com_politica_do_mapa(resposta):
    """Troca a CSP só desta resposta (`csp_override` substitui a política, não soma; a de `SECURE_CSP_MAPA` já é completa)."""
    if mapa_ativo():
        resposta._csp_config = settings.SECURE_CSP_MAPA
    return resposta
