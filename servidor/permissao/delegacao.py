"""Delegação de acesso (R10; plan.md §Permissão — função pode()).

Convidar e conceder só alcançam cargo de nível estritamente abaixo do de quem concede, dentro do escopo dele e só com
permissões que ele tem, exceto o Administrador, que também convida Administrador. O Administrador no escopo conta
como quem tem todo o catálogo (D043) e é o único que concede ação não delegável. O Administrador titular da empresa
(R23) só sai por transferência de titularidade. O Administrador da plataforma não tem limite. Toda função trava a linha da pessoa-alvo antes da
concessão, a ordem única de `identidade.senha._pessoa_travada`, para não voltar o deadlock achado na Fase 2.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from identidade import senha
from identidade.models import Pessoa
from permissao.models import BASES_COM_CATEGORIA, NIVEL_DA_BASE, Concessao, ConcessaoCategoria, concessoes_ativas
from permissao.pode import Alvo, alvo_de, memoria_de
from territorio.models import Empresa, Fazenda, SubArea


def _campos_do_escopo(escopo):
    if isinstance(escopo, Empresa):
        return {'empresa_id': escopo.pk}
    if isinstance(escopo, Fazenda):
        return {'empresa_id': escopo.empresa_id, 'fazenda_id': escopo.pk}
    if isinstance(escopo, SubArea):
        return {'empresa_id': escopo.empresa_id, 'fazenda_id': escopo.fazenda_id, 'sub_area_id': escopo.pk}
    raise ValueError('escopo deve ser Empresa, Fazenda ou SubArea')


def _alvo_da_concessao(concessao):
    if concessao.sub_area_id is None:
        return Alvo(concessao.empresa_id, concessao.fazenda_id)
    return alvo_de(SubArea.objects.get(pk=concessao.sub_area_id))


def pode_conceder(quem, concessao, categorias=()):
    """`concessao` é a proposta (cargo, empresa, escopo, período), salva ou não; `categorias` são as pedidas.

    Basta uma concessão de `quem` que cubra o escopo e satisfaça todas as regras: as regras não se somam entre
    concessões diferentes.
    """
    if quem is None or not quem.is_authenticated:
        return False
    if quem.administrador_plataforma:
        return True
    cargo = concessao.cargo
    if cargo.empresa_id != concessao.empresa_id:
        return False
    memoria = memoria_de(quem)
    alvo = _alvo_da_concessao(concessao)
    concedidas = frozenset(cargo.permissoes.values_list('pk', flat=True))
    pedidas = frozenset(categoria.pk for categoria in categorias)
    for vinculo in memoria.vinculos:
        if 'convidar_pessoa' not in vinculo.permissoes or not vinculo.cobre(alvo):
            continue
        # Nível estritamente abaixo (R10), salvo o Administrador, que também convida Administrador (mantenedor, 2026-10-29).
        if NIVEL_DA_BASE[vinculo.base] < NIVEL_DA_BASE[cargo.base] or (
            vinculo.base != 'administrador' and NIVEL_DA_BASE[vinculo.base] == NIVEL_DA_BASE[cargo.base]
        ):
            continue
        if vinculo.base != 'administrador' and (
            not concedidas <= vinculo.permissoes or not all(memoria.catalogo[codigo] for codigo in concedidas)
        ):
            continue
        # Ninguém concede categoria que não tem: lista vazia é nenhuma categoria (nega por padrão).
        if vinculo.base in BASES_COM_CATEGORIA and not pedidas <= vinculo.categorias:
            continue
        return True
    return False


def _proposta(quem, cargo, escopo, inicio, fim):
    return Concessao(
        cargo=cargo, concedida_por=quem, inicio=inicio or timezone.now(), fim=fim, **_campos_do_escopo(escopo)
    )


def _gravar(proposta, pessoa, categorias):
    proposta.pessoa = pessoa
    proposta.save()
    ConcessaoCategoria.objects.bulk_create(
        ConcessaoCategoria(concessao=proposta, categoria=categoria) for categoria in categorias
    )
    return proposta


def conceder(quem, pessoa, cargo, escopo, categorias=(), inicio=None, fim=None):
    """Concede `cargo` a `pessoa` em `escopo` (Empresa, Fazenda ou SubArea). Negado: `PermissionDenied`."""
    proposta = _proposta(quem, cargo, escopo, inicio, fim)
    with transaction.atomic():
        Pessoa.objects.select_for_update().get(pk=pessoa.pk)
        if not pode_conceder(quem, proposta, categorias):
            raise PermissionDenied
        return _gravar(proposta, pessoa, categorias)


def convidar(quem, nome, email, cpf, cargo, escopo, categorias=(), inicio=None, fim=None):
    """Cria a pessoa (origem na empresa do escopo), envia a senha temporária e concede o cargo, tudo na mesma
    transação: SMTP que falha desfaz o convite. Devolve `(pessoa, senha_temporaria)`. CPF já cadastrado levanta
    `cpf_duplicado`: para quem já existe, `conceder()`."""
    proposta = _proposta(quem, cargo, escopo, inicio, fim)
    if not pode_conceder(quem, proposta, categorias):
        raise PermissionDenied
    with transaction.atomic():
        pessoa = Pessoa.objects.criar(nome, email, cpf, empresa_origem=Empresa.objects.get(pk=proposta.empresa_id))
        temporaria = senha.emitir_senha_temporaria(pessoa)
        _gravar(proposta, pessoa, categorias)
    return pessoa, temporaria


def _pode_revogar(quem, concessao):
    """`revogar_acesso` no escopo da concessão e nível base acima do cargo dela, ou igual se for Administrador
    (como no convite; mantenedor, 2026-10-29). O Administrador titular é protegido à parte, em `revogar_concessao`."""
    if quem.administrador_plataforma:
        return True
    alvo = _alvo_da_concessao(concessao)
    return any(
        'revogar_acesso' in vinculo.permissoes
        and vinculo.cobre(alvo)
        and (vinculo.base == 'administrador' or NIVEL_DA_BASE[vinculo.base] > NIVEL_DA_BASE[concessao.cargo.base])
        for vinculo in memoria_de(quem).vinculos
    )


def _administra_a_empresa_inteira(concessao):
    return concessao.cargo.base == 'administrador' and concessao.fazenda_id is None


def revogar_concessao(quem, concessao):
    """Grava `revogada_em` e `revogada_por`. Vale na requisição seguinte da pessoa atingida (R11)."""
    if quem is None or not quem.is_authenticated:
        raise PermissionDenied
    with transaction.atomic():
        # Pessoa, depois empresa: a trava da pessoa serializa as revogações dela e a da empresa fecha a corrida com
        # `transferir_titularidade` (um teste transacional prova as duas).
        Pessoa.objects.select_for_update().get(pk=concessao.pessoa_id)
        empresa = Empresa.objects.select_for_update().get(pk=concessao.empresa_id)
        atual = Concessao.objects.select_related('cargo').get(pk=concessao.pk)
        if not _pode_revogar(quem, atual):
            raise PermissionDenied
        if atual.pessoa_id == empresa.titular_id and _administra_a_empresa_inteira(atual):
            raise ValidationError(
                'O Administrador titular só sai por transferência de titularidade.', code='titular_protegido'
            )
        if atual.revogada_em is not None:
            raise ValidationError('Concessão já revogada.', code='concessao_ja_revogada')
        atual.revogada_em = timezone.now()
        atual.revogada_por = quem
        atual.save(update_fields=['revogada_em', 'revogada_por'])
    concessao.refresh_from_db()


def transferir_titularidade(quem, empresa, novo_titular):
    """Passa o título de Administrador titular (R23). Só o titular atual ou a plataforma transferem, e o novo titular
    precisa ser Administrador ativo da empresa inteira. O titular antigo vira Administrador comum."""
    if quem is None or not quem.is_authenticated:
        raise PermissionDenied
    with transaction.atomic():
        atual = Empresa.objects.select_for_update().get(pk=empresa.pk)
        if not (quem.administrador_plataforma or quem.pk == atual.titular_id):
            raise PermissionDenied
        if not concessoes_ativas().filter(
            pessoa=novo_titular, empresa=atual, fazenda__isnull=True, cargo__base='administrador'
        ).exists():
            raise ValidationError('O novo titular precisa ser Administrador da empresa inteira.', code='titular_invalido')
        atual.titular = novo_titular
        atual.save(update_fields=['titular'])
    empresa.refresh_from_db()
