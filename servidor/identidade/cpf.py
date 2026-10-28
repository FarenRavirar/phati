"""CPF: normalizar, validar, buscar e cifrar (R1; plan.md §Autenticação).

`cpf_busca` (HMAC-SHA256) serve à busca e à unicidade sem expor o CPF. `cpf_cifrado` (Fernet, cifra autenticada)
serve à exibição ao Administrador. As duas subchaves saem da raiz `PHATI_CHAVE_CPF` por HKDF, com rótulos distintos.
Rotação: decifrar cada `cpf_cifrado` com a raiz antiga e regravar `cpf_busca` e `cpf_cifrado` com a nova.
Este módulo não registra log: o CPF nunca sai dele (R1).
"""

import base64
import hashlib
import hmac
import re

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.exceptions import ValidationError


def _subchave(rotulo):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=rotulo).derive(settings.CHAVE_CPF)


def normalizar_cpf(texto):
    """Devolve os 11 dígitos de um CPF válido (aceita ponto e traço); recusa o resto."""
    cpf = re.sub(r'[.\-]', '', texto.strip())
    if not re.fullmatch(r'\d{11}', cpf) or len(set(cpf)) == 1:
        raise ValidationError('CPF inválido.', code='cpf_invalido')
    for tamanho in (9, 10):
        soma = sum(int(d) * peso for d, peso in zip(cpf[:tamanho], range(tamanho + 1, 1, -1)))
        if int(cpf[tamanho]) != (soma * 10 % 11) % 10:
            raise ValidationError('CPF inválido.', code='cpf_invalido')
    return cpf


def chave_de_busca(cpf):
    return hmac.new(_subchave(b'phati/cpf/busca'), cpf.encode(), hashlib.sha256).hexdigest()


def _fernet():
    return Fernet(base64.urlsafe_b64encode(_subchave(b'phati/cpf/cifra')))


def cifrar(cpf):
    return _fernet().encrypt(cpf.encode()).decode()


def decifrar(cifrado):
    return _fernet().decrypt(cifrado.encode()).decode()
