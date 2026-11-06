"""Comando `gerar_pacote_fazenda` (004b R2, A2): só a casca; a regra está em `test_geracao.py`."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from pacote.models import VersaoPacote
from pacote.testes.conftest import CAIXA, REFERENCIA

FUNDO = str(REFERENCIA / 'fundo.pmtiles')
CAIXA_TEXTO = ','.join(str(v) for v in CAIXA)


def _chamar(fazenda, operador, saida=None, caixa=CAIXA_TEXTO, fazenda_id=None, operador_id=None):
    # `--caixa=` com igual: argparse leria `--caixa -48,...` como outra opção, porque o valor começa com "-".
    call_command(
        'gerar_pacote_fazenda', str(fazenda_id or fazenda.pk), '--operador', str(operador_id or operador.pk),
        f'--caixa={caixa}', '--fundo-origem', FUNDO, stdout=saida,
    )


def test_gera_e_diz_a_versao(pacotes, cenario, plataforma):
    saida = StringIO()
    _chamar(cenario.f1, plataforma, saida)
    assert f'Versão 1 da fazenda {cenario.f1.pk} gerada e vigente.' in saida.getvalue()
    assert VersaoPacote.objects.get(fazenda=cenario.f1).vigente


def test_operador_que_nao_e_da_plataforma_e_recusado(pacotes, cenario, fabrica_pessoa, conceder_direto):
    admin = fabrica_pessoa('Administrador de X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    with pytest.raises(CommandError, match='Administrador da plataforma'):
        _chamar(cenario.f1, admin)
    assert not VersaoPacote.objects.exists()


def test_caixa_invalida_vira_erro_de_comando(pacotes, cenario, plataforma):
    with pytest.raises(CommandError, match='caixa'):
        _chamar(cenario.f1, plataforma, caixa='1,2,3')


def test_operador_ou_fazenda_inexistente(pacotes, cenario, plataforma):
    with pytest.raises(CommandError, match='Não encontrei'):
        _chamar(cenario.f1, plataforma, fazenda_id=999999)
    with pytest.raises(CommandError, match='Não encontrei'):
        _chamar(cenario.f1, plataforma, operador_id=999999)


def test_erro_de_ferramenta_vira_erro_de_comando(pacotes, cenario, plataforma, settings):
    settings.PMTILES_BIN = 'pmtiles-que-nao-existe'
    with pytest.raises(CommandError, match='não rodou'):
        _chamar(cenario.f1, plataforma)
