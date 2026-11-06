"""Pacote de referência numa fazenda sintética (004b T2.1a): o que o ambiente de teste de navegador serve."""

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


def test_diretorio_que_ja_existe_nao_e_sobrescrito_e_a_linha_nao_sobra(pacotes, cenario):
    (pacotes / str(cenario.f1.pk) / 'v1').mkdir(parents=True)
    with pytest.raises(FileExistsError):
        instalar_referencia(cenario.f1)
    assert not VersaoPacote.objects.filter(fazenda=cenario.f1).exists()
