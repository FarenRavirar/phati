"""Leitura da auditoria (005 R2 a R4, R7): uma só função de escopo e de texto para a API e para a tela.

`evento_auditoria` não tem RLS (plan da 001, §RLS): o isolamento entre empresas é o filtro de `consultar`, e só ele. A
função fica em `permissao` porque precisa de `escopos_da_acao`; `comum` não importa `permissao`. Chame dentro de
`com_permissao` (a rota e a página já o fazem): a leitura de nomes de empresa, fazenda e sub-área passa pela RLS delas.
"""

from collections import Counter
from datetime import datetime, time, timedelta
from itertools import chain

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

from comum.auditoria import ACOES, auditar
from comum.auditoria_rotulos import rotulo_e_resumo
from comum.models import EventoAuditoria
from identidade.models import Pessoa
from permissao.models import Cargo
from permissao.pode import age_na_plataforma_ou_em_empresa, escopos_da_acao
from territorio.models import Empresa, Fazenda, NivelDivisao, SubArea

ACAO = 'ver_auditoria'
JANELA_PADRAO = timedelta(days=90)


def data_da_janela_padrao(agora):
    """Primeiro dia da janela padrão: 90 dias atrás no fuso local. Dia inteiro, não instante: o link "Mais antigos" só leva
    data, e a página seguinte tem de cortar no mesmo ponto da primeira (PR #63, Greptile P2)."""
    return timezone.localtime(agora - JANELA_PADRAO).date()


def inicio_do_dia(dia):
    """Meia-noite local de `dia`, como datetime aware (o filtro é `>=`)."""
    return timezone.make_aware(datetime.combine(dia, time.min))
REMOVIDA = 'removida'
SISTEMA = 'Sistema'
# Tipo gravado em `alvo_tipo` → como a tela o chama e onde achar o nome. Outro tipo cai só no nome do tipo.
_TIPOS = {
    'Empresa': ('Empresa', Empresa), 'Fazenda': ('Fazenda', Fazenda), 'SubArea': ('Sub-área', SubArea), 'Cargo': ('Cargo', Cargo),
    'NivelDivisao': ('Nível', NivelDivisao),
}
_TIPOS_SEM_NOME = {'Concessao': 'Acesso', 'Convite': 'Convite'}
# Convite a quem já tem conta não revela a pessoa a quem convida (R24 da 003): enquanto não há vínculo, a auditoria também
# não a nomeia. O alvo do convite fica só "Convite"; quem recusou aparece como "Pessoa convidada"; e os filtros por pessoa
# não casam esses eventos, senão o filtro viraria uma pergunta "esta conta foi convidada?" (Greptile e Sourcery, PR #55).
SEM_VINCULO = 'Pessoa convidada'
_RECUSA = 'convite_recusado'
_ACEITE = 'convite_aceito'
# Colunas `detalhes` que apontam a pessoa afetada: `pessoa_id` (concessão, convite, titular novo) e `de` (titular que saiu).
_PESSOA_DO_DETALHE = ('pessoa_id', 'de')
# Convite sem vínculo: a pessoa convidada não aparece em filtro nem em select (R24 da 003). O aceite já tem vínculo, então fica.
_CONVITE_SEM_VINCULO = Q(alvo_tipo='Convite') & ~Q(acao=_ACEITE)
_CONSULTA = 'auditoria_consultada'  # o próprio registro de leitura: o `detalhes.pessoa_id` dele é o filtro, não um afetado


def _id_inteiro(valor):
    """O `detalhes` é JSON gravado por código nosso, mas leitura não confia nele: só inteiro vira id (bool não é id)."""
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def _do_escopo(escopos):
    """Eventos que o escopo de quem lê alcança: a plataforma vê todos (inclusive sem empresa); o resto, só as suas empresas.
    Base única de `consultar` e de `pessoas_citadas`. `empresa_id` nulo nunca entra aqui: `NULL IN (...)` não é verdade (A3)."""
    if escopos.plataforma:
        return EventoAuditoria.objects.all()
    return EventoAuditoria.objects.filter(empresa_id__in=escopos.empresas)


