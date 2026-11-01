"""Cadastro territorial (R7): a plataforma cria a empresa, o Administrador cria fazenda e sub-área.

Não há autocadastro: toda função aqui começa por `pode()`. Negado: `PermissionDenied`.
Renomear, arquivar e desarquivar (003 R9, R11) seguem o mesmo molde: trava, `pode()`, grava, `auditar`.
"""

import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from comum.auditoria import auditar
from identidade import senha
from identidade.models import Pessoa
from permissao.cargos_base import criar_cargos_base
from permissao.models import Concessao, Convite
from permissao.pode import pode
from territorio.models import Empresa, Fazenda, NivelDivisao, SubArea

NIVEL_MAXIMO = 3
NOMES_PADRAO_DOS_NIVEIS = {1: 'Gleba', 2: 'Talhão'}  # R10: o nível 3 nasce sem nome


def nome_valido(nome, maximo=200):
    """Nome sem espaços nas pontas. Vazio, só espaços ou maior que `maximo` levanta `nome_invalido`: a regra vale na
    função, não só no formulário (R9)."""
    limpo = (nome or '').strip()
    if not limpo or len(limpo) > maximo:
        raise ValidationError('Informe um nome de 1 a %(maximo)s caracteres.', code='nome_invalido', params={'maximo': maximo})
    return limpo


def criar_empresa(solicitante, nome, nome_administrador, email_administrador, cpf_administrador):
    """Cria a empresa, os quatro cargos-base e o primeiro Administrador de empresa, convidado por senha temporária,
    que fica como Administrador titular (R23).

    Tudo numa transação; o e-mail sai depois do commit e falha de SMTP só vai para o log: empresa e administrador ficam, e a senha temporária volta no retorno.
    CPF já cadastrado levanta `cpf_duplicado` (a pessoa já existe: shortcut, o convite de quem já tem conta
    espera uma decisão sobre o Administrador de empresa que não é novo no sistema). Devolve
    `(empresa, administrador, senha_temporaria)`.
    """
    if not pode(solicitante, 'criar_empresa'):
        raise PermissionDenied
    nome = nome_valido(nome)
    with transaction.atomic():
        empresa = Empresa.objects.create(nome=nome)
        NivelDivisao.objects.bulk_create(
            NivelDivisao(empresa=empresa, nivel=nivel, nome=nome_do_nivel) for nivel, nome_do_nivel in NOMES_PADRAO_DOS_NIVEIS.items()
        )
        auditar('empresa_criada', solicitante, empresa, empresa.pk)
        cargos = criar_cargos_base(empresa)
        administrador = Pessoa.objects.criar(
            nome_administrador, email_administrador, cpf_administrador, empresa_origem=empresa
        )
        auditar('pessoa_criada', solicitante, administrador, empresa.pk)
        temporaria = senha.emitir_senha_temporaria(administrador)
        concessao = Concessao.objects.create(
            pessoa=administrador, cargo=cargos['administrador'], empresa=empresa, concedida_por=solicitante
        )
        auditar(
            'concessao_criada', solicitante, concessao, empresa.pk,
            {'pessoa_id': administrador.pk, 'cargo_id': concessao.cargo_id, 'fazenda_id': None, 'sub_area_id': None},
        )
        empresa.titular = administrador
        empresa.save(update_fields=['titular'])
    return empresa, administrador, temporaria


def criar_fazenda(solicitante, empresa, nome):
    nome = nome_valido(nome)
    with transaction.atomic():
        _travar(empresa)  # espera um arquivamento em curso e depois lê o estado gravado (R11)
        if not pode(solicitante, 'criar_fazenda', empresa):
            raise PermissionDenied
        fazenda = Fazenda.objects.create(empresa=empresa, nome=nome)
        auditar('fazenda_criada', solicitante, fazenda, fazenda.empresa_id)
    return fazenda


