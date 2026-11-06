"""Monitor de uso do Google (004b R13): só o Administrador da plataforma abre; os demais recebem 404 por URL direta (A10)."""

from django.conf import settings
from django.http import Http404
from django.utils import timezone
from django.views.decorators.http import require_GET

from permissao.pode import pode
from projeto import uso_google
from projeto.monitoramento_google import CloudMonitoring
from projeto.paginas_autenticadas import exige_acao, exige_entrada, renderizar_na_casca


def _fonte():
    """Sem credencial configurada a tela mostra "não medido": a fonte nunca é inventada."""
    return CloudMonitoring(settings.GOOGLE_MONITORING_CREDENCIAL) if settings.GOOGLE_MONITORING_CREDENCIAL else None


def _linha(janela):
    medido = janela.usados is not None
    return [
        janela.nome,
        f'{janela.usados:,}'.replace(',', '.') if medido else uso_google.NAO_MEDIDO,
        f'{janela.total:,}'.replace(',', '.'),
        janela.renova_em.strftime('%d/%m/%Y %H:%M (horário do Pacífico)'),
        f'{janela.porcentagem:.1f}%'.replace('.', ',') if janela.porcentagem is not None else uso_google.NAO_MEDIDO,
        janela.origem,
    ]


@require_GET
@exige_entrada
@exige_acao('ver_monitor_google')
def monitor(requisicao):
    if not pode(requisicao.user, 'ver_monitor_google'):
        raise Http404
    janelas = uso_google.janelas(timezone.now(), settings.MAPA_GOOGLE_COTA_DIARIA, settings.MAPA_GOOGLE_GRATIS_MENSAL, _fonte())
    contexto = {
        'colunas': ['Janela', 'Usados', 'Total', 'Renova em', 'Usado (%)', 'Origem do número'],
        'linhas': [_linha(janela) for janela in janelas],
    }
    return renderizar_na_casca(requisicao, 'monitor_google.html', contexto)