def _filtrar(escopos, desde, ate, acao, pessoa_id, alvo_pessoa_id, empresa_id):
    eventos = _do_escopo(escopos)
    if empresa_id is not None:
        if not escopos.plataforma and empresa_id not in escopos.empresas:
            raise ObjectDoesNotExist  # 404 comum, igual a empresa inexistente (R3)
        eventos = eventos.filter(empresa_id=empresa_id)
    if desde is None and ate is None:
        # Janela padrão só quando não há data nenhuma: com só `ate`, o piso de 90 dias cortaria tudo o que é mais antigo.
        eventos = eventos.filter(hora_servidor__gte=inicio_do_dia(data_da_janela_padrao(timezone.now())))
    elif desde is not None:
        eventos = eventos.filter(hora_servidor__gte=desde)
    if ate is not None:
        eventos = eventos.filter(hora_servidor__lte=ate)
    if acao:
        eventos = eventos.filter(acao=acao)  # a rota só aceita nome de `ACOES`; aqui a função segue segura com qualquer texto
    if pessoa_id is not None:
        eventos = eventos.filter(pessoa_id=pessoa_id).exclude(acao=_RECUSA)
    if alvo_pessoa_id is not None:
        # Pessoa como alvo direto, ou citada em `detalhes.pessoa_id` (concessão, titular novo) ou `detalhes.de` (titular
        # que saiu). O texto do JSON casa com os índices de expressão da migração 0003. Convite sem vínculo fica de fora, e
        # `auditoria_consultada` também (ver `_CONSULTA`).
        achada = Q(alvo_tipo='Pessoa', alvo_id=alvo_pessoa_id)
        for chave in _PESSOA_DO_DETALHE:
            achada |= Q(**{f'pessoa_do_detalhe_{chave}': str(alvo_pessoa_id)})
        eventos = eventos.annotate(
            **{f'pessoa_do_detalhe_{chave}': KeyTextTransform(chave, 'detalhes') for chave in _PESSOA_DO_DETALHE}
        ).filter(achada).exclude(_CONVITE_SEM_VINCULO).exclude(acao=_CONSULTA)
    return eventos


def _nomes(eventos):
    """Nome de cada id da página, em poucas consultas (nunca uma por linha). Sem CPF: o campo nem é lido."""
    pessoas, empresas, por_tipo = set(), set(), {tipo: set() for tipo in _TIPOS}
    for e in eventos:
        if e.acao != _RECUSA:
            pessoas.add(e.pessoa_id)
        empresas.add(e.empresa_id)
        if e.alvo_tipo != 'Convite' and isinstance(e.detalhes, dict):
            pessoas.add(_id_inteiro(e.detalhes.get('pessoa_id')))
        if e.alvo_tipo == 'Pessoa':
            pessoas.add(e.alvo_id)
        elif e.alvo_tipo in por_tipo:
            por_tipo[e.alvo_tipo].add(e.alvo_id)
    nomes = {'Pessoa': dict(Pessoa.objects.filter(pk__in=pessoas - {None}).values_list('pk', 'nome'))}
    nomes['Empresa'] = dict(Empresa.objects.filter(pk__in=(empresas | por_tipo['Empresa']) - {None}).values_list('pk', 'nome'))
    for tipo, (_, modelo) in _TIPOS.items():
        if tipo != 'Empresa':
            nomes[tipo] = dict(modelo.objects.filter(pk__in=por_tipo[tipo] - {None}).values_list('pk', 'nome'))
    return nomes


def _alvo(evento, nomes):
    tipo = evento.alvo_tipo
    detalhes = evento.detalhes if isinstance(evento.detalhes, dict) else {}
    if tipo == 'Pessoa':
        return nomes['Pessoa'].get(evento.alvo_id, REMOVIDA)
    if tipo in _TIPOS:
        rotulo = _TIPOS[tipo][0]
        return f'{rotulo}: {nomes[tipo].get(evento.alvo_id, REMOVIDA)}'
    if tipo == 'Convite':
        return _TIPOS_SEM_NOME[tipo]  # sem a pessoa convidada (SEM_VINCULO)
    if tipo in _TIPOS_SEM_NOME:
        pessoa = _id_inteiro(detalhes.get('pessoa_id'))
        return _TIPOS_SEM_NOME[tipo] + (f' de {nomes["Pessoa"].get(pessoa, REMOVIDA)}' if pessoa is not None else '')
    return ''


def _linha(evento, nomes):
    rotulo, resumo = rotulo_e_resumo(evento.acao, evento.detalhes)
    if evento.pessoa_id is None:
        quem = SISTEMA
    elif evento.acao == _RECUSA:
        quem = SEM_VINCULO
    else:
        quem = nomes['Pessoa'].get(evento.pessoa_id, REMOVIDA)
    if evento.empresa_id is None:
        empresa = ''
    else:
        empresa = nomes['Empresa'].get(evento.empresa_id, REMOVIDA)
    return {
        'id': evento.pk, 'hora': evento.hora_servidor, 'acao': evento.acao, 'rotulo': rotulo,
        'quem': quem, 'alvo': _alvo(evento, nomes), 'empresa': empresa, 'resumo': resumo,
    }


def pode_ver_auditoria(quem):
    """Quem lê a auditoria na plataforma ou em alguma empresa (005 Q1). A página usa esta função; o item do menu usa o mesmo
    helper de `pode.py` pelo campo `em_empresa`, e `consultar` também, então as três decisões não divergem."""
    return age_na_plataforma_ou_em_empresa(quem, ACAO)