def criar_sub_area(solicitante, fazenda, nome, pai=None):
    """Sub-área raiz da fazenda (sem `pai`) ou filha de `pai`; até 3 níveis (R7). Passe `pai` lido do banco."""
    if pai is not None and pai.fazenda_id != fazenda.pk:
        raise ValidationError('O pai é de outra fazenda.', code='pai_de_outra_fazenda')
    nome = nome_valido(nome)
    nivel = 1 if pai is None else pai.nivel + 1
    if nivel > NIVEL_MAXIMO:
        raise ValidationError('A divisão da fazenda tem no máximo 3 níveis.', code='nivel_maximo')
    with transaction.atomic():
        _travar(fazenda)
        if not pode(solicitante, 'criar_sub_area', pai or fazenda):
            raise PermissionDenied
        sub_area = SubArea.objects.create(empresa=fazenda.empresa, fazenda=fazenda, pai=pai, nivel=nivel, nome=nome)
        sub_area.refresh_from_db()  # o gatilho preenche `caminho`, de que `pode()` depende (achado do Qodo, PR #11)
        auditar('sub_area_criada', solicitante, sub_area, sub_area.empresa_id)
    return sub_area


def _empresa_de(alvo):
    return alvo.pk if isinstance(alvo, Empresa) else alvo.empresa_id


def _travar(alvo):
    """`select_for_update` da linha do alvo. A ordem entre linhas é sempre empresa, fazenda, sub-área (a de
    `delegacao.py`), para dois atos concorrentes não darem deadlock. Fora do alcance da RLS a linha some e o caminho é
    o da permissão negada. Chamar dentro de `transaction.atomic()`."""
    if not list(type(alvo).objects.select_for_update().filter(pk=alvo.pk).values_list('pk', flat=True)):
        raise PermissionDenied


def _filhos(alvo):
    """`(fazendas, sub_áreas)` abaixo do alvo, sem o próprio alvo."""
    if isinstance(alvo, Empresa):
        return Fazenda.objects.filter(empresa=alvo), SubArea.objects.filter(empresa=alvo)
    if isinstance(alvo, Fazenda):
        return Fazenda.objects.none(), SubArea.objects.filter(fazenda=alvo)
    return Fazenda.objects.none(), SubArea.objects.filter(caminho__contains=f'/{alvo.pk}/')


def _travar_arvore(alvo):
    _travar(alvo)
    fazendas, sub_areas = _filhos(alvo)
    list(fazendas.select_for_update().order_by('pk').values_list('pk', flat=True))
    list(sub_areas.select_for_update().order_by('pk').values_list('pk', flat=True))


def _renomear(solicitante, alvo, nome, acao_auditoria):
    nome = nome_valido(nome)
    with transaction.atomic():
        _travar(alvo)
        if not pode(solicitante, 'renomear', alvo):
            raise PermissionDenied
        antigo = alvo.nome
        alvo.nome = nome
        alvo.save(update_fields=['nome'])
        auditar(acao_auditoria, solicitante, alvo, _empresa_de(alvo), {'nome_antigo': antigo, 'nome_novo': nome})
    return alvo


def renomear_empresa(solicitante, empresa, nome):
    return _renomear(solicitante, empresa, nome, 'empresa_renomeada')


def renomear_fazenda(solicitante, fazenda, nome):
    return _renomear(solicitante, fazenda, nome, 'fazenda_renomeada')


def renomear_sub_area(solicitante, sub_area, nome):
    return _renomear(solicitante, sub_area, nome, 'sub_area_renomeada')


def _afetados(alvo):
    """Ids de fazendas e sub-áreas ainda ativas que o arquivamento de `alvo` atinge, o próprio alvo incluído."""
    fazendas, sub_areas = _filhos(alvo)
    fazendas_ids = list(fazendas.filter(arquivada_em__isnull=True).values_list('pk', flat=True))
    sub_areas_ids = list(sub_areas.filter(arquivada_em__isnull=True).values_list('pk', flat=True))
    if isinstance(alvo, Fazenda):
        fazendas_ids.append(alvo.pk)
    elif isinstance(alvo, SubArea):
        sub_areas_ids.append(alvo.pk)
    return fazendas_ids, sub_areas_ids


def _convites_pendentes(alvo, fazendas_ids, sub_areas_ids, agora):
    escopo = Q(fazenda_id__in=fazendas_ids) | Q(sub_area_id__in=sub_areas_ids)
    if isinstance(alvo, Empresa):
        escopo |= Q(empresa_id=alvo.pk)
    return Convite.objects.filter(
        escopo, aceito_em__isnull=True, recusado_em__isnull=True, cancelado_em__isnull=True, expira_em__gt=agora
    )


