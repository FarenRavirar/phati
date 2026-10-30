"""E-mail só para credenciais e para o aviso de convite (R6): senha temporária, link de redefinição, aviso de troca e
aviso de convite. O aviso de convite não leva segredo nem link de ação (D053).

Toda mensagem do sistema passa por uma destas quatro funções; nenhum outro módulo envia e-mail (A6).
O envio sai só depois do commit da transação em curso (`on_commit`): rollback não deixa e-mail enviado sem o
dado gravado. Falha do SMTP não derruba quem chamou: vai para o log só com o modelo, a pessoa e o tipo da
exceção (a mensagem carrega a senha temporária ou o link, e a exceção do backend pode citar o endereço). Quem
perdeu a mensagem pede outra: o Administrador reenvia pela redefinição de senha (decisão a confirmar, T5.5a 4 e 5).

O envio roda numa thread, depois da resposta: o SMTP (até `PHATI_EMAIL_PRAZO`) não entra no tempo da resposta, e CPF
existente e inexistente não se distinguem por ele (T5.5c; OWASP Forgot Password, Django #31505). Sem fila durável: se o
processo cair com a thread no meio, a mensagem se perde, como já se perdia na falha de SMTP (outbox é decisão de T5.5a 5).
"""

import logging
import smtplib
import threading
from functools import partial

from django.conf import settings
from django.core.mail import BadHeaderError, EmailMessage
from django.db import transaction
from django.utils import timezone

registro = logging.getLogger(__name__)

MODELOS = ('senha_temporaria', 'redefinicao', 'aviso_de_troca', 'convite')


def _enviar_agora(pessoa, modelo, assunto, corpo):
    falha = None
    try:
        EmailMessage(assunto, corpo, to=[pessoa.email]).send()
    except (smtplib.SMTPException, OSError, BadHeaderError) as erro:
        falha = type(erro).__name__
    if falha is not None:
        # Fora do `except` e sem `exc_info`, de propósito: o texto da exceção do backend pode citar o endereço da
        # pessoa, e o traceback não acrescenta nada que o tipo, o modelo e a pessoa já não digam (Sonar, PR #14).
        registro.error('falha ao enviar o e-mail %s para a pessoa %s: %s', modelo, pessoa.pk, falha)


def _despachar(funcao):
    # `daemon`: thread de e-mail não segura o encerramento do worker. O teste troca esta função pela chamada direta.
    threading.Thread(target=funcao, daemon=True).start()


def _enviar(pessoa, modelo, assunto, corpo):
    transaction.on_commit(partial(_despachar, partial(_enviar_agora, pessoa, modelo, assunto, corpo)))


def enviar_senha_temporaria(pessoa, senha):
    _enviar(
        pessoa,
        'senha_temporaria',
        'Seu acesso ao phati',
        f'Olá, {pessoa.nome}.\n\nSua senha temporária é: {senha}\n\n'
        'Ela vale por 72 horas e só pode ser usada uma vez. No primeiro acesso o sistema pede que você escolha uma senha nova.',
    )


def enviar_link_de_redefinicao(pessoa, segredo):
    link = f'{settings.URL_BASE}/redefinir-senha#segredo={segredo}'
    _enviar(
        pessoa,
        'redefinicao',
        'Redefinição de senha do phati',
        f'Olá, {pessoa.nome}.\n\nPara escolher uma senha nova, abra o link abaixo em até 10 minutos. Ele só funciona uma vez.\n\n{link}\n\n'
        'Se você pediu mais de um link, use o mais recente. Se você não pediu isso, ignore esta mensagem; sua senha atual continua valendo.',
    )


def enviar_aviso_de_troca(pessoa):
    _enviar(
        pessoa,
        'aviso_de_troca',
        'Sua senha do phati foi alterada',
        f'Olá, {pessoa.nome}.\n\nA senha da sua conta foi alterada. Se não foi você, avise o administrador da sua empresa.',
    )


def enviar_aviso_de_convite(pessoa, empresa_nome, cargo_nome, expira_em):
    # Sem segredo e sem link de ação: o aceite é dentro do sistema, com a conta autenticada. Quem não conhece a
    # empresa recusa (padrão de GitHub, WorkOS e Entra: o convidado sempre é avisado e escolhe).
    _enviar(
        pessoa,
        'convite',
        'Você recebeu um convite no phati',
        f'Olá, {pessoa.nome}.\n\nA empresa {empresa_nome} convidou você para participar com o cargo {cargo_nome}. '
        f'Entre no phati em {settings.URL_BASE} para aceitar ou recusar. O convite vale até {timezone.localtime(expira_em):%d/%m/%Y}. '
        'Se você não conhece essa empresa, recuse o convite.',
    )