def _empresas_da_consulta(escopos, empresa_id):
    """Empresas cujo registro leva o evento da consulta: a pedida, ou todas as do escopo, para que o Administrador de cada
    uma veja quem leu a auditoria dela. A plataforma sem filtro grava um evento sem empresa, que só ela lê."""
    if empresa_id is not None:
        return [empresa_id]
    return [None] if escopos.plataforma else sorted(escopos.empresas)


def consultar(quem, *, limite=30, depois=0, desde=None, ate=None, acao=None, pessoa_id=None, alvo_pessoa_id=None, empresa_id=None):
    """Eventos que `quem` pode ler, do mais recente ao mais antigo, e se há mais além da página (`depois` = último id).

    Quem não lê auditoria em empresa alguma, ou pede empresa fora do escopo, recebe 404 (`ObjectDoesNotExist`). A
    primeira página (sem `depois`) grava `auditoria_consultada` na mesma transação, com os filtros usados.
    """
    if not age_na_plataforma_ou_em_empresa(quem, ACAO):
        raise ObjectDoesNotExist
    escopos = escopos_da_acao(quem, ACAO)
    eventos = _filtrar(escopos, desde, ate, acao, pessoa_id, alvo_pessoa_id, empresa_id)
    if depois:
        # shortcut: cursor por id; evento com id menor que o do cursor, confirmado só depois de a página passar dele, some desta
        # navegação (reabrir a lista mostra). Revisado na PR #63 (Sourcery): `pg_snapshot_xmin` ou horizonte de transação custam
        # mais que o risco, dado o volume de plan.md §Volume. Quando melhorar: transação longa ou escrita concorrente frequente.
        eventos = eventos.filter(pk__lt=depois)
    with transaction.atomic():
        pagina = list(eventos.order_by('-id')[: limite + 1])
        if not depois:
            usados = {'desde': desde and desde.isoformat(), 'ate': ate and ate.isoformat(), 'acao': acao,
                      'pessoa_id': pessoa_id, 'alvo_pessoa_id': alvo_pessoa_id, 'empresa_id': empresa_id}
            detalhes = {chave: valor for chave, valor in usados.items() if valor is not None}
            for empresa in _empresas_da_consulta(escopos, empresa_id):
                auditar('auditoria_consultada', quem, None, empresa, detalhes)
    mais = len(pagina) > limite
    pagina = pagina[:limite]
    nomes = _nomes(pagina)
    return [_linha(e, nomes) for e in pagina], mais


def _rotulo_de_homonimo(nome, pk, origem, nomes_de_empresa):
    """Empresa de origem entre parênteses só se quem lê já a vê; senão, o id (sem dado de pessoa além do nome)."""
    return f'{nome} ({nomes_de_empresa[origem]})' if origem in nomes_de_empresa else f'{nome} (#{pk})'


def pessoas_citadas(quem):
    """(pk, rótulo) das pessoas que aparecem nos eventos que `quem` lê, para os selects de "Quem agiu" e "Pessoa afetada".

    Vem da atividade, não do diretório: ex-colaborador com evento aparece, mesmo sem concessão; quem só tem concessão, não.
    Usa a base de `consultar` e as exclusões de `_filtrar`, então convite sem vínculo fica de fora. Pessoa apagada não entra:
    não há nome para mostrar. Chame dentro de `com_permissao` (o nome da empresa de origem passa pela RLS dela).
    """
    if not age_na_plataforma_ou_em_empresa(quem, ACAO):
        raise ObjectDoesNotExist
    escopos = escopos_da_acao(quem, ACAO)
    base = _do_escopo(escopos)
    alvos = base.exclude(_CONVITE_SEM_VINCULO).exclude(acao=_CONSULTA)
    quem_agiu = base.exclude(acao=_RECUSA).order_by().values_list('pessoa_id', flat=True).distinct()
    alvo_direto = alvos.filter(alvo_tipo='Pessoa').order_by().values_list('alvo_id', flat=True).distinct()
    no_detalhe = [alvos.order_by().values_list(f'detalhes__{chave}', flat=True).distinct() for chave in _PESSOA_DO_DETALHE]
    ids = {_id_inteiro(valor) for valor in chain(quem_agiu, alvo_direto, *no_detalhe)} - {None}
    pessoas = list(Pessoa.objects.filter(pk__in=ids).order_by('nome', 'pk').values_list('pk', 'nome', 'empresa_origem_id'))
    repetidos = Counter(nome for _, nome, _ in pessoas)
    origens = {origem for _, _, origem in pessoas if origem is not None and (escopos.plataforma or origem in escopos.empresas)}
    nomes_de_empresa = dict(Empresa.objects.filter(pk__in=origens).values_list('pk', 'nome'))
    return [
        (pk, _rotulo_de_homonimo(nome, pk, origem, nomes_de_empresa) if repetidos[nome] > 1 else nome)
        for pk, nome, origem in pessoas
    ]
