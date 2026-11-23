"""Imagem do PgBouncer (spec 009 R18): base fixada por digest, pacote com versão exata, usuário não root, entrypoint.

Asserções estáticas sobre o texto do Dockerfile, no molde de `test_imagem_banco.py`. Cada checagem é uma função que
recebe o texto: os testes positivos passam o Dockerfile real; os negativos passam o mesmo texto com uma mutação.
"""

import re
import shlex
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


def _palavra(instrucao):
    """Palavra-chave da instrução; o Dockerfile não diferencia maiúsculas de minúsculas."""
    return instrucao.split(None, 1)[0].upper()


_DIGEST_BASE = re.compile(r'postgres:18@sha256:[0-9a-f]{64}')


def _verifica_base(texto):
    """Todo FROM é `postgres:18` fixado por digest ou referência a estágio anterior já declarado com `AS`."""
    estagios, froms = set(), 0
    for instrucao in _instrucoes(texto):
        if _palavra(instrucao) != 'FROM':
            continue
        froms += 1
        argumentos = [a for a in instrucao.split()[1:] if not a.startswith('--')]
        assert argumentos, 'FROM sem imagem'
        if argumentos[0].lower() not in estagios:
            assert _DIGEST_BASE.fullmatch(argumentos[0]), 'base sem postgres:18 fixado por digest'
        if len(argumentos) == 3 and argumentos[1].upper() == 'AS':
            estagios.add(argumentos[2].lower())
    assert froms, 'sem FROM'


_INSTALADORES = {('apt-get', 'install'), ('apt', 'install')}


def _instalacoes_apt(texto):
    """Pacotes (sem opções) de cada `apt-get install` que uma instrução RUN executa; texto citado em `echo` não conta."""
    instalacoes = []
    for instrucao in _instrucoes(texto):
        if _palavra(instrucao) != 'RUN':
            continue
        for comando in re.split(r'&&|\|\||;', instrucao[len('RUN'):]):
            try:
                tokens = shlex.split(comando)
            except ValueError:
                continue
            if tuple(tokens[:2]) in _INSTALADORES:
                instalacoes.append([t for t in tokens[2:] if not t.startswith('-')])
    return instalacoes


def _verifica_pacote(texto):
    instalacoes = _instalacoes_apt(texto)
    assert len(instalacoes) == 1, 'esperava exatamente um apt-get install executado'
    assert 'pgbouncer=1.26.1-1.pgdg13+1' in instalacoes[0], 'pgbouncer sem versão exata fixada'
    assert 'pgbouncer' not in instalacoes[0], 'pgbouncer instalado sem versão'


def _e_root(usuario):
    """Nome `root` ou UID zero (`0`, `00`): o processo roda com privilégio de root."""
    return re.fullmatch(r'root|0+', usuario) is not None


def _verifica_usuario_nao_root(texto):
    logicas = _instrucoes(texto)
    usuarios = [i.split(None, 1)[1] for i in logicas if _palavra(i) == 'USER']
    assert usuarios, 'sem instrução USER'
    # `usuario:grupo`: só o usuário define o UID do processo.
    assert not _e_root(usuarios[-1].split(':', 1)[0]), 'imagem termina como root'
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


def test_segundo_estagio_sem_digest_falha():
    # Caso negativo (S2): um FROM posterior sem digest é base não fixada, mesmo com o primeiro fixado.
    mutado = _mutar(DOCKERFILE, 'RUN apt-get update', 'FROM postgres:18 AS extra\nRUN apt-get update')
    with pytest.raises(AssertionError, match='digest'):
        _verifica_base(mutado)


def test_segundo_estagio_com_flag_platform_sem_digest_falha():
    # Caso negativo: a flag `--platform` não pode esconder a referência sem digest.
    mutado = _mutar(DOCKERFILE, 'RUN apt-get update', 'FROM --platform=linux/amd64 postgres:18 AS extra\nRUN apt-get update')
    with pytest.raises(AssertionError, match='digest'):
        _verifica_base(mutado)


def test_segundo_estagio_com_flag_platform_e_digest_passa():
    # Caminho feliz: a flag `--platform` é ignorada e a referência fixada por digest é aceita.
    achado = re.search(r'postgres:18@sha256:[0-9a-f]{64}', DOCKERFILE)
    assert achado, 'digest do postgres:18 ausente no Dockerfile'
    digest = achado.group(0)
    mutado = _mutar(DOCKERFILE, 'RUN apt-get update', f'FROM --platform=linux/amd64 {digest} AS extra\nRUN apt-get update')
    _verifica_base(mutado)


def test_estagio_que_parte_de_estagio_anterior_passa():
    # Caminho feliz (S2): `FROM base` reaproveita o estágio já fixado por digest e não precisa de digest próprio.
    mutado = _mutar(DOCKERFILE, 'RUN apt-get update', 'FROM base AS extra\nRUN apt-get update')
    mutado = re.sub(r'^(FROM postgres:18@sha256:[0-9a-f]{64})$', r'\1 AS base', mutado, flags=re.M)
    _verifica_base(mutado)


@pytest.mark.parametrize(
    'echo',
    [
        "echo 'apt-get install -y --no-install-recommends pgbouncer=1.26.1-1.pgdg13+1'",
        'echo apt-get install -y --no-install-recommends pgbouncer=1.26.1-1.pgdg13+1',
    ],
)
def test_apt_install_dentro_de_echo_falha(echo):
    # Caso negativo (S6): `apt-get install` citado num `echo` não instala nada, com aspas ou sem.
    mutado = _mutar(DOCKERFILE, '&& apt-get install -y --no-install-recommends pgbouncer=1.26.1-1.pgdg13+1', f'&& {echo}')
    with pytest.raises(AssertionError, match='apt-get install'):
        _verifica_pacote(mutado)


def test_usuario_root_com_grupo_falha():
    # Caso negativo (S1): `root:root` roda como root; a parte do grupo não muda o UID.
    mutado = _mutar(DOCKERFILE, 'USER postgres', 'USER root:root')
    with pytest.raises(AssertionError, match='root'):
        _verifica_usuario_nao_root(mutado)


def test_usuario_zero_com_grupo_falha():
    mutado = _mutar(DOCKERFILE, 'USER postgres', 'USER 0:0')
    with pytest.raises(AssertionError, match='root'):
        _verifica_usuario_nao_root(mutado)


def test_usuario_zero_com_zeros_falha():
    mutado = _mutar(DOCKERFILE, 'USER postgres', 'USER 00')
    with pytest.raises(AssertionError, match='root'):
        _verifica_usuario_nao_root(mutado)


def test_usuario_root_em_minusculas_falha():
    # Caso negativo (E1, achado fora do Sourcery): instrução Dockerfile não diferencia maiúsculas.
    mutado = _mutar(DOCKERFILE, 'USER postgres', 'USER postgres\nuser root')
    with pytest.raises(AssertionError, match='root'):
        _verifica_usuario_nao_root(mutado)


def test_usuario_nao_root_com_grupo_root_passa():
    # Caminho feliz: o usuário é `postgres`; grupo `root` não torna o processo root.
    mutado = _mutar(DOCKERFILE, 'USER postgres', 'USER postgres:root')
    _verifica_usuario_nao_root(mutado)
