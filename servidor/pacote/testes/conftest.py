import json
import shutil
from pathlib import Path

import pytest

REFERENCIA = Path(__file__).resolve().parents[1] / 'referencia'
CAIXA = (-48.3015, -10.7515, -48.2985, -10.7485)  # dentro do centro de teste da 004 (LON0, LAT0), menos de 0,1 grau


@pytest.fixture
def pacotes(settings, tmp_path):
    """Diretório de pacotes descartável (`PACOTES_DIR`)."""
    settings.PACOTES_DIR = tmp_path / 'pacotes'
    return settings.PACOTES_DIR


@pytest.fixture
def ortofoto_tif(tmp_path):
    """GeoTIFF RGB minúsculo sobre `CAIXA`, gerado na hora (dado sintético; `rasterio` vem com `rio-pmtiles`)."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    tamanho = 256
    x, y = np.meshgrid(np.linspace(0, 1, tamanho), np.linspace(0, 1, tamanho))
    imagem = np.stack([(60 + 120 * x).astype('uint8'), (90 + 100 * y).astype('uint8'), np.full((tamanho, tamanho), 70, 'uint8')])
    caminho = tmp_path / 'ortofoto.tif'
    with rasterio.open(
        caminho, 'w', driver='GTiff', height=tamanho, width=tamanho, count=3, dtype='uint8', crs='EPSG:4326',
        transform=from_bounds(*CAIXA, tamanho, tamanho), compress='deflate',
    ) as destino:
        destino.write(imagem)
    return caminho


@pytest.fixture
def referencia_instalada(pacotes, cenario):
    """Instala o pacote de referência como versão 1 vigente da fazenda F1 de X, sem rodar as ferramentas externas."""
    from pacote.models import VersaoPacote

    destino = pacotes / str(cenario.f1.pk) / 'v1'
    shutil.copytree(REFERENCIA, destino)
    manifesto = json.loads((REFERENCIA / 'manifesto.json').read_text(encoding='utf-8'))
    return VersaoPacote.objects.create(empresa=cenario.x, fazenda=cenario.f1, numero=1, manifesto=manifesto, vigente=True)


SENHA = 'cavalo azul sobe o morro'


@pytest.fixture
def entrar(db, cpf_novo):
    """`entrar(cargo, escopo)` cria uma pessoa sintética com o cargo no escopo e devolve o cliente já logado."""
    from django.test import Client

    from identidade.models import Pessoa
    from permissao.models import Concessao
    from territorio.models import Fazenda

    def abrir(cargo=None, escopo=None, administrador_plataforma=False):
        cpf = cpf_novo()
        pessoa = Pessoa.objects.criar(nome='Pessoa Sintetica', email='pessoa@exemplo.test', cpf=cpf)
        pessoa.set_password(SENHA)
        pessoa.administrador_plataforma = administrador_plataforma
        pessoa.save()
        if cargo is not None:
            lugar = {'empresa': escopo.empresa, 'fazenda': escopo} if isinstance(escopo, Fazenda) else {'empresa': escopo}
            Concessao.objects.create(pessoa=pessoa, cargo=cargo, concedida_por=pessoa, **lugar)
        cliente = Client()
        assert cliente.post('/entrar', {'cpf': cpf, 'senha': SENHA}).status_code == 302
        return cliente

    return abrir


@pytest.fixture
def cargo_so_ver(cenario):
    """Cargo personalizado de X com `ver` e sem `baixar_pacote_offline`."""
    from permissao.models import Cargo, CargoPermissao

    cargo = Cargo.objects.create(empresa=cenario.x, nome='So ver', base='usuario')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='ver')
    return cargo