def efeitos_do_arquivamento(alvo):
    """O que arquivar `alvo` atinge além dele, para a tela de confirmação dizer a verdade: `(fazendas, sub_áreas,
    convites pendentes)` que passam a arquivados ou cancelados."""
    fazendas_ids, sub_areas_ids = _afetados(alvo)
    convites = _convites_pendentes(alvo, fazendas_ids, sub_areas_ids, timezone.now()).count()
    return len(fazendas_ids) - isinstance(alvo, Fazenda), len(sub_areas_ids) - isinstance(alvo, SubArea), convites


def arquivar(solicitante, alvo):
    """Arquiva `alvo` (Empresa, Fazenda ou SubArea) e o que está abaixo dele num só ato (`arquivamento`) e invalida os
    convites pendentes do escopo (`cancelado_em`; não voltam ao desarquivar). Dado e concessões ficam intactos (R11).
    Filho já arquivado por outro ato continua com o identificador dele."""
    with transaction.atomic():
        _travar_arvore(alvo)
        if not pode(solicitante, 'arquivar', alvo):
            raise PermissionDenied
        agora, ato = timezone.now(), uuid.uuid4()
        marca = {'arquivada_em': agora, 'arquivada_por': solicitante, 'arquivamento': ato}
        fazendas_ids, sub_areas_ids = _afetados(alvo)
        Fazenda.objects.filter(pk__in=fazendas_ids).update(**marca)
        SubArea.objects.filter(pk__in=sub_areas_ids).update(**marca)
        type(alvo).objects.filter(pk=alvo.pk).update(**marca)
        invalidados = sorted(_convites_pendentes(alvo, fazendas_ids, sub_areas_ids, agora).values_list('pk', flat=True))
        Convite.objects.filter(pk__in=invalidados).update(cancelado_em=agora)
        auditar(
            'territorio_arquivado', solicitante, alvo, _empresa_de(alvo),
            {'arquivamento': str(ato), 'convites_invalidados': invalidados},
        )
    alvo.refresh_from_db()
    return alvo


def _ancestral_arquivado(alvo):
    if isinstance(alvo, Empresa):
        return False
    ancestrais = [] if isinstance(alvo, Fazenda) else [int(i) for i in alvo.caminho.split('/') if i]
    return (
        Empresa.objects.filter(pk=alvo.empresa_id, arquivada_em__isnull=False).exists()
        or (isinstance(alvo, SubArea) and Fazenda.objects.filter(pk=alvo.fazenda_id, arquivada_em__isnull=False).exists())
        or SubArea.objects.filter(pk__in=ancestrais, arquivada_em__isnull=False).exists()
    )


def desarquivar(solicitante, alvo):
    """Restaura `alvo` e só os filhos arquivados no mesmo ato. Ancestral ainda arquivado: `ancestral_arquivado`
    (desarquive o de cima antes). Convite invalidado não volta (R11)."""
    with transaction.atomic():
        _travar_arvore(alvo)
        if not pode(solicitante, 'desarquivar', alvo):
            raise PermissionDenied
        atual = type(alvo).objects.get(pk=alvo.pk)
        if atual.arquivada_em is None:
            raise ValidationError('O item não está arquivado.', code='nao_arquivado')
        if _ancestral_arquivado(atual):
            raise ValidationError('Desarquive o item de cima antes.', code='ancestral_arquivado')
        solta = {'arquivada_em': None, 'arquivada_por': None, 'arquivamento': None}
        fazendas, sub_areas = _filhos(atual)
        fazendas.filter(arquivamento=atual.arquivamento).update(**solta)
        sub_areas.filter(arquivamento=atual.arquivamento).update(**solta)
        type(alvo).objects.filter(pk=alvo.pk).update(**solta)
        auditar('territorio_desarquivado', solicitante, alvo, _empresa_de(alvo), {'arquivamento': str(atual.arquivamento)})
    alvo.refresh_from_db()
    return alvo
