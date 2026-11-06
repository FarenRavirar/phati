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
def ortofoto_grande_tif(tmp_path):
    """GeoTIFF RGB que cobre 3x a `CAIXA` em cada lado: a geração tem de recortá-lo (dado sintético)."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    oeste, sul, leste, norte = CAIXA
    largura, altura = leste - oeste, norte - sul
    limites = (oeste - largura, sul - altura, leste + largura, norte + altura)
    tamanho = 512
    x, y = np.meshgrid(np.linspace(0, 1, tamanho), np.linspace(0, 1, tamanho))
    imagem = np.stack([(60 + 120 * x).astype('uint8'), (90 + 100 * y).astype('uint8'), np.full((tamanho, tamanho), 70, 'uint8')])
    caminho = tmp_path / 'ortofoto-grande.tif'
    with rasterio.open(
        caminho, 'w', driver='GTiff', height=tamanho, width=tamanho, count=3, dtype='uint8', crs='EPSG:4326',
        transform=from_bounds(*limites, tamanho, tamanho), compress='deflate',
    ) as destino:
        destino.write(imagem)
    return caminho


@pytest.fixture
def referencia_instalada(pacotes, cenario):
    """Instala o pacote de referência como versão 1 vigente da fazenda F1 de X, sem rodar as ferramentas externas."""
    from pacote.sintetico import instalar_referencia

    return instalar_referencia(cenario.f1)


SENHA = 'cavalo azul sobe o morro'


@pytest.fixture
def entrar(db, cpf_novo):
    """`entrar(cargo, escopo)` cria uma pessoa sintética com o cargo no escopo e devolve o cliente já logado."""
    from django.test import Client

    from identidade.models import Pessoa
    from permissao.models import Concessao
    from territorio.models import Fazenda, SubArea

    def abrir(cargo=None, escopo=None, administrador_plataforma=False):
        cpf = cpf_novo()
        pessoa = Pessoa.objects.criar(nome='Pessoa Sintetica', email='pessoa@exemplo.test', cpf=cpf)
        pessoa.set_password(SENHA)
        pessoa.administrador_plataforma = administrador_plataforma
        pessoa.save()
        if cargo is not None:
            if isinstance(escopo, SubArea):
                lugar = {'empresa': escopo.empresa, 'fazenda': escopo.fazenda, 'sub_area': escopo}
            elif isinstance(escopo, Fazenda):
                lugar = {'empresa': escopo.empresa, 'fazenda': escopo}
            else:
                lugar = {'empresa': escopo}
            Concessao.objects.create(pessoa=pessoa, cargo=cargo, concedida_por=pessoa, **lugar)
        cliente = Client()
        assert cliente.post('/entrar', {'cpf': cpf, 'senha': SENHA}).status_code == 302
        setattr(cliente, 'pessoa', pessoa)  # os testes de função (sem HTTP) usam a mesma pessoa
        return cliente

    return abrir


@pytest.fixture
def cargo_so_ver(cenario):
    """Cargo personalizado de X com `ver` e sem `baixar_pacote_offline`."""
    from permissao.models import Cargo, CargoPermissao

    cargo = Cargo.objects.create(empresa=cenario.x, nome='So ver', base='usuario')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='ver')
    return cargo
