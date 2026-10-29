"""Senha: hash Argon2id, validação e senha temporária (R3, R4; plan.md §Autenticação)."""

import secrets
from contextlib import contextmanager
from datetime import timedelta

from django.contrib.auth.hashers import Argon2PasswordHasher
from django.contrib.auth.password_validation import CommonPasswordValidator
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from identidade import cpf, email, sessao
from identidade.models import PedidoRedefinicao, Pessoa

NOME_DO_PRODUTO = 'phati'
COMPRIMENTO_MINIMO = 15
COMPRIMENTO_MAXIMO = 128
VALIDADE_TEMPORARIA = timedelta(hours=72)
# 32 símbolos sem ambíguos (sem 0, O, 1, I); 16 deles dão 80 bits.
ALFABETO_TEMPORARIA = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


class GeradorHashArgon2(Argon2PasswordHasher):
    """Argon2id com o mínimo do OWASP Password Storage Cheat Sheet (lido em 2026-10-22):
    19 MiB de memória, 2 iterações, paralelismo 1. O nome do algoritmo não muda, para `identify_hasher` funcionar.
    """

    time_cost = 2
    memory_cost = 19 * 1024  # em KiB
    parallelism = 1


_comuns = CommonPasswordValidator()


def validar_senha(senha, pessoa=None, cpf_da_pessoa=None):
    """Aplica R3. Cada recusa tem `code` próprio, para o teste provar qual regra disparou."""
    if len(senha) < COMPRIMENTO_MINIMO:
        raise ValidationError('Senha curta demais.', code='senha_curta')
    if len(senha) > COMPRIMENTO_MAXIMO:
        raise ValidationError('Senha longa demais.', code='senha_longa')
    try:
        _comuns.validate(senha)
    except ValidationError:
        raise ValidationError('Senha comum demais.', code='senha_comum') from None
    minuscula = senha.casefold()
    palavras = {NOME_DO_PRODUTO}
    if cpf_da_pessoa:
        c = cpf_da_pessoa
        palavras.update({c, f'{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}'})
    if pessoa is not None:
        palavras.update(parte for parte in pessoa.nome.casefold().split() if len(parte) >= 4)
    if any(palavra in minuscula for palavra in palavras):
        raise ValidationError('Senha contém palavra do contexto.', code='senha_contexto')


@contextmanager
def _pessoa_travada(pessoa):
    """Trava a linha da pessoa até o fim da transação (achados do Qodo, PR #9): trocas de senha, emissões de
    temporária e emissão ou rotação de acesso do aplicativo passam a se serializar. Quem chama sincroniza a
    própria instância com `refresh_from_db()` depois do bloco (sem código depois do `yield`, achado do Sonar)."""
    with transaction.atomic():
        yield Pessoa.objects.select_for_update().get(pk=pessoa.pk)


def _encerrar_credenciais_antigas(pessoa):
    # Achado do Codex (PR #9): link de redefinição pedido antes da troca não pode valer depois dela.
    sessao.revogar_acessos(pessoa)
    PedidoRedefinicao.objects.filter(pessoa=pessoa, usado_em__isnull=True).update(usado_em=timezone.now())


_CAMPOS_DA_SENHA = ['password', 'deve_trocar_senha', 'senha_temporaria_ate', 'falhas_consecutivas', 'bloqueada_ate']


def definir_senha(pessoa, senha):
    """Valida e grava a senha nova; zera temporária, falhas e bloqueio e revoga os acessos do aplicativo.

    A sessão de navegador cai sozinha: o hash de autenticação dela deriva do hash da senha (R15).
    Grava só os campos da senha, para não sobrescrever o que outra transação mudou. O aviso por e-mail é de
    quem chama, fora de transação.
    """
    validar_senha(senha, pessoa, cpf_da_pessoa=cpf.decifrar(pessoa.cpf_cifrado))
    with _pessoa_travada(pessoa) as travada:
        travada.set_password(senha)
        travada.deve_trocar_senha = False
        travada.senha_temporaria_ate = None
        travada.falhas_consecutivas = 0
        travada.bloqueada_ate = None
        travada.save(update_fields=_CAMPOS_DA_SENHA)
        _encerrar_credenciais_antigas(travada)
    pessoa.refresh_from_db()


def trocar_senha(pessoa, senha_atual, senha_nova):
    with _pessoa_travada(pessoa) as travada:
        # A conferência da senha atual e a gravação da nova ficam sob a mesma trava.
        if not travada.check_password(senha_atual):
            raise ValidationError('Senha atual incorreta.', code='senha_atual_incorreta')
        definir_senha(travada, senha_nova)
    pessoa.refresh_from_db()
    email.enviar_aviso_de_troca(pessoa)


def emitir_senha_temporaria(pessoa):
    """Gera a senha temporária (uso único, 72 h), grava só o hash, envia por e-mail e a devolve a quem criou.

    O e-mail sai depois do commit; a senha volta a quem chama, então falha do SMTP (só log) não deixa a pessoa
    sem acesso (achado do Qodo, PR #9; T5.5a 4 e 5).
    """
    senha = ''.join(secrets.choice(ALFABETO_TEMPORARIA) for _ in range(16))
    with _pessoa_travada(pessoa) as travada:
        travada.set_password(senha)
        travada.senha_temporaria_ate = timezone.now() + VALIDADE_TEMPORARIA
        travada.deve_trocar_senha = True
        travada.falhas_consecutivas = 0
        travada.bloqueada_ate = None
        travada.save(update_fields=_CAMPOS_DA_SENHA)
        _encerrar_credenciais_antigas(travada)
        email.enviar_senha_temporaria(travada, senha)
    pessoa.refresh_from_db()
    return senha
