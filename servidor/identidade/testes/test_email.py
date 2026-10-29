"""A6 (R6): só três modelos de mensagem, e todo envio passa por eles."""

import re
import smtplib
from pathlib import Path

import pytest
from django.conf import settings
from django.db import transaction

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
        if 'testes' not in arquivo.relative_to(RAIZ).parts
        and 'migrations' not in arquivo.relative_to(RAIZ).parts
        and arquivo.name not in ('email.py', 'settings.py')
        and envio.search(arquivo.read_text(encoding='utf-8'))
    ]
    assert fora == []


class _Desfaz(Exception):
    pass


def test_rollback_da_transacao_nao_envia_o_email(pessoa, mailoutbox, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True) as chamadas:
        with pytest.raises(_Desfaz):
            with transaction.atomic():
                email.enviar_aviso_de_troca(pessoa)
                raise _Desfaz
    assert chamadas == []
    assert mailoutbox == []


def test_email_so_sai_depois_do_commit(pessoa, mailoutbox, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True) as chamadas:
        email.enviar_aviso_de_troca(pessoa)
        assert mailoutbox == []
    assert len(chamadas) == 1
    assert len(mailoutbox) == 1


def test_falha_do_smtp_vai_para_o_log_sem_senha_nem_texto_da_excecao(pessoa, monkeypatch, caplog):
    def falha(*_):
        raise smtplib.SMTPException('texto-da-excecao')

    monkeypatch.setattr(email.EmailMessage, 'send', falha)
    email.enviar_senha_temporaria(pessoa, 'ABC123')
    assert 'senha_temporaria' in caplog.text
    assert 'SMTPException' in caplog.text
    assert 'ABC123' not in caplog.text
    assert 'texto-da-excecao' not in caplog.text
