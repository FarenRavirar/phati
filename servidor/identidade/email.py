"""E-mail só para credenciais (R6): senha temporária, link de redefinição e aviso de troca.

Toda mensagem do sistema passa por uma destas três funções; nenhum outro módulo envia e-mail (A6).
Falha de envio levanta a exceção do backend para quem chamou; nada é registrado em log (a mensagem
carrega a senha temporária ou o link).
"""

from django.conf import settings
from django.core.mail import EmailMessage

MODELOS = ('senha_temporaria', 'redefinicao', 'aviso_de_troca')


def _enviar(pessoa, assunto, corpo):
    EmailMessage(assunto, corpo, to=[pessoa.email]).send()


def enviar_senha_temporaria(pessoa, senha):
    _enviar(
        pessoa,
        'Seu acesso ao phati',
        f'Olá, {pessoa.nome}.\n\nSua senha temporária é: {senha}\n\n'
        'Ela vale por 72 horas e só pode ser usada uma vez. No primeiro acesso o sistema pede que você escolha uma senha nova.',
    )


def enviar_link_de_redefinicao(pessoa, segredo):
    link = f'{settings.URL_BASE}/redefinir-senha?segredo={segredo}'
    _enviar(
        pessoa,
        'Redefinição de senha do phati',
        f'Olá, {pessoa.nome}.\n\nPara escolher uma senha nova, abra o link abaixo em até 10 minutos. Ele só funciona uma vez.\n\n{link}\n\n'
        'Se você não pediu isso, ignore esta mensagem; sua senha atual continua valendo.',
    )


def enviar_aviso_de_troca(pessoa):
    _enviar(
        pessoa,
        'Sua senha do phati foi alterada',
        f'Olá, {pessoa.nome}.\n\nA senha da sua conta foi alterada. Se não foi você, avise o administrador da sua empresa.',
    )
