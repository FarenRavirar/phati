"""Arquivo original de um envio (008 R15, D114 c): disco privado `CAMADAS_DIR`, nome interno gerado, sha256, sem rota.

O nome interno sai de `secrets.token_hex`, nunca do nome enviado. O caminho só é montado a partir de um nome que casa
o padrão e fica dentro de `CAMADAS_DIR` depois de resolvido (um link simbólico para fora é recusado)."""

import hashlib
import os
import re
import secrets
import tempfile
from pathlib import Path

from django.conf import settings

PADRAO_NOME = re.compile(r'[0-9a-f]{32}\.bin')


class OriginalInvalido(Exception):
    pass


def caminho_interno(nome):
    """Caminho de um original dentro de CAMADAS_DIR. Qualquer nome fora do padrão ou que saia da pasta é recusado."""
    if not isinstance(nome, str) or not PADRAO_NOME.fullmatch(nome):
        raise OriginalInvalido('nome interno inválido')
    base = Path(settings.CAMADAS_DIR).resolve()
    alvo = (base / nome).resolve()
    if alvo.parent != base:
        raise OriginalInvalido('caminho fora de CAMADAS_DIR')
    return alvo


def gravar(dados):
    """Grava `dados` de forma atômica (temporário na mesma pasta, fsync, rename) e confere o hash depois de gravar.

    Devolve (nome interno, sha256). Falha no meio não deixa arquivo final nem temporário."""
    digest = hashlib.sha256(dados).hexdigest()
    base = Path(settings.CAMADAS_DIR)
    base.mkdir(parents=True, exist_ok=True)
    nome = secrets.token_hex(16) + '.bin'
    destino = caminho_interno(nome)
    descritor, temporario = tempfile.mkstemp(dir=base, prefix='.parcial-', suffix='.tmp')
    try:
        with os.fdopen(descritor, 'wb') as saida:
            saida.write(dados)
            saida.flush()
            os.fsync(saida.fileno())
        os.chmod(temporario, 0o600)
        os.replace(temporario, destino)
    except BaseException:
        Path(temporario).unlink(missing_ok=True)
        raise
    if hashlib.sha256(destino.read_bytes()).hexdigest() != digest:
        destino.unlink(missing_ok=True)
        raise OriginalInvalido('hash diferente depois de gravar')
    return nome, digest


def ler(nome, hash_esperado):
    """Lê o original e recusa se o sha256 não confere com o guardado no envio."""
    dados = caminho_interno(nome).read_bytes()
    if hashlib.sha256(dados).hexdigest() != hash_esperado:
        raise OriginalInvalido('hash não confere')
    return dados


def remover(nome):
    """Apaga o original. Arquivo ausente não é erro (a limpeza é idempotente)."""
    caminho_interno(nome).unlink(missing_ok=True)
