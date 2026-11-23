"""Imagem do PgBouncer (spec 009 R18): base fixada por digest, pacote com versão exata, usuário não root, entrypoint.

Asserções estáticas sobre o texto do Dockerfile, no molde de `test_imagem_banco.py`. Cada checagem é uma função que
recebe o texto: os testes positivos passam o Dockerfile real; os negativos passam o mesmo texto com uma mutação.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings

RAIZ = Path(settings.DIRETORIO_BASE)
DOCKERFILE = (RAIZ / 'pgbouncer' / 'Dockerfile').read_text(encoding='utf-8')


def _instrucoes(texto):
    """Instruções lógicas do Dockerfile: sem comentário, com linhas de continuação (`\\`) unidas."""
    logicas, atual = [], ''
    for linha in texto.splitlines():
        if linha.lstrip().startswith('#') or not linha.strip():
            continue
        atual += ' ' + linha.strip()
        if atual.endswith('\\'):
            atual = atual[:-1].rstrip()
            continue
        logicas.append(atual.strip())
        atual = ''
    return logicas


def _verifica_base(texto):
    assert re.search(r'^FROM postgres:18@sha256:[0-9a-f]{64}$', texto, re.M), 'base sem postgres:18 fixado por digest'


def _verifica_pacote(texto):
    instalacao = [i for i in _instrucoes(texto) if 'apt-get install' in i]
    assert len(instalacao) == 1, 'esperava exatamente um apt-get install'
    assert 'pgbouncer=1.26.1-1.pgdg13+1' in instalacao[0], 'pgbouncer sem versão exata fixada'
    assert not re.search(r'\bpgbouncer\b(?!=)', instalacao[0]), 'pgbouncer instalado sem versão'


def _verifica_usuario_nao_root(texto):
    logicas = _instrucoes(texto)
    usuarios = [i.split(None, 1)[1] for i in logicas if i.startswith('USER ')]
    assert usuarios, 'sem instrução USER'
    assert usuarios[-1] not in ('root', '0'), 'imagem termina como root'
    assert logicas[-1].startswith('ENTRYPOINT'), 'USER precisa estar antes do ENTRYPOINT no fim'


def _verifica_entrypoint(texto):
    logicas = _instrucoes(texto)
    assert 'ENTRYPOINT ["/entrypoint.sh"]' in logicas, 'ENTRYPOINT não aponta para entrypoint.sh'
    assert 'COPY entrypoint.sh /entrypoint.sh' in logicas, 'entrypoint.sh não é copiado para o caminho do ENTRYPOINT'
    assert (RAIZ / 'pgbouncer' / 'entrypoint.sh').is_file(), 'arquivo entrypoint.sh ausente no contexto'


def _verifica_sem_latest(texto):
    assert not re.search(r'(?i):latest\b|\blatest\b', texto), 'tag latest proibida'


def _mutar(texto, de, para):
    assert de in texto, f'mutação não aplicou: {de!r} não está no Dockerfile'
    return texto.replace(de, para)


def test_base_postgres_18_fixada_por_digest():
    _verifica_base(DOCKERFILE)


def test_base_sem_digest_falha():
    # Caso negativo: sem o digest, a tag `postgres:18` muda sob a imagem sem aviso.
    mutado = re.sub(r'@sha256:[0-9a-f]{64}', '', DOCKERFILE)
    with pytest.raises(AssertionError, match='digest'):
        _verifica_base(mutado)


def test_pacote_pgbouncer_com_versao_exata():
    _verifica_pacote(DOCKERFILE)


def test_pacote_sem_versao_falha():
    # Caso negativo: `pgbouncer` sem `=versão` deixa o apt puxar outra versão do PGDG.
    mutado = _mutar(DOCKERFILE, 'pgbouncer=1.26.1-1.pgdg13+1', 'pgbouncer')
    with pytest.raises(AssertionError, match='versão exata'):
        _verifica_pacote(mutado)


def test_pacote_com_outra_versao_falha():
    mutado = _mutar(DOCKERFILE, 'pgbouncer=1.26.1-1.pgdg13+1', 'pgbouncer=1.25.0-1.pgdg13+1')
    with pytest.raises(AssertionError, match='versão exata'):
        _verifica_pacote(mutado)


def test_termina_como_usuario_nao_root():
    _verifica_usuario_nao_root(DOCKERFILE)


def test_usuario_root_no_fim_falha():
    # Caso negativo: `USER root` no fim roda o PgBouncer com privilégio de root.
    mutado = _mutar(DOCKERFILE, 'USER postgres', 'USER root')
    with pytest.raises(AssertionError, match='root'):
        _verifica_usuario_nao_root(mutado)


def test_usuario_zero_no_fim_falha():
    mutado = _mutar(DOCKERFILE, 'USER postgres', 'USER 0')
    with pytest.raises(AssertionError, match='root'):
        _verifica_usuario_nao_root(mutado)


def test_entrypoint_aponta_para_o_script():
    _verifica_entrypoint(DOCKERFILE)


def test_entrypoint_fora_do_script_falha():
    # Caso negativo: ENTRYPOINT para outro caminho deixa a imagem sem a configuração do `auth`.
    mutado = _mutar(DOCKERFILE, 'ENTRYPOINT ["/entrypoint.sh"]', 'ENTRYPOINT ["/bin/sh"]')
    with pytest.raises(AssertionError, match='entrypoint.sh'):
        _verifica_entrypoint(mutado)


def test_dockerfile_sem_tag_latest():
    _verifica_sem_latest(DOCKERFILE)


def test_tag_latest_falha():
    # Caso negativo: `latest` muda a cada publicação da base e quebra a reprodução do build.
    mutado = re.sub(r'^FROM postgres:18', 'FROM postgres:latest', DOCKERFILE, flags=re.M)
    with pytest.raises(AssertionError, match='latest'):
        _verifica_sem_latest(mutado)
