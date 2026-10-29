"""Login por CPF e senha com bloqueio por conta (R2, R4; plan.md §Autenticação).

CPF inexistente, CPF inválido, senha errada, conta bloqueada e senha temporária vencida ou já usada devolvem o mesmo
`None`, e todos pagam uma verificação Argon2, o que deixa o tempo parecido. Não idêntico: senha errada ainda grava o
contador (um UPDATE de alguns ms) e o CPF inexistente não; resíduo registrado no PR #9, sem equalização.
O contador é da conta, nunca do IP. Tentativa feita durante o bloqueio não conta nem o prolonga.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from comum.auditoria import auditar
from identidade import cpf
from identidade.models import Pessoa


# Calculado na carga do módulo: o primeiro login com CPF inexistente não paga o custo a mais (achado do Qodo, PR #9).
_HASH_FALSO = make_password(secrets.token_urlsafe(16))


def _bloqueio_em_segundos(falhas):
    excesso = falhas - settings.AUTENTICACAO_FALHAS_LIMITE
    return min(settings.AUTENTICACAO_BLOQUEIO_BASE_SEGUNDOS * 2**excesso, settings.AUTENTICACAO_BLOQUEIO_TETO_SEGUNDOS)


def autenticar(cpf_texto, senha):
    """Devolve a pessoa autenticada ou `None`. A senha temporária é consumida no primeiro acesso correto."""
    try:
        busca = cpf.chave_de_busca(cpf.normalizar_cpf(cpf_texto))
    except ValidationError:
        busca = None
    with transaction.atomic():
        pessoa = Pessoa.objects.select_for_update().filter(cpf_busca=busca).first() if busca else None
        if pessoa is None:
            check_password(senha, _HASH_FALSO)
            return None
        agora = timezone.now()
        # Conta sem senha utilizável (recém-criada) pagaria menos que as outras: o Django nem chama o Argon2.
        if pessoa.has_usable_password():
            correta = pessoa.check_password(senha)
        else:
            check_password(senha, _HASH_FALSO)
            correta = False
        if pessoa.bloqueada_ate is not None and pessoa.bloqueada_ate > agora:
            return None
        if not correta:
            pessoa.falhas_consecutivas += 1
            if pessoa.falhas_consecutivas >= settings.AUTENTICACAO_FALHAS_LIMITE:
                segundos = _bloqueio_em_segundos(pessoa.falhas_consecutivas)
                pessoa.bloqueada_ate = agora + timedelta(seconds=segundos)
                auditar('conta_bloqueada', None, pessoa, pessoa.empresa_origem_id, {'segundos': segundos})
            pessoa.save(update_fields=['falhas_consecutivas', 'bloqueada_ate'])
            return None
        if pessoa.deve_trocar_senha:
            if pessoa.senha_temporaria_ate is None or pessoa.senha_temporaria_ate <= agora:
                return None
            pessoa.senha_temporaria_ate = None
        pessoa.falhas_consecutivas = 0
        pessoa.bloqueada_ate = None
        pessoa.save(update_fields=['falhas_consecutivas', 'bloqueada_ate', 'senha_temporaria_ate'])
        return pessoa
