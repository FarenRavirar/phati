"""Manifesto do pacote (004b R1, R6): o contrato entre o servidor e o aplicativo.

Dado externo (JSON do banco, do disco ou do aplicativo) é `unknown` até passar por aqui. `extra='forbid'` recusa campo
desconhecido: documento nunca entra no pacote (RF-09, A1), e um aplicativo antigo não lê campo que não conhece por engano."""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

FORMATO_VERSAO = 1
NOME_DO_MANIFESTO = 'manifesto.json'
ESQUEMA_JSON = Path(__file__).with_name('esquema_manifesto.json')
PADRAO_DO_NOME = r'^[a-z0-9][a-z0-9_-]*\.pmtiles$'  # nunca barra nem `..`: o nome é só um arquivo do diretório da versão


class ManifestoInvalido(ValueError):
    """Manifesto fora do esquema, ou arquivo que não bate com ele."""


class _Estrito(BaseModel):
    """Base dos modelos do manifesto: recusa campo desconhecido e é imutável."""
    model_config = ConfigDict(extra='forbid', frozen=True)


class Arquivo(_Estrito):
    """Um arquivo PMTiles do pacote (fundo ou ortofoto)."""
    nome: str = Field(pattern=PADRAO_DO_NOME)  # no esquema exportado também: o cliente valida sem repetir a regra
    papel: Literal['fundo', 'ortofoto']
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    zoom_minimo: int = Field(ge=0, le=24)
    zoom_maximo: int = Field(ge=0, le=24)
    atribuicao: str = Field(min_length=1)
    licenca: str = Field(min_length=1)
    capturada_em: date | None = None  # data de captura da ortofoto (R8); ausente no fundo

    @model_validator(mode='after')
    def _zooms_e_data(self):
        """Zoom mínimo não passa do máximo; só a ortofoto tem data de captura."""
        if self.zoom_minimo > self.zoom_maximo:
            raise ValueError('zoom_minimo maior que zoom_maximo')
        if self.papel == 'fundo' and self.capturada_em is not None:
            raise ValueError('só a ortofoto tem data de captura')
        return self


class CamadaVetorial(_Estrito):
    """Camada vetorial do pacote: identificador, revisão vigente e data."""
    identificador: str = Field(min_length=1)
    revisao_vigente: int = Field(ge=1)
    data: date


class Manifesto(_Estrito):
    """Manifesto de uma versão do pacote (R1): o que o servidor entrega e o aplicativo confere."""
    formato_versao: Literal[1]
    fazenda_id: int = Field(ge=1)
    versao: int = Field(ge=1)
    gerado_em: datetime
    zoom_maximo_ortofoto: int = Field(ge=0, le=24)  # o teto pedido na geração (R5): nenhum tile da ortofoto passa dele
    arquivos: list[Arquivo] = Field(min_length=1)
    camadas: list[CamadaVetorial]

    @model_validator(mode='after')
    def _coerencia(self):
        """Nomes e papéis únicos, `gerado_em` com fuso e ortofoto dentro do teto de zoom."""
        nomes = [a.nome for a in self.arquivos]
        if len(set(nomes)) != len(nomes):
            raise ValueError('nome de arquivo repetido')
        papeis = [a.papel for a in self.arquivos]
        if len(set(papeis)) != len(papeis):
            raise ValueError('papel de arquivo repetido')  # a web e o aplicativo escolhem o arquivo pelo papel
        if self.gerado_em.tzinfo is None:
            raise ValueError('gerado_em sem fuso')
        for arquivo in self.arquivos:
            if arquivo.papel == 'ortofoto' and arquivo.zoom_maximo > self.zoom_maximo_ortofoto:
                raise ValueError('ortofoto passa do teto de zoom')
        return self


def validar(dado) -> Manifesto:
    """Dado externo (dict) → `Manifesto`, ou `ManifestoInvalido` com o motivo."""
    try:
        return Manifesto.model_validate(dado)
    except ValidationError as erro:
        raise ManifestoInvalido(str(erro)) from erro


def sha256_do_arquivo(caminho: Path) -> str:
    """SHA-256 do arquivo, lido em blocos de 1 MiB."""
    resumo = hashlib.sha256()
    with caminho.open('rb') as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b''):
            resumo.update(bloco)
    return resumo.hexdigest()


def ler(diretorio: Path) -> Manifesto:
    """Lê `manifesto.json` do diretório da versão e confere cada arquivo (existência, bytes e SHA-256)."""
    try:
        bruto = json.loads((diretorio / NOME_DO_MANIFESTO).read_text(encoding='utf-8'))
    except (OSError, ValueError) as erro:
        raise ManifestoInvalido(f'manifesto ilegível: {erro}') from erro
    manifesto = validar(bruto)
    for arquivo in manifesto.arquivos:
        caminho = diretorio / arquivo.nome
        if not caminho.is_file():
            raise ManifestoInvalido(f'arquivo ausente: {arquivo.nome}')
        if caminho.stat().st_size != arquivo.bytes or sha256_do_arquivo(caminho) != arquivo.sha256:
            raise ManifestoInvalido(f'arquivo não bate com o manifesto: {arquivo.nome}')
    return manifesto


def esquema() -> dict:
    """JSON Schema do manifesto, gerado do modelo."""
    return Manifesto.model_json_schema()


def esquema_exportado() -> str:
    """Texto de `esquema_manifesto.json`; um teste confere que o arquivo versionado é este (drift)."""
    return json.dumps(esquema(), ensure_ascii=False, indent=2, sort_keys=True) + '\n'
