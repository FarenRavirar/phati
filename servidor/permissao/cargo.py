"""Criar e alterar cargo (R8, R10, R16; T5.5b item 1). Evento `cargo_alterado` (A13).

Quem gerencia só alcança cargo de nível estritamente abaixo do seu (o Administrador também o seu) e só com permissões
que ele mesmo tem e são delegáveis; o Administrador conta como quem tem o catálogo todo (D043). Precisa de concessão
da empresa inteira com `gerenciar_cargo`: cargo é da empresa, não da fazenda. `base` e `empresa` não mudam depois de
criados (gatilho da migração 0002), então alterar é só nome e permissões. Ações da plataforma nunca entram em cargo.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from comum.auditoria import auditar
from permissao.delegacao import _nivel_permite, travar_cargo_para_edicao
from permissao.models import NIVEL_DA_BASE, Cargo, CargoPermissao, Permissao
from permissao.pode import ACOES_DA_PLATAFORMA, Alvo, memoria_de, pode
from territorio.models import Empresa

# Cargo de nível Administrador acompanha o catálogo (a migração que cria ação dá a permissão nova a ele) e é o que impede a
# empresa de ficar sem quem gerencie: nasce com a empresa (`criar_cargos_base`) e não se cria nem se edita aqui (mantenedor,
# 2026-11-02, opção C; criar ficou de fora depois da revisão da PR #32: um cargo de nível Administrador novo nasceria
# impossível de completar). atalho: a regra é pela base, não por marca no cargo; se a empresa precisar de cargo Administrador
# personalizado, o passo é marcar o cargo de base.
BASES_FIXAS = ('administrador',)


def _pode_gerenciar(quem, empresa, base, codigos):
    # `pode()` decide acesso, nível do Administrador e arquivamento da empresa num só lugar (003 R11); o resto abaixo
    # é a hierarquia de cargo (nível e permissões que quem gerencia tem).
    if not pode(quem, 'gerenciar_cargo', empresa):
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


def _cargo_travado_e_base(empresa, base, cargo):
    """Na alteração, o cargo relido sob a trava de linha e a base dele; na criação, `base` conferida."""
    if cargo is None:
        if base not in NIVEL_DA_BASE:
            raise ValidationError('Base do cargo inválida.', code='base_invalida')
        return None, base
    travado = Cargo.objects.select_for_update().get(pk=cargo.pk)
    if travado.empresa_id != empresa.pk:
        raise PermissionDenied
    return travado, travado.base


def _exigir_nome_livre(empresa, nome, cargo):
    # `(empresa, nome)` é único no banco; sem isto o conflito virava IntegrityError e erro 500 (Qodo, PR #16).
    repetido = Cargo.objects.filter(empresa=empresa, nome=nome)
    if cargo is not None:
        repetido = repetido.exclude(pk=cargo.pk)
    if repetido.exists():
        raise ValidationError('Já existe cargo com esse nome na empresa.', code='nome_duplicado')


def _gravar_cargo(empresa, nome, base, cargo):
    try:
        with transaction.atomic():  # ponto de salvamento: o erro de integridade aborta a transação inteira
            if cargo is None:
                return Cargo.objects.create(empresa=empresa, nome=nome, base=base)
            cargo.nome, cargo.versao = nome, cargo.versao + 1
            cargo.save(update_fields=['nome', 'versao'])  # sob a trava de linha: ninguém soma ao mesmo tempo
            return cargo
    except IntegrityError as erro:
        # A pré-checagem não vê a corrida: dois pedidos passam por ela e o segundo bate na restrição única.
        # Só essa restrição vira erro de regra; outra falha de integridade continua visível (Qodo, PR #16).
        if getattr(getattr(erro.__cause__, 'diag', None), 'constraint_name', None) != 'cargo_nome_unico_por_empresa':
            raise
        raise ValidationError('Já existe cargo com esse nome na empresa.', code='nome_duplicado') from None


def gerenciar_cargo(quem, empresa, nome, codigos, base=None, cargo=None, versao=None):
    """Cria (`base` obrigatória) ou altera (`cargo`) o cargo de `empresa` e grava o conjunto exato de `codigos`.

    Negado: `PermissionDenied`. Na alteração, `versao` é a que quem edita leu: se o cargo mudou desde então (ou a versão
    não veio), levanta `cargo_alterado_por_outra_pessoa` e não grava nada. Devolve o cargo.
    """
    nome = (nome or '').strip()
    if not nome or len(nome) > 100:
        raise ValidationError('Nome do cargo inválido.', code='nome_invalido')
    codigos = _codigos_validos(codigos)
    with transaction.atomic():
        # Trava a empresa antes de `pode()`: espera um arquivamento em curso e depois lê o estado gravado (003 R11).
        if not list(Empresa.objects.select_for_update(no_key=True).filter(pk=empresa.pk).values_list('pk', flat=True)):
            raise PermissionDenied  # fora do alcance (a RLS esconde a linha) ou inexistente: o mesmo caminho da permissão negada
        if cargo is not None:
            travar_cargo_para_edicao(cargo.pk)  # quem concede, convida ou aceita convite espera a edição e lê o conjunto novo
        cargo, base = _cargo_travado_e_base(empresa, base, cargo)
        if not _pode_gerenciar(quem, empresa, base, codigos):
            raise PermissionDenied
        # Depois da autorização: quem não pode gerenciar o cargo não descobre a versão dele.
        if base in BASES_FIXAS:  # criar ou editar: depois da autorização, quem não pode gerenciar não descobre a regra
            raise ValidationError('O cargo de nível Administrador nasce com a empresa e não se cria nem se edita: ele acompanha todas as permissões.', code='cargo_fixo')
        if cargo is not None and versao != cargo.versao:
            raise ValidationError('Outra pessoa alterou este cargo. Recarregue a página e edite de novo.', code='cargo_alterado_por_outra_pessoa')
        _exigir_nome_livre(empresa, nome, cargo)
        cargo = _gravar_cargo(empresa, nome, base, cargo)
        CargoPermissao.objects.filter(cargo=cargo).delete()  # cargo novo não tem linhas: nada a apagar
        CargoPermissao.objects.bulk_create(CargoPermissao(cargo=cargo, permissao_id=c) for c in sorted(codigos))
        auditar('cargo_alterado', quem, cargo, empresa.pk, {'nome': nome, 'base': base, 'permissoes': sorted(codigos)})
    return cargo
