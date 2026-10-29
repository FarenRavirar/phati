"""E-mail só para credenciais (R6): senha temporária, link de redefinição e aviso de troca.

Toda mensagem do sistema passa por uma destas três funções; nenhum outro módulo envia e-mail (A6).
O envio sai só depois do commit da transação em curso (`on_commit`): rollback não deixa e-mail enviado sem o
dado gravado. Falha do SMTP não derruba quem chamou: vai para o log só com o modelo, a pessoa e o tipo da
exceção (a mensagem carrega a senha temporária ou o link, e a exceção do backend pode citar o endereço). Quem
perdeu a mensagem pede outra: o Administrador reenvia pela redefinição de senha (decisão a confirmar, T5.5a 4 e 5).
"""

import logging
import smtplib
from functools import partial

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction

registro = logging.getLogger(__name__)

MODELOS = ('senha_temporaria', 'redefinicao', 'aviso_de_troca')


def _enviar_agora(pessoa, modelo, assunto, corpo):
    try:
        EmailMessage(assunto, corpo, to=[pessoa.email]).send()
    except (smtplib.SMTPException, OSError) as erro:
        registro.error('falha ao enviar o e-mail %s para a pessoa %s: %s', modelo, pessoa.pk, type(erro).__name__)


def _enviar(pessoa, modelo, assunto, corpo):
    transaction.on_commit(partial(_enviar_agora, pessoa, modelo, assunto, corpo))


def enviar_senha_temporaria(pessoa, senha):
    _enviar(
        pessoa,
        'senha_temporaria',
        'Seu acesso ao phati',
        f'Olá, {pessoa.nome}.\n\nSua senha temporária é: {senha}\n\n'
        'Ela vale por 72 horas e só pode ser usada uma vez. No primeiro acesso o sistema pede que você escolha uma senha nova.',
    )


def enviar_link_de_redefinicao(pessoa, segredo):
    link = f'{settings.URL_BASE}/redefinir-senha?segredo={segredo}'
    _enviar(
        pessoa,
        'redefinicao',
        'Redefinição de senha do phati',
        f'Olá, {pessoa.nome}.\n\nPara escolher uma senha nova, abra o link abaixo em até 10 minutos. Ele só funciona uma vez.\n\n{link}\n\n'
        'Se você não pediu isso, ignore esta mensagem; sua senha atual continua valendo.',
    )


def enviar_aviso_de_troca(pessoa):
    _enviar(
        pessoa,
        'aviso_de_troca',
        'Sua senha do phati foi alterada',
        f'Olá, {pessoa.nome}.\n\nA senha da sua conta foi alterada. Se não foi você, avise o administrador da sua empresa.',
    )
