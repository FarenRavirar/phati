"""Comando `limpar_envios_camada` (008 T2.4): apaga só o vencido e o original dele, dentro de CAMADAS_DIR; idempotente."""

from datetime import timedelta
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from catalogo import envios, original, publicacao
from catalogo.models import EnvioCamada
from catalogo.testes.test_ingestao import geojson, ponto_geojson
from identidade.models import Pessoa
from territorio.models import Empresa, Fazenda

pytestmark = pytest.mark.django_db


@pytest.fixture
def camadas(settings, tmp_path):
    settings.CAMADAS_DIR = tmp_path / 'camadas'
    settings.CAMADAS_DIR.mkdir()
    return settings.CAMADAS_DIR


@pytest.fixture
def mundo(cpf_novo):
    m = SimpleNamespace()
    m.x = Empresa.objects.create(nome='Empresa X')
    m.f1 = Fazenda.objects.create(empresa=m.x, nome='F1')
    m.operador = Pessoa.objects.criar('Operadora Sintética', 'op@exemplo.test', cpf_novo(), empresa_origem=m.x)
    m.operador.administrador_plataforma = True
    m.operador.save(update_fields=['administrador_plataforma'])
    return m


def _envio(mundo, agora=None):
    return envios.criar_envio(mundo.operador, mundo.f1, geojson([ponto_geojson()]), agora=agora)


def test_expirado_some_com_o_original_e_o_nao_expirado_fica(camadas, mundo):
    vencido = _envio(mundo, agora=timezone.now() - timedelta(hours=48))
    vigente = _envio(mundo)
    call_command('limpar_envios_camada', operador=mundo.operador.pk, stdout=StringIO())
    assert not EnvioCamada.objects.filter(pk=vencido.pk).exists()
    assert EnvioCamada.objects.filter(pk=vigente.pk).exists()
    assert not (camadas / vencido.arquivo_temporario).exists()
    assert (camadas / vigente.arquivo_temporario).exists()


def test_arquivo_faltando_nao_derruba_a_limpeza(camadas, mundo):
    vencido = _envio(mundo, agora=timezone.now() - timedelta(hours=48))
    (camadas / vencido.arquivo_temporario).unlink()
    removidos, ignorados = envios.limpar_expirados(mundo.operador)
    assert (removidos, ignorados) == (1, 0)
    assert not EnvioCamada.objects.filter(pk=vencido.pk).exists()


def test_nome_interno_invalido_nao_apaga_nada_fora_de_camadas_dir(camadas, mundo, tmp_path):
    fora = tmp_path / 'fora.bin'
    fora.write_bytes(b'arquivo de fora')
    EnvioCamada.objects.create(
        criado_por=mundo.operador, empresa=mundo.x, fazenda=mundo.f1, arquivo_temporario='../fora.bin',
        hash_original='a' * 64, expira_em=timezone.now() - timedelta(hours=1),
    )
    removidos, ignorados = envios.limpar_expirados(mundo.operador)
    assert (removidos, ignorados) == (0, 1)
    assert fora.read_bytes() == b'arquivo de fora'  # nada fora de CAMADAS_DIR foi tocado
    assert EnvioCamada.objects.count() == 1  # a linha suspeita fica para inspeção


def test_segunda_execucao_nao_remove_nada(camadas, mundo):
    _envio(mundo, agora=timezone.now() - timedelta(hours=48))
    assert envios.limpar_expirados(mundo.operador) == (1, 0)
    assert envios.limpar_expirados(mundo.operador) == (0, 0)


def test_envio_removido_pela_limpeza_nao_pode_mais_ser_publicado(camadas, mundo):
    vencido = _envio(mundo, agora=timezone.now() - timedelta(hours=48))
    arquivo = camadas / vencido.arquivo_temporario
    assert envios.limpar_expirados(mundo.operador) == (1, 0)
    assert not arquivo.exists()
    with pytest.raises(publicacao.EnvioNaoEncontrado):
        publicacao.publicar_envio(mundo.operador, vencido.pk, estudo_id=0, metadados={}, nos=[])


def test_saida_do_comando_conta_removidos(camadas, mundo):
    _envio(mundo, agora=timezone.now() - timedelta(hours=48))
    saida = StringIO()
    call_command('limpar_envios_camada', operador=mundo.operador.pk, stdout=saida)
    assert '1 envio(s) expirado(s) removido(s)' in saida.getvalue()


def test_operador_inexistente_e_recusado(camadas):
    with pytest.raises(CommandError, match='operador não encontrado'):
        call_command('limpar_envios_camada', operador=999999, stdout=StringIO())


def test_falha_ao_apagar_o_original_desfaz_a_linha_e_a_proxima_limpeza_tenta_de_novo(camadas, mundo, monkeypatch):
    # Regressão (achado Greptile, P2): linha apagada antes de um original que não sai deixava arquivo órfão.
    vencido = _envio(mundo, agora=timezone.now() - timedelta(hours=48))
    remover_de_verdade = original.remover

    def remover_sem_permissao(nome):
        raise PermissionError('sem permissão para apagar')

    monkeypatch.setattr(original, 'remover', remover_sem_permissao)
    with pytest.raises(PermissionError):
        envios.limpar_expirados(mundo.operador)
    assert EnvioCamada.objects.filter(pk=vencido.pk).exists()  # a linha volta: a próxima execução tenta de novo
    monkeypatch.setattr(original, 'remover', remover_de_verdade)
    assert envios.limpar_expirados(mundo.operador) == (1, 0)
    assert not (camadas / vencido.arquivo_temporario).exists()
    assert not EnvioCamada.objects.filter(pk=vencido.pk).exists()
