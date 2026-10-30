"""Cria o primeiro Administrador da plataforma (R20; T5.4). Sem cadastro público, é a única porta de entrada.

A senha temporária sai uma vez na saída padrão e não entra em log nem em auditoria.
"""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from comum.auditoria import auditar
from identidade import senha
from identidade.models import Pessoa


class Command(BaseCommand):
    help = 'Cria um Administrador da plataforma com senha temporária (mostrada uma vez).'

    def add_arguments(self, parser):
        parser.add_argument('--nome', required=True)
        parser.add_argument('--email', required=True)
        parser.add_argument('--cpf', required=True)

    def handle(self, *args, nome, email, cpf, **opcoes):
        try:
            with transaction.atomic():
                pessoa = Pessoa.objects.criar(nome, email, cpf)
                pessoa.administrador_plataforma = True
                pessoa.save(update_fields=['administrador_plataforma'])
                auditar('pessoa_criada', None, pessoa)
                temporaria = senha.emitir_senha_temporaria(pessoa)
        except ValidationError as erro:
            raise CommandError(getattr(erro, 'code', None) or 'entrada_invalida') from None
        self.stdout.write(f'Administrador da plataforma criado (id {pessoa.pk}). Senha temporária: {temporaria}')
