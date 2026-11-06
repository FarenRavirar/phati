"""Manifesto (004b R1, A1): aceita o de referência e recusa cada defeito, um por caso."""

import copy
import json
import shutil

import pytest

from pacote import manifesto
from pacote.testes.conftest import REFERENCIA


@pytest.fixture
def bruto():
    return json.loads((REFERENCIA / 'manifesto.json').read_text(encoding='utf-8'))


def test_o_manifesto_de_referencia_e_aceito_com_os_arquivos_conferidos():
    lido = manifesto.ler(REFERENCIA)
    assert lido.formato_versao == 1
    assert {a.papel for a in lido.arquivos} == {'fundo', 'ortofoto'}


def test_o_manifesto_nao_lista_documento(bruto):
    # RF-09: documento só online. O esquema recusa campo desconhecido, então `documentos` não entra nem por engano.
    assert 'documentos' not in bruto
    bruto['documentos'] = [{'nome': 'laudo.pdf'}]
    with pytest.raises(manifesto.ManifestoInvalido):
        manifesto.validar(bruto)


@pytest.mark.parametrize('campo', ['formato_versao', 'fazenda_id', 'versao', 'gerado_em', 'zoom_maximo_ortofoto', 'arquivos', 'camadas'])
def test_recusa_manifesto_sem_campo_obrigatorio(bruto, campo):
    del bruto[campo]
    with pytest.raises(manifesto.ManifestoInvalido):
        manifesto.validar(bruto)


def test_recusa_formato_versao_desconhecida(bruto):
    bruto['formato_versao'] = 2
    with pytest.raises(manifesto.ManifestoInvalido):
        manifesto.validar(bruto)


def test_recusa_sha256_que_nao_bate_com_o_arquivo(tmp_path):
    shutil.copytree(REFERENCIA, tmp_path / 'v1')
    with (tmp_path / 'v1' / 'fundo.pmtiles').open('r+b') as arquivo:
        arquivo.seek(-1, 2)
        ultimo = arquivo.read(1)
        arquivo.seek(-1, 2)
        arquivo.write(bytes([ultimo[0] ^ 1]))  # mesmo tamanho, um bit diferente
    with pytest.raises(manifesto.ManifestoInvalido, match='não bate'):
        manifesto.ler(tmp_path / 'v1')


def test_recusa_arquivo_ausente_e_manifesto_ilegivel(tmp_path):
    shutil.copytree(REFERENCIA, tmp_path / 'v1')
    (tmp_path / 'v1' / 'ortofoto.pmtiles').unlink()
    with pytest.raises(manifesto.ManifestoInvalido, match='ausente'):
        manifesto.ler(tmp_path / 'v1')
    (tmp_path / 'v1' / 'manifesto.json').write_text('{ não é json', encoding='utf-8')
    with pytest.raises(manifesto.ManifestoInvalido, match='ilegível'):
        manifesto.ler(tmp_path / 'v1')


@pytest.mark.parametrize('nome', ['../fundo.pmtiles', 'a/b.pmtiles', 'FUNDO.pmtiles', 'fundo.txt', '.oculto.pmtiles', ''])
def test_recusa_nome_de_arquivo_que_nao_e_um_arquivo_simples(bruto, nome):
    bruto['arquivos'][0]['nome'] = nome
    with pytest.raises(manifesto.ManifestoInvalido):
        manifesto.validar(bruto)


def test_recusa_incoerencias(bruto):
    casos = {
        'nome repetido': lambda m: m['arquivos'][1].update(nome=m['arquivos'][0]['nome']),
        'papel repetido': lambda m: m['arquivos'][1].update(papel='fundo', capturada_em=None),
        'ortofoto acima do teto': lambda m: m.update(zoom_maximo_ortofoto=m['arquivos'][1]['zoom_maximo'] - 1),
        'zoom invertido': lambda m: m['arquivos'][0].update(zoom_minimo=9, zoom_maximo=3),
        'data de captura no fundo': lambda m: m['arquivos'][0].update(capturada_em='2026-01-01'),
        'sem fuso': lambda m: m.update(gerado_em='2026-01-01T00:00:00'),
        'sha256 curto': lambda m: m['arquivos'][0].update(sha256='abc'),
        'sem arquivos': lambda m: m.update(arquivos=[]),
    }
    for descricao, estragar in casos.items():
        alterado = copy.deepcopy(bruto)
        estragar(alterado)
        with pytest.raises(manifesto.ManifestoInvalido):
            manifesto.validar(alterado)
        assert descricao  # o nome do caso aparece no relatório do pytest quando falha


def test_esquema_exportado_para_o_aplicativo_nao_saiu_do_modelo():
    # Drift: o arquivo versionado é o que o aplicativo lê; mudou o modelo, regenere (`manifesto.esquema_exportado()`).
    assert manifesto.ESQUEMA_JSON.read_text(encoding='utf-8') == manifesto.esquema_exportado()


def test_o_esquema_exportado_carrega_a_regra_do_nome_e_recusa_o_que_o_servidor_recusa():
    # Greptile, PR #50: o cliente que só lê o JSON Schema precisa da mesma regra que o servidor aplica.
    import re

    padrao = json.loads(manifesto.ESQUEMA_JSON.read_text(encoding='utf-8'))['$defs']['Arquivo']['properties']['nome']['pattern']
    assert re.match(padrao, 'fundo.pmtiles')
    for nome in ('../fora.pmtiles', 'a/b.pmtiles', 'FUNDO.pmtiles', 'fundo.txt'):
        assert not re.match(padrao, nome), nome
