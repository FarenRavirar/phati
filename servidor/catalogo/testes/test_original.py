"""Arquivo original do envio (008 T2.4; R15): hash conferido, nome interno, sem rota pública, atômico, confinado."""

import hashlib
import os
import re
from pathlib import Path

import pytest

from catalogo import original
from catalogo.original import OriginalInvalido

ARQUIVO = b'conteudo sintetico do envio'


@pytest.fixture
def camadas(settings, tmp_path):
    settings.CAMADAS_DIR = tmp_path / 'camadas'
    settings.CAMADAS_DIR.mkdir()
    return settings.CAMADAS_DIR


def test_gravar_devolve_hash_sha256_do_conteudo(camadas):
    nome, digest = original.gravar(ARQUIVO)
    assert digest == hashlib.sha256(ARQUIVO).hexdigest()
    assert original.ler(nome, digest) == ARQUIVO


def test_hash_errado_e_recusado_na_leitura(camadas):
    nome, _ = original.gravar(ARQUIVO)
    with pytest.raises(OriginalInvalido, match='hash não confere'):
        original.ler(nome, 'f' * 64)


def test_arquivo_alterado_no_disco_e_recusado_na_leitura(camadas):
    nome, digest = original.gravar(ARQUIVO)
    (camadas / nome).write_bytes(b'alterado depois de gravar')
    with pytest.raises(OriginalInvalido, match='hash não confere'):
        original.ler(nome, digest)


def test_nome_interno_e_gerado_e_nao_e_o_nome_enviado(camadas):
    nome, _ = original.gravar(ARQUIVO)
    assert re.fullmatch(r'[0-9a-f]{32}\.bin', nome)
    assert 'camada' not in nome  # o nome enviado nunca chega aqui
    assert 'envio' not in nome


def test_nomes_gerados_nao_se_repetem(camadas):
    nomes = {original.gravar(ARQUIVO)[0] for _ in range(20)}
    assert len(nomes) == 20


def test_gravacao_que_falha_no_meio_nao_deixa_arquivo_nem_temporario(camadas, monkeypatch):
    def falha(descritor):
        raise OSError('disco cheio (simulado)')

    monkeypatch.setattr(os, 'fsync', falha)
    with pytest.raises(OSError):
        original.gravar(ARQUIVO)
    assert list(camadas.iterdir()) == []


def test_falha_na_conferencia_depois_do_rename_remove_o_destino(camadas, monkeypatch):
    # Achado 9: a releitura depois do os.replace ficava fora do tratamento e deixava o destino instalado.
    def falha(self):
        raise OSError('leitura de conferência falhou (simulado)')

    monkeypatch.setattr(Path, 'read_bytes', falha)
    with pytest.raises(OSError):
        original.gravar(ARQUIVO)
    assert list(camadas.iterdir()) == []


def test_original_nao_tem_rota_publica(camadas, client, db):
    nome, _ = original.gravar(ARQUIVO)
    for caminho in (f'/{nome}', f'/camadas/{nome}', f'/media/{nome}', f'/static/{nome}', f'/_fazenda/{nome}'):
        assert client.get(caminho).status_code == 404, caminho


@pytest.mark.parametrize('nome', ['../fora.bin', '/etc/passwd', 'C:/fora.bin', '..\\fora.bin', 'a' * 32 + '.bin/../x', '', None, 'camada.kml'])
def test_nome_hostil_nao_escapa_de_camadas_dir(camadas, nome):
    with pytest.raises(OriginalInvalido):
        original.caminho_interno(nome)


def test_link_simbolico_para_fora_de_camadas_dir_e_recusado(camadas, tmp_path):
    fora = tmp_path / 'fora'
    fora.mkdir()
    nome = 'a' * 32 + '.bin'
    (camadas / nome).symlink_to(fora / 'alvo.bin')  # o teste roda no contêiner Linux, onde o link existe
    with pytest.raises(OriginalInvalido, match='fora de CAMADAS_DIR'):
        original.caminho_interno(nome)


def test_remover_arquivo_ausente_nao_e_erro(camadas):
    original.remover('a' * 32 + '.bin')  # não existe: idempotente
    nome, _ = original.gravar(ARQUIVO)
    original.remover(nome)
    original.remover(nome)
    assert not (camadas / nome).exists()
