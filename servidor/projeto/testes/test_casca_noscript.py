"""Casca: "Cadastrar empresa" e "Arquivadas" também saem no <noscript> do seletor, com as mesmas condições de permissão
(sem JS a lista do seletor fica `hidden` e os links seriam inalcançáveis)."""

import re
from uuid import uuid4

from django.utils import timezone

from territorio.models import Fazenda


def _noscript(html):
    return ' '.join(re.findall(r'<noscript>(.*?)</noscript>', html, re.S))


def test_noscript_leva_cadastrar_e_arquivadas_a_quem_tem_as_duas(cliente_logado, conta, cenario):
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    Fazenda.objects.create(empresa=cenario.x, nome='Velha', arquivada_em=timezone.now(), arquivada_por=conta.pessoa, arquivamento=uuid4())
    html = cliente_logado.get('/empresas/').content.decode()
    assert 'href="/empresas/nova"' in _noscript(html)
    assert 'Cadastrar empresa' in _noscript(html)
    assert 'href="/arquivadas/"' in _noscript(html)
    assert 'Arquivadas' in _noscript(html)


def test_noscript_sem_permissao_nao_leva_a_cadastrar_nem_a_arquivadas(cliente_logado, cenario):
    html = cliente_logado.get('/empresas/').content.decode()
    assert 'href="/empresas/nova"' not in _noscript(html)
    assert 'href="/arquivadas/"' not in _noscript(html)


def test_noscript_so_com_arquivadas_nao_leva_a_cadastrar(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    Fazenda.objects.create(empresa=cenario.x, nome='Velha', arquivada_em=timezone.now(), arquivada_por=conta.pessoa, arquivamento=uuid4())
    html = cliente_logado.get('/empresas/').content.decode()
    assert 'href="/arquivadas/"' in _noscript(html)
    assert 'href="/empresas/nova"' not in _noscript(html)
