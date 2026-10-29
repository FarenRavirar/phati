"""Criar e alterar cargo (R8, R10, R16; T5.5b item 1). Evento `cargo_alterado` (A13).

Quem gerencia só alcança cargo de nível estritamente abaixo do seu (o Administrador também o seu) e só com permissões
que ele mesmo tem e são delegáveis; o Administrador conta como quem tem o catálogo todo (D043). Precisa de concessão
da empresa inteira com `gerenciar_cargo`: cargo é da empresa, não da fazenda. `base` e `empresa` não mudam depois de
criados (gatilho da migração 0002), então alterar é só nome e permissões. Ações da plataforma nunca entram em cargo.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from comum.auditoria import auditar
from permissao.delegacao import _nivel_permite
from permissao.models import NIVEL_DA_BASE, Cargo, CargoPermissao, Permissao
from permissao.pode import ACOES_DA_PLATAFORMA, Alvo, memoria_de


def _pode_gerenciar(quem, empresa, base, codigos):
    if quem is None or not quem.is_authenticated:
        return False
    if quem.administrador_plataforma:
        return True
    memoria = memoria_de(quem)
    return any(
        vinculo.tem('gerenciar_cargo')
        and vinculo.cobre(Alvo(empresa.pk))
        and _nivel_permite(vinculo.base, base)
        and (vinculo.base == 'administrador' or all(c in vinculo.permissoes and memoria.catalogo[c] for c in codigos))
        for vinculo in memoria.vinculos
    )


def _codigos_validos(codigos):
    codigos = frozenset(codigos)
    existentes = set(Permissao.objects.filter(pk__in=codigos).values_list('pk', flat=True))
    if codigos & ACOES_DA_PLATAFORMA or codigos - existentes:
        raise ValidationError('Permissão inexistente ou exclusiva da plataforma.', code='permissao_invalida')
    return codigos


def gerenciar_cargo(quem, empresa, nome, codigos, base=None, cargo=None):
    """Cria (`base` obrigatória) ou altera (`cargo`) o cargo de `empresa` e grava o conjunto exato de `codigos`.

    Negado: `PermissionDenied`. Devolve o cargo.
    """
    nome = (nome or '').strip()
    if not nome or len(nome) > 100:
        raise ValidationError('Nome do cargo inválido.', code='nome_invalido')
    codigos = _codigos_validos(codigos)
    with transaction.atomic():
        if cargo is not None:
            cargo = Cargo.objects.select_for_update().get(pk=cargo.pk)
            if cargo.empresa_id != empresa.pk:
                raise PermissionDenied
            base = cargo.base
        elif base not in NIVEL_DA_BASE:
            raise ValidationError('Base do cargo inválida.', code='base_invalida')
        if not _pode_gerenciar(quem, empresa, base, codigos):
            raise PermissionDenied
        if cargo is None:
            cargo = Cargo.objects.create(empresa=empresa, nome=nome, base=base)
        else:
            cargo.nome = nome
            cargo.save(update_fields=['nome'])
            CargoPermissao.objects.filter(cargo=cargo).delete()
        CargoPermissao.objects.bulk_create(CargoPermissao(cargo=cargo, permissao_id=c) for c in sorted(codigos))
        auditar('cargo_alterado', quem, cargo, empresa.pk, {'nome': nome, 'base': base, 'permissoes': sorted(codigos)})
    return cargo
