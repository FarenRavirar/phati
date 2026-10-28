"""A6 (R6): só três modelos de mensagem, e todo envio passa por eles."""

import re
from pathlib import Path

from django.conf import settings

from identidade import email

RAIZ = Path(settings.DIRETORIO_BASE)


def test_tres_modelos_um_para_cada_credencial(pessoa, mailoutbox):
    email.enviar_senha_temporaria(pessoa, 'ABC123')
    email.enviar_link_de_redefinicao(pessoa, 'segredo')
    email.enviar_aviso_de_troca(pessoa)
    assert [m.to for m in mailoutbox] == [[pessoa.email]] * 3
    assert 'ABC123' in mailoutbox[0].body
    assert f'{settings.URL_BASE}/redefinir-senha?segredo=segredo' in mailoutbox[1].body
    assert len({m.subject for m in mailoutbox}) == 3


def test_so_existem_tres_funcoes_de_envio():
    fonte = Path(email.__file__).read_text(encoding='utf-8')
    assert len(re.findall(r'^def enviar_', fonte, re.M)) == len(email.MODELOS) == 3


def test_nenhum_outro_modulo_envia_email():
    envio = re.compile(r'\b(send_mail|send_mass_mail|mail_admins|mail_managers|EmailMessage|EmailMultiAlternatives|mailers)\b')
    fora = [
        str(arquivo.relative_to(RAIZ))
        for arquivo in RAIZ.rglob('*.py')
        if 'testes' not in arquivo.parts
        and 'migrations' not in arquivo.parts
        and arquivo.name not in ('email.py', 'settings.py')
        and envio.search(arquivo.read_text(encoding='utf-8'))
    ]
    assert fora == []
