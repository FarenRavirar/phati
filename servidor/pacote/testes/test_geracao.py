"""Geração do pacote (004b R2, R5, R20; A2, A5): a função, não o comando. Usa o `pmtiles` e o `rio` reais."""

import json
import threading
from datetime import date

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection

from comum.models import EventoAuditoria
from pacote import geracao, manifesto
from pacote.models import VersaoPacote
from pacote.testes.conftest import CAIXA, REFERENCIA

FUNDO = REFERENCIA / 'fundo.pmtiles'  # o fundo de referência serve de fonte do `extract`


def _gerar(plataforma, fazenda, **extra):
    return geracao.gerar_pacote(plataforma, fazenda, CAIXA, fundo_origem=FUNDO, **extra)


def test_gera_a_versao_1_vigente_com_manifesto_valido_e_auditoria(pacotes, cenario, plataforma):
    versao = _gerar(plataforma, cenario.f1)
    pasta = pacotes / str(cenario.f1.pk) / 'v1'
    lido = manifesto.ler(pasta)  # confere bytes e SHA-256 de cada arquivo
    assert (versao.numero, versao.vigente, versao.empresa_id) == (1, True, cenario.x.pk)
    assert lido.versao == 1 and lido.fazenda_id == cenario.f1.pk
    assert [a.papel for a in lido.arquivos] == ['fundo']
    assert json.loads((pasta / 'manifesto.json').read_text(encoding='utf-8'))['versao'] == 1
    evento = EventoAuditoria.objects.get(acao='pacote_gerado')
    assert (evento.pessoa_id, evento.alvo_id, evento.empresa_id) == (plataforma.pk, cenario.f1.pk, cenario.x.pk)
    assert evento.detalhes['versao'] == 1 and evento.detalhes['origem'] == 'comando' and evento.detalhes['usuario_so']
    assert [p.name for p in (pacotes / str(cenario.f1.pk)).iterdir()] == ['v1']  # nenhum temporário sobra


def test_a_segunda_geracao_cria_a_versao_2_e_a_1_segue_legivel(pacotes, cenario, plataforma):
    _gerar(plataforma, cenario.f1)
    _gerar(plataforma, cenario.f1)
    assert list(VersaoPacote.objects.filter(fazenda=cenario.f1).order_by('numero').values_list('numero', 'vigente')) == [(1, False), (2, True)]
    for numero in (1, 2):
        manifesto.ler(pacotes / str(cenario.f1.pk) / f'v{numero}')
    assert EventoAuditoria.objects.filter(acao='pacote_gerado').count() == 2


def test_ortofoto_respeita_o_teto_de_zoom_e_a_data_vai_ao_manifesto(pacotes, cenario, plataforma, ortofoto_tif):
    _gerar(plataforma, cenario.f1, ortofoto=ortofoto_tif, ortofoto_capturada_em=date(2026, 1, 15), zoom_maximo_ortofoto=15)
    lido = manifesto.ler(pacotes / str(cenario.f1.pk) / 'v1')
    orto = next(a for a in lido.arquivos if a.papel == 'ortofoto')
    assert lido.zoom_maximo_ortofoto == 15 and orto.zoom_maximo <= 15  # A5: nenhum tile acima do teto
    assert orto.capturada_em == date(2026, 1, 15)


def test_falha_no_meio_deixa_a_vigente_intacta_e_sem_temporario(pacotes, cenario, plataforma, monkeypatch):
    _gerar(plataforma, cenario.f1)
    chamadas = []
    original = geracao._cabecalho

    def quebra_na_segunda_versao(arquivo):
        chamadas.append(arquivo)
        raise geracao.ErroDeGeracao('interrompido de propósito')

    monkeypatch.setattr(geracao, '_cabecalho', quebra_na_segunda_versao)
    with pytest.raises(geracao.ErroDeGeracao):
        _gerar(plataforma, cenario.f1)
    monkeypatch.setattr(geracao, '_cabecalho', original)
    assert chamadas  # a falha aconteceu depois do `extract`, com o temporário já cheio
    assert list(VersaoPacote.objects.filter(fazenda=cenario.f1).values_list('numero', 'vigente')) == [(1, True)]
    assert [p.name for p in (pacotes / str(cenario.f1.pk)).iterdir()] == ['v1']  # sem v2 parcial e sem .tmp
    manifesto.ler(pacotes / str(cenario.f1.pk) / 'v1')
    assert EventoAuditoria.objects.filter(acao='pacote_gerado').count() == 1


def test_ferramenta_ausente_vira_erro_de_geracao_sem_sobra(pacotes, cenario, plataforma, settings):
    settings.PMTILES_BIN = 'pmtiles-que-nao-existe'
    with pytest.raises(geracao.ErroDeGeracao):
        _gerar(plataforma, cenario.f1)
    assert list((pacotes / str(cenario.f1.pk)).iterdir()) == []
    assert not VersaoPacote.objects.exists()


