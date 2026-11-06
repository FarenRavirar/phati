"""Pacote de referência numa fazenda sintética (004b T2.1a): o que o ambiente de teste de navegador serve."""

import shutil
from pathlib import Path

import pytest

from pacote import manifesto
from pacote.models import VersaoPacote
from pacote.sintetico import instalar_referencia


def test_instala_a_versao_1_vigente_com_arquivos_que_batem_com_o_manifesto(pacotes, cenario):
    versao = instalar_referencia(cenario.f1)
    assert (versao.numero, versao.vigente, versao.empresa_id, versao.fazenda_id) == (1, True, cenario.x.pk, cenario.f1.pk)
    lido = manifesto.ler(pacotes / str(cenario.f1.pk) / 'v1')  # confere bytes e SHA-256 de cada arquivo
    assert lido.fazenda_id == cenario.f1.pk
    assert [a.papel for a in lido.arquivos] == ['fundo', 'ortofoto']


def test_fazenda_que_ja_tem_pacote_e_recusada_e_nada_muda(pacotes, cenario):
    instalar_referencia(cenario.f1)
    with pytest.raises(ValueError, match='fazenda_ja_tem_pacote'):
        instalar_referencia(cenario.f1)
    assert VersaoPacote.objects.filter(fazenda=cenario.f1).count() == 1


def test_falha_na_copia_desfaz_a_linha_do_banco(pacotes, cenario, monkeypatch):
    def quebrar(*_a, **_k):
        raise OSError('disco cheio')

    monkeypatch.setattr('pacote.sintetico.shutil.copytree', quebrar)
    with pytest.raises(OSError):
        instalar_referencia(cenario.f1)
    assert not VersaoPacote.objects.filter(fazenda=cenario.f1).exists()


def test_diretorio_que_ja_existe_nao_e_sobrescrito_nem_apagado_e_a_linha_nao_sobra(pacotes, cenario):
    destino = pacotes / str(cenario.f1.pk) / 'v1'
    destino.mkdir(parents=True)
    (destino / 'alheio.txt').write_text('meu', encoding='utf-8')
    with pytest.raises(FileExistsError):
        instalar_referencia(cenario.f1)
    assert (destino / 'alheio.txt').read_text(encoding='utf-8') == 'meu'
    assert not VersaoPacote.objects.filter(fazenda=cenario.f1).exists()


def test_copia_parcial_que_falha_apaga_o_que_criou_e_a_nova_tentativa_funciona(pacotes, cenario, monkeypatch):
    original = shutil.copytree

    def copiar_e_quebrar(origem, destino, *args, **kwargs):
        original(origem, destino, *args, **kwargs)  # o diretório já existe, com arquivos, quando o erro vem
        raise OSError('disco cheio')

    monkeypatch.setattr('pacote.sintetico.shutil.copytree', copiar_e_quebrar)
    with pytest.raises(OSError):
        instalar_referencia(cenario.f1)
    assert not (pacotes / str(cenario.f1.pk) / 'v1').exists()
    assert not VersaoPacote.objects.filter(fazenda=cenario.f1).exists()
    monkeypatch.undo()
    assert instalar_referencia(cenario.f1).numero == 1


def test_falha_ao_gravar_o_manifesto_apaga_o_diretorio_e_a_nova_tentativa_funciona(pacotes, cenario, monkeypatch):
    original = Path.write_text

    def quebrar(self, *args, **kwargs):
        if self.name == 'manifesto.json':
            raise OSError('disco cheio')
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'write_text', quebrar)
    with pytest.raises(OSError):
        instalar_referencia(cenario.f1)
    assert not (pacotes / str(cenario.f1.pk) / 'v1').exists()
    monkeypatch.undo()
    assert instalar_referencia(cenario.f1).numero == 1
