"""Manifesto do pacote (004b R1, R6): o contrato entre o servidor e o aplicativo.

Dado externo (JSON do banco, do disco ou do aplicativo) é `unknown` até passar por aqui. `extra='forbid'` recusa campo
desconhecido: documento nunca entra no pacote (RF-09, A1), e um aplicativo antigo não lê campo que não conhece por engano."""

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

FORMATO_VERSAO = 1
NOME_DO_MANIFESTO = 'manifesto.json'
ESQUEMA_JSON = Path(__file__).with_name('esquema_manifesto.json')
_NOME = re.compile(r'^[a-z0-9][a-z0-9_-]*\.pmtiles$')  # nunca barra nem `..`: o nome é só um arquivo do diretório da versão


class ManifestoInvalido(ValueError):
    """Manifesto fora do esquema, ou arquivo que não bate com ele."""


def _nome_simples(nome: str) -> str:
    if not _NOME.match(nome):
        raise ValueError('nome de arquivo inválido')
    return nome


class _Estrito(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Arquivo(_Estrito):
    nome: Annotated[str, AfterValidator(_nome_simples)]
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
        if self.zoom_minimo > self.zoom_maximo:
            raise ValueError('zoom_minimo maior que zoom_maximo')
        if self.papel == 'fundo' and self.capturada_em is not None:
            raise ValueError('só a ortofoto tem data de captura')
        return self


class CamadaVetorial(_Estrito):
    identificador: str = Field(min_length=1)
    revisao_vigente: int = Field(ge=1)
    data: date


class Manifesto(_Estrito):
    formato_versao: Literal[1]
    fazenda_id: int = Field(ge=1)
    versao: int = Field(ge=1)
    gerado_em: datetime
    zoom_maximo_ortofoto: int = Field(ge=0, le=24)  # o teto pedido na geração (R5): nenhum tile da ortofoto passa dele
    arquivos: list[Arquivo] = Field(min_length=1)
    camadas: list[CamadaVetorial]

    @model_validator(mode='after')
    def _coerencia(self):
        nomes = [a.nome for a in self.arquivos]
        if len(set(nomes)) != len(nomes):
            raise ValueError('nome de arquivo repetido')
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
    return Manifesto.model_json_schema()


def esquema_exportado() -> str:
    """Texto de `esquema_manifesto.json`; um teste confere que o arquivo versionado é este (drift)."""
    return json.dumps(esquema(), ensure_ascii=False, indent=2, sort_keys=True) + '\n'