@pytest.mark.parametrize('papel', ['curador', 'tecnico', 'usuario'])
def test_so_o_administrador_da_plataforma_gera(pacotes, cenario, fabrica_pessoa, conceder_direto, papel):
    quem = fabrica_pessoa(papel)
    conceder_direto(quem, cenario.cargos_x[papel], cenario.f1)
    with pytest.raises(PermissionDenied):
        _gerar(quem, cenario.f1)
    assert not VersaoPacote.objects.exists()
    assert not pacotes.exists()  # recusado antes de criar qualquer diretório


def test_administrador_da_empresa_tambem_nao_gera(pacotes, cenario, fabrica_pessoa, conceder_direto):
    admin = fabrica_pessoa('Administrador de X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    with pytest.raises(PermissionDenied):
        _gerar(admin, cenario.f1)


@pytest.mark.parametrize('caixa', [
    (1, 2, 3), (-48.2, -10.7, -48.3, -10.6), (-48.3, -10.6, -48.2, -10.7), (-181, 0, 0, 1), (0, -91, 1, 0),
    ('a', 'b', 'c', 'd'), (float('nan'), 0, 1, 1), (float('inf'), 0, 1, 1), None, (-48.3, -10.7, -48.3, -10.6),
])
def test_caixa_invalida_e_recusada_sem_sobra(pacotes, cenario, plataforma, caixa):
    with pytest.raises(ValidationError):
        geracao.gerar_pacote(plataforma, cenario.f1, caixa, fundo_origem=FUNDO)
    assert not pacotes.exists() and not VersaoPacote.objects.exists()


@pytest.mark.parametrize('zoom', [2.5, True, '15', None])
def test_zoom_que_nao_e_inteiro_e_recusado_antes_de_chamar_a_ferramenta(pacotes, cenario, plataforma, zoom):
    # Sourcery, PR #50: os zooms viram argumento de linha de comando; medido, 2.5 e True passavam na checagem de faixa.
    for campo in ('zoom_maximo_fundo', 'zoom_minimo_ortofoto', 'zoom_maximo_ortofoto'):
        with pytest.raises(ValidationError, match='Zoom'):
            _gerar(plataforma, cenario.f1, **{campo: zoom})
    assert not pacotes.exists()


def test_arquivo_com_nome_de_opcao_vira_caminho_absoluto_e_nao_opcao(pacotes, cenario, plataforma, tmp_path, monkeypatch):
    # O nome `--help` relativo vira `<pasta>/--help` pelo `resolve()`: a ferramenta nunca o lê como opção.
    sombra = tmp_path / '--help'
    sombra.write_bytes((REFERENCIA / 'fundo.pmtiles').read_bytes())
    monkeypatch.chdir(tmp_path)
    versao = geracao.gerar_pacote(plataforma, cenario.f1, CAIXA, fundo_origem='--help')
    assert versao.numero == 1


def test_entradas_invalidas_sao_recusadas(pacotes, cenario, plataforma, tmp_path):
    with pytest.raises(ValidationError, match='não existe'):
        geracao.gerar_pacote(plataforma, cenario.f1, CAIXA, fundo_origem=tmp_path / 'nao-existe.pmtiles')
    with pytest.raises(ValidationError, match='não existe'):
        _gerar(plataforma, cenario.f1, ortofoto=tmp_path / 'nao-existe.tif')
    with pytest.raises(ValidationError, match='Zoom'):
        _gerar(plataforma, cenario.f1, zoom_minimo_ortofoto=18, zoom_maximo_ortofoto=14)
    with pytest.raises(ValidationError, match='Zoom'):
        _gerar(plataforma, cenario.f1, zoom_maximo_fundo=25)
    assert not VersaoPacote.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_duas_geracoes_simultaneas_dao_numeros_diferentes_e_uma_vigente(pacotes, catalogo_da_corrida, cenario, plataforma):
    erros = []

    def gerar():
        try:
            _gerar(plataforma, cenario.f1)
        except Exception as erro:  # noqa: BLE001  o teste lista o que falhou
            erros.append(repr(erro))
        finally:
            connection.close()

    fios = [threading.Thread(target=gerar) for _ in range(2)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert erros == []
    assert sorted(VersaoPacote.objects.filter(fazenda=cenario.f1).values_list('numero', flat=True)) == [1, 2]
    assert VersaoPacote.objects.filter(fazenda=cenario.f1, vigente=True).count() == 1
    assert sorted(p.name for p in (pacotes / str(cenario.f1.pk)).iterdir()) == ['v1', 'v2']
