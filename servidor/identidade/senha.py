"""Senha: hash Argon2id, validação e senha temporária (R3, R4; plan.md §Autenticação)."""

import secrets
from datetime import timedelta

from django.contrib.auth.hashers import Argon2PasswordHasher
from django.contrib.auth.password_validation import CommonPasswordValidator
from django.core.exceptions import ValidationError
from django.utils import timezone

from identidade import cpf, email, sessao

NOME_DO_PRODUTO = 'phati'
COMPRIMENTO_MINIMO = 15
COMPRIMENTO_MAXIMO = 128
VALIDADE_TEMPORARIA = timedelta(hours=72)
# 32 símbolos sem ambíguos (sem 0, O, 1, I); 16 deles dão 80 bits.
ALFABETO_TEMPORARIA = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


class HasherArgon2(Argon2PasswordHasher):
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


def definir_senha(pessoa, senha):
    """Valida e grava a senha nova; zera temporária, falhas e bloqueio e revoga os acessos do aplicativo.

    A sessão de navegador cai sozinha: o hash de autenticação dela deriva do hash da senha (R15).
    O aviso por e-mail é de quem chama, fora de transação.
    """
    validar_senha(senha, pessoa, cpf_da_pessoa=cpf.decifrar(pessoa.cpf_cifrado))
    pessoa.set_password(senha)
    pessoa.deve_trocar_senha = False
    pessoa.senha_temporaria_ate = None
    pessoa.falhas_consecutivas = 0
    pessoa.bloqueada_ate = None
    pessoa.save()
    sessao.revogar_acessos(pessoa)


def trocar_senha(pessoa, senha_atual, senha_nova):
    if not pessoa.check_password(senha_atual):
        raise ValidationError('Senha atual incorreta.', code='senha_atual_incorreta')
    definir_senha(pessoa, senha_nova)
    email.enviar_aviso_de_troca(pessoa)


def emitir_senha_temporaria(pessoa):
    """Gera a senha temporária (uso único, 72 h), grava só o hash, envia por e-mail e a devolve a quem criou."""
    senha = ''.join(secrets.choice(ALFABETO_TEMPORARIA) for _ in range(16))
    pessoa.set_password(senha)
    pessoa.senha_temporaria_ate = timezone.now() + VALIDADE_TEMPORARIA
    pessoa.deve_trocar_senha = True
    pessoa.falhas_consecutivas = 0
    pessoa.bloqueada_ate = None
    pessoa.save()
    sessao.revogar_acessos(pessoa)
    email.enviar_senha_temporaria(pessoa, senha)
    return senha
