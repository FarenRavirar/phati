"""`gerar_pacote_fazenda`: casca de `pacote.geracao.gerar_pacote` (004b R2). A barreira real é o acesso ao shell do servidor."""

from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from identidade.models import Pessoa
from pacote import geracao
from permissao.pode import com_permissao
from territorio.models import Fazenda


class Command(BaseCommand):
    """Comando de linha de comando; a regra mora em `pacote.geracao`."""
    help = 'Gera a próxima versão do pacote offline de uma fazenda (Administrador da plataforma).'

    def add_arguments(self, parser):
        """Declara fazenda, operador, caixa, origens e zooms. Use `--caixa=` com igual: o valor começa com "-"."""
        parser.add_argument('fazenda', type=int, help='id da fazenda')
        parser.add_argument('--operador', type=int, required=True, help='id da pessoa (Administrador da plataforma)')
        parser.add_argument('--caixa', required=True, help='oeste,sul,leste,norte em WGS 84')
        parser.add_argument('--fundo-origem', required=True, help='PMTiles vetorial aberto, arquivo local')
        parser.add_argument('--ortofoto', help='GeoTIFF/COG da ortofoto (opcional)')
        parser.add_argument('--ortofoto-data', type=date.fromisoformat, help='data de captura, AAAA-MM-DD')
        parser.add_argument('--zoom-maximo-fundo', type=int, default=geracao.ZOOM_MAXIMO_FUNDO_PADRAO)
        parser.add_argument('--zoom-minimo-ortofoto', type=int, default=geracao.ZOOM_MINIMO_ORTOFOTO_PADRAO)
        parser.add_argument('--zoom-maximo-ortofoto', type=int, default=geracao.ZOOM_MAXIMO_ORTOFOTO_PADRAO)

    def handle(self, *args, **opcoes):
        """Resolve operador e fazenda, chama `gerar_pacote` e traduz os erros esperados em `CommandError`."""
        try:
            quem = Pessoa.objects.get(pk=opcoes['operador'])
            with com_permissao(quem):  # o papel `app` só enxerga fazenda dentro do escopo da pessoa (RLS)
                fazenda = Fazenda.objects.get(pk=opcoes['fazenda'])
        except (Pessoa.DoesNotExist, Fazenda.DoesNotExist) as erro:
            raise CommandError(f'Não encontrei: {erro}') from erro
        try:
            versao = geracao.gerar_pacote(
                quem, fazenda, opcoes['caixa'].split(','), fundo_origem=opcoes['fundo_origem'],
                ortofoto=opcoes['ortofoto'], ortofoto_capturada_em=opcoes['ortofoto_data'],
                zoom_maximo_fundo=opcoes['zoom_maximo_fundo'], zoom_minimo_ortofoto=opcoes['zoom_minimo_ortofoto'],
                zoom_maximo_ortofoto=opcoes['zoom_maximo_ortofoto'],
            )
        except PermissionDenied as erro:
            raise CommandError('O operador não é Administrador da plataforma.') from erro
        except (ValidationError, geracao.ErroDeGeracao) as erro:
            raise CommandError(str(erro)) from erro
        self.stdout.write(f'Versão {versao.numero} da fazenda {fazenda.pk} gerada e vigente.')
