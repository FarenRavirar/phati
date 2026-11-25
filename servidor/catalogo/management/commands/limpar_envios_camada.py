"""Apaga envios de camada vencidos e os originais deles (008 T2.4). Manutenção manual: sem agendador (cron na VM é outra spec)."""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from catalogo.envios import limpar_expirados
from identidade.models import Pessoa


class Command(BaseCommand):
    help = 'Apaga envios de camada expirados e seus originais em CAMADAS_DIR. Rodar com --operador da plataforma.'

    def add_arguments(self, parser):
        parser.add_argument('--operador', type=int, required=True, help='id da pessoa que executa (Administrador da plataforma)')

    def handle(self, *args, operador, **opcoes):
        try:
            quem = Pessoa.objects.get(pk=operador)
        except Pessoa.DoesNotExist as erro:
            raise CommandError('operador não encontrado') from erro
        removidos, ignorados = limpar_expirados(quem, timezone.now())
        self.stdout.write(f'{removidos} envio(s) expirado(s) removido(s); {ignorados} ignorado(s) por nome interno inválido')
