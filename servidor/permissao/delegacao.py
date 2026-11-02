"""Delegação de acesso (R10; plan.md §Permissão — função pode()).

Convidar e conceder só alcançam cargo de nível estritamente abaixo do de quem concede, dentro do escopo dele e só com
permissões que ele tem, exceto o Administrador, que também convida Administrador. O Administrador no escopo conta
como quem tem todo o catálogo (D043) e é o único que concede ação não delegável. O Administrador titular da empresa
(R23) só sai por transferência de titularidade. O Administrador da plataforma não tem limite. Toda função trava a linha da pessoa-alvo antes da
concessão, a ordem única de `identidade.senha._pessoa_travada`, para não voltar o deadlock achado na Fase 2.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Q

from django.utils import timezone

from comum.auditoria import auditar

from identidade import senha
from identidade.models import Pessoa
from permissao.models import BASES_COM_CATEGORIA, NIVEL_DA_BASE, Concessao, ConcessaoCategoria
from permissao.pode import Alvo, alvo_de, escopo_arquivado, escopo_de, esquecer, memoria_de
from territorio.models import Empresa, Fazenda, SubArea


def _travar_pessoa(pk):
    """Trava a linha da pessoa sem bloquear a checagem de chave estrangeira: `FOR UPDATE` conflita com o
    `KEY SHARE` que gravar `concedida_por`, `revogada_por` ou `titular` pede em outra pessoa, e duas operações
    cruzadas (A revoga B enquanto B revoga A) davam deadlock. `FOR NO KEY UPDATE` serializa do mesmo jeito e deixa
    a FK passar (achado do Codex, PR #11, reproduzido por teste de corrida)."""
    Pessoa.objects.select_for_update(no_key=True).get(pk=pk)


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


def _nivel_permite(base_de_quem, base_do_cargo):
    """Nível estritamente abaixo (R10), salvo o Administrador, que também convida e revoga Administrador
    (mantenedor, 2026-10-29)."""
    return base_de_quem == 'administrador' or NIVEL_DA_BASE[base_de_quem] > NIVEL_DA_BASE[base_do_cargo]


def _fim_cabe(vinculo, fim):
    """O acesso concedido não sobrevive à concessão de quem concede (achado do Qodo, PR #11; inferência a confirmar)."""
    limite = vinculo.concessao.fim
    return limite is None or (fim is not None and fim <= limite)


def _concede(vinculo, memoria, proposta, alvo, concedidas, pedidas):
    """Uma concessão de quem concede satisfaz todas as regras de R10 para a proposta?"""
    if not vinculo.tem('convidar_pessoa') or not vinculo.cobre(alvo):
        return False
    if not _nivel_permite(vinculo.base, proposta.cargo.base) or not _fim_cabe(vinculo, proposta.fim):
        return False
    if vinculo.base != 'administrador' and (
        not concedidas.issubset(vinculo.permissoes) or not all(memoria.catalogo[codigo] for codigo in concedidas)
    ):
        return False
    # Ninguém concede categoria que não tem: lista vazia é nenhuma categoria (nega por padrão).
    return vinculo.base not in BASES_COM_CATEGORIA or pedidas <= vinculo.categorias


def exigir_categoria_compativel(cargo, categorias):
    """Só Técnico e Usuário têm categoria de dado (D035); o gatilho do banco recusa o resto, e sem esta checagem a
    entrada ruim virava erro 500, ou um convite que só falhava no aceite (Codex, PR #16)."""
    if categorias and cargo.base not in BASES_COM_CATEGORIA:
        raise ValidationError('Este cargo não aceita categoria de dado.', code='categoria_incompativel')


def pode_conceder(quem, concessao, categorias=()):
    """`concessao` é a proposta (cargo, empresa, escopo, período), salva ou não; `categorias` são as pedidas.

    Basta uma concessão de `quem` que cubra o escopo e satisfaça todas as regras: as regras não se somam entre
    concessões diferentes.
    """
    if quem is None or not quem.is_authenticated:
        return False
    cargo = concessao.cargo
    # Antes do atalho da plataforma: cargo de uma empresa em escopo de outra viola a chave composta do banco, e a
    # plataforma também não pode propor isso (erro 500 e convite inválido; Sourcery, PR #16).
    if cargo.empresa_id != concessao.empresa_id:
        return False
    # Convidar e conceder são escrita: escopo arquivado nega até a plataforma (003 R11).
    if escopo_arquivado(escopo_de(concessao)):
        return False
    if quem.administrador_plataforma:
        return True
    memoria = memoria_de(quem)
    alvo = _alvo_da_concessao(concessao)
    concedidas = frozenset(cargo.permissoes.values_list('pk', flat=True))
    pedidas = frozenset(categoria.pk for categoria in categorias)
    return any(_concede(vinculo, memoria, concessao, alvo, concedidas, pedidas) for vinculo in memoria.vinculos)


def travar_escopo(proposta):
    """Trava a linha do escopo da proposta: convidar e conceder esperam um arquivamento em curso e depois leem o estado
    gravado, em vez de deixar convite pendente num escopo arquivado (003 R11). Chamar dentro de `transaction.atomic()`."""
    escopo = escopo_de(proposta)
    list(type(escopo).objects.select_for_update(no_key=True).filter(pk=escopo.pk).values_list('pk', flat=True))


def com_fim_no_futuro():
    # Concessão ou convite cujo `fim` já passou nunca vale (o banco recusa `fim <= inicio`): fora das listas (Sourcery).
    return Q(fim__isnull=True) | Q(fim__gt=timezone.now())


def concessao_igual(pessoa, proposta, categorias):
    """A concessão não revogada e sem fim passado que já dá à pessoa o mesmo que `proposta` (cargo, lugar, fim e
    categorias) e que já começou quando a proposta começa, ou None. Concessão futura não antecipa o acesso pedido
    (Greptile, PR #30). Sem isto, repetir um convite cujo CPF já virou pessoa, ou aceitar um convite do que ela já
    tem, gravaria uma segunda concessão igual (Sourcery, PR #30); o mesmo vale para conceder duas vezes seguidas
    (clique duplo): revogar uma deixaria a outra valendo (003 Fase 4, mercado: GitHub e Azure não duplicam)."""
    candidatas = Concessao.objects.filter(
        pessoa=pessoa, cargo_id=proposta.cargo_id, empresa_id=proposta.empresa_id, fazenda_id=proposta.fazenda_id,
        sub_area_id=proposta.sub_area_id, fim=proposta.fim, inicio__lte=proposta.inicio, revogada_em__isnull=True,
    ).filter(com_fim_no_futuro())
    pedidas = {categoria.pk for categoria in categorias}
    return next((c for c in candidatas if set(c.categorias.values_list('pk', flat=True)) == pedidas), None)


def _chave_da_trava_do_cargo(cargo_id):
    # Um bigint só: prefixo fixo nos 32 bits altos (separa de outro uso de advisory lock) e o id do cargo nos baixos.
    return (0xC0C0 << 32) | (cargo_id & 0xFFFFFFFF)


def travar_cargo(cargo_id):
    """Trava COMPARTILHADA do cargo até o fim da transação: quem concede, convida ou aceita convite não bloqueia outro que
    concede, mas espera a edição do cargo (`travar_cargo_para_edicao`) terminar e lê as permissões novas em `pode_conceder`.
    Sem ela a checagem lia o conjunto antigo enquanto a edição o ampliava, e dava a quem concede uma permissão que ele não tem
    (a chave estrangeira só bloqueia na gravação, depois da checagem).

    É um advisory lock, não `SELECT ... FOR UPDATE` na linha: a RLS deixa o Curador de fazenda ou sub-área só LER o cargo, e o
    `FOR UPDATE` exige também a política de escrita, então para ele travaria nada e a corrida voltaria (Codex e Greptile, PR #32).
    Também não levanta exceção para cargo de outra empresa: a recusa vem de `pode_conceder`. Compartilhada entre os três
    caminhos, não fecha ciclo com a trava de pessoa. Ordem: pessoa, escopo, cargo; `gerenciar_cargo` faz empresa e cargo.
    Chamar dentro de `transaction.atomic()`, antes de `pode_conceder`."""
    with connection.cursor() as consulta:
        consulta.execute('SELECT pg_advisory_xact_lock_shared(%s)', [_chave_da_trava_do_cargo(cargo_id)])


def travar_cargo_para_edicao(cargo_id):
    """Trava EXCLUSIVA do cargo até o fim da transação, para `gerenciar_cargo`: espera quem concede e bloqueia quem começa."""
    with connection.cursor() as consulta:
        consulta.execute('SELECT pg_advisory_xact_lock(%s)', [_chave_da_trava_do_cargo(cargo_id)])


def _proposta(quem, cargo, escopo, inicio, fim):
    return Concessao(
        cargo=cargo, concedida_por=quem, inicio=inicio or timezone.now(), fim=fim, **_campos_do_escopo(escopo)
    )


def _gravar(quem, proposta, pessoa, categorias):
    proposta.pessoa = pessoa
    proposta.save()
    ConcessaoCategoria.objects.bulk_create(
        ConcessaoCategoria(concessao=proposta, categoria=categoria) for categoria in categorias
    )
    auditar(
        'concessao_criada', quem, proposta, proposta.empresa_id,
        {'pessoa_id': pessoa.pk, 'cargo_id': proposta.cargo_id, 'fazenda_id': proposta.fazenda_id,
         'sub_area_id': proposta.sub_area_id},
    )
    return proposta


def conceder(quem, pessoa, cargo, escopo, categorias=(), inicio=None, fim=None):
    """Concede `cargo` a `pessoa` em `escopo` (Empresa, Fazenda ou SubArea). Negado: `PermissionDenied`."""
    categorias = tuple(categorias)  # percorrido na checagem e na gravação: um gerador acabaria na primeira
    exigir_categoria_compativel(cargo, categorias)
    proposta = _proposta(quem, cargo, escopo, inicio, fim)
    with transaction.atomic():
        _travar_pessoa(pessoa.pk)
        travar_escopo(proposta)
        travar_cargo(cargo.pk)
        if not pode_conceder(quem, proposta, categorias):
            raise PermissionDenied
        return concessao_igual(pessoa, proposta, categorias) or _gravar(quem, proposta, pessoa, categorias)


def criar_pessoa_e_conceder(quem, proposta, categorias, nome, email, cpf):
    """Cria a pessoa e grava a concessão proposta. Chamar dentro da transação, já com `travar_escopo` e `pode_conceder`
    conferidos: `convidar` e `convidar_por_cpf` fazem isso uma vez cada, para os dois caminhos custarem o mesmo."""
    pessoa = Pessoa.objects.criar(nome, email, cpf, empresa_origem=Empresa.objects.get(pk=proposta.empresa_id))
    # Grava a concessão antes de enviar a senha: período ou categoria recusados pelo banco não podem deixar um
    # e-mail com credencial de conta que não existe (achado do Codex, PR #11).
    auditar('pessoa_criada', quem, pessoa, proposta.empresa_id)
    _gravar(quem, proposta, pessoa, categorias)
    return pessoa, senha.emitir_senha_temporaria(pessoa)


def convidar(quem, nome, email, cpf, cargo, escopo, categorias=(), inicio=None, fim=None):
    """Cria a pessoa (origem na empresa do escopo), envia a senha temporária e concede o cargo, tudo na mesma
    transação; o e-mail sai depois do commit e falha de SMTP só vai para o log, sem desfazer o convite. Devolve `(pessoa, senha_temporaria)`. CPF já cadastrado levanta
    `cpf_duplicado`: para quem já existe, `conceder()`."""
    categorias = tuple(categorias)
    exigir_categoria_compativel(cargo, categorias)
    proposta = _proposta(quem, cargo, escopo, inicio, fim)
    if not pode_conceder(quem, proposta, categorias):
        raise PermissionDenied
    with transaction.atomic():
        travar_escopo(proposta)
        travar_cargo(cargo.pk)
        if not pode_conceder(quem, proposta, categorias):  # de novo, já com a trava: o arquivamento pode ter commitado
            raise PermissionDenied
        return criar_pessoa_e_conceder(quem, proposta, categorias, nome, email, cpf)


def _pode_revogar(quem, concessao):
    """`revogar_acesso` no escopo da concessão e nível base acima do cargo dela, ou igual se for Administrador
    (como no convite; mantenedor, 2026-10-29). O Administrador titular é protegido à parte, em `revogar_concessao`."""
    if quem.administrador_plataforma:
        return True
    alvo = _alvo_da_concessao(concessao)
    return any(
        vinculo.tem('revogar_acesso')
        and vinculo.cobre(alvo)
        and _nivel_permite(vinculo.base, concessao.cargo.base)
        for vinculo in memoria_de(quem).vinculos
    )


def _administra_a_empresa_inteira(concessao):
    return concessao.cargo.base == 'administrador' and concessao.fazenda_id is None


def pode_revogar(quem, concessao):
    """A tela só mostra o link de revogar a quem `revogar_concessao` aceitaria: escopo, nível do cargo e Administrador
    titular protegido (Sourcery, PR #30). A função de revogar repete a checagem sob trava."""
    if quem is None or not quem.is_authenticated or not _pode_revogar(quem, concessao):
        return False
    if not _administra_a_empresa_inteira(concessao):
        return True
    return concessao.pessoa_id != Empresa.objects.filter(pk=concessao.empresa_id).values_list('titular_id', flat=True).first()


def revogar_concessao(quem, concessao):
    """Grava `revogada_em` e `revogada_por`. Vale na requisição seguinte da pessoa atingida (R11)."""
    if quem is None or not quem.is_authenticated:
        raise PermissionDenied
    with transaction.atomic():
        # Pessoa, depois empresa: a trava da pessoa serializa as revogações dela e a da empresa fecha a corrida com
        # `transferir_titularidade` (um teste transacional prova as duas).
        _travar_pessoa(concessao.pessoa_id)
        # O titular só tem concessão da empresa inteira, então só ela disputa a trava com a transferência. Quem
        # tem escopo de fazenda não enxerga a empresa para travar (RLS) e não alcança essa concessão de qualquer jeito.
        titular_id = None
        if concessao.fazenda_id is None:
            empresa = Empresa.objects.select_for_update().filter(pk=concessao.empresa_id).first()
            if empresa is None:
                raise PermissionDenied
            titular_id = empresa.titular_id
        atual = Concessao.objects.select_related('cargo').get(pk=concessao.pk)
        if not _pode_revogar(quem, atual):
            raise PermissionDenied
        if atual.pessoa_id == titular_id and _administra_a_empresa_inteira(atual):
            raise ValidationError(
                'O Administrador titular só sai por transferência de titularidade.', code='titular_protegido'
            )
        if atual.revogada_em is not None:
            raise ValidationError('Concessão já revogada.', code='concessao_ja_revogada')
        atual.revogada_em = timezone.now()
        atual.revogada_por = quem
        atual.save(update_fields=['revogada_em', 'revogada_por'])
        auditar('concessao_revogada', quem, atual, atual.empresa_id, {'pessoa_id': atual.pessoa_id})
    concessao.refresh_from_db()


def pode_transferir_titularidade(quem, empresa):
    """Só o titular atual ou a plataforma (R23), e nunca numa empresa arquivada: transferir é escrita, e escrita em
    escopo arquivado é recusada até para a plataforma (003 R11; Qodo, PR #30). A tela de transferir pergunta isto antes da
    etapa 1; a função abaixo repete a checagem sob trava."""
    if quem is None or not quem.is_authenticated or escopo_arquivado(empresa):
        return False
    return bool(quem.administrador_plataforma or quem.pk == empresa.titular_id)


def transferir_titularidade(quem, empresa, novo_titular, justificativa):
    """Passa o título de Administrador titular (R23). Só o titular atual ou a plataforma transferem, e o novo titular
    precisa ser Administrador ativo da empresa inteira, sem prazo (concessão que vence deixaria a empresa com titular
    sem acesso). O titular antigo vira Administrador comum. A justificativa é obrigatória e fica na auditoria (D068)."""
    if quem is None or not quem.is_authenticated:
        raise PermissionDenied
    justificativa = (justificativa or '').strip()
    if not justificativa:
        raise ValidationError('Informe a justificativa da transferência.', code='justificativa_obrigatoria')
    with transaction.atomic():
        # Pessoa, depois empresa, a mesma ordem de `revogar_concessao`: a ordem inversa dava deadlock com a revogação
        # da concessão do novo titular, porque gravar `titular` pede KEY SHARE na pessoa (achado do Codex, PR #11,
        # reproduzido pelo teste de corrida).
        _travar_pessoa(novo_titular.pk)
        atual = Empresa.objects.select_for_update().get(pk=empresa.pk)
        if not pode_transferir_titularidade(quem, atual):
            raise PermissionDenied
        # Concessões lidas de novo, depois da trava: a memória do objeto pode ser de antes dela.
        esquecer(novo_titular)
        if not any(
            vinculo.base == 'administrador'
            and vinculo.concessao.empresa_id == atual.pk
            and vinculo.concessao.fazenda_id is None
            and vinculo.concessao.fim is None
            for vinculo in memoria_de(novo_titular).vinculos
        ):
            raise ValidationError(
                'O novo titular precisa ser Administrador da empresa inteira, sem prazo.', code='titular_invalido'
            )
        titular_anterior = atual.titular_id
        atual.titular = novo_titular
        atual.save(update_fields=['titular'])
        auditar('titularidade_transferida', quem, atual, atual.pk, {'de': titular_anterior, 'para': novo_titular.pk, 'justificativa': justificativa})
    empresa.refresh_from_db()
