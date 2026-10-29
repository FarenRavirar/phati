"""Cadastro territorial (R7): a plataforma cria a empresa, o Administrador cria fazenda e sub-área.

Não há autocadastro: toda função aqui começa por `pode()`. Negado: `PermissionDenied`.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from identidade import senha
from identidade.models import Pessoa
from permissao.cargos_base import criar_cargos_base
from permissao.models import Concessao
from permissao.pode import pode
from territorio.models import Empresa, Fazenda, SubArea

NIVEL_MAXIMO = 3


def criar_empresa(solicitante, nome, nome_administrador, email_administrador, cpf_administrador):
    """Cria a empresa, os quatro cargos-base e o primeiro Administrador de empresa, convidado por senha temporária,
    que fica como Administrador titular (R23).

    Tudo numa transação, com o e-mail dentro: SMTP que falha não deixa empresa, cargo, pessoa nem concessão.
    CPF já cadastrado levanta `cpf_duplicado` (a pessoa já existe: shortcut, o convite de quem já tem conta
    espera uma decisão sobre o Administrador de empresa que não é novo no sistema). Devolve
    `(empresa, administrador, senha_temporaria)`.
    """
    if not pode(solicitante, 'criar_empresa'):
        raise PermissionDenied
    with transaction.atomic():
        empresa = Empresa.objects.create(nome=nome)
        cargos = criar_cargos_base(empresa)
        administrador = Pessoa.objects.criar(
            nome_administrador, email_administrador, cpf_administrador, empresa_origem=empresa
        )
        temporaria = senha.emitir_senha_temporaria(administrador)
        Concessao.objects.create(
            pessoa=administrador, cargo=cargos['administrador'], empresa=empresa, concedida_por=solicitante
        )
        empresa.titular = administrador
        empresa.save(update_fields=['titular'])
    return empresa, administrador, temporaria


def criar_fazenda(solicitante, empresa, nome):
    if not pode(solicitante, 'criar_fazenda', empresa):
        raise PermissionDenied
    return Fazenda.objects.create(empresa=empresa, nome=nome)


def criar_sub_area(solicitante, fazenda, nome, pai=None):
    """Sub-área raiz da fazenda (sem `pai`) ou filha de `pai`; até 3 níveis (R7). Passe `pai` lido do banco."""
    if not pode(solicitante, 'criar_sub_area', pai or fazenda):
        raise PermissionDenied
    nivel = 1 if pai is None else pai.nivel + 1
    if nivel > NIVEL_MAXIMO:
        raise ValidationError('A divisão da fazenda tem no máximo 3 níveis.', code='nivel_maximo')
    return SubArea.objects.create(empresa=fazenda.empresa, fazenda=fazenda, pai=pai, nivel=nivel, nome=nome)
