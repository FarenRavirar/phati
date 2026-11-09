"""Leitura da auditoria (005 R2 a R4, R7): uma só função de escopo e de texto para a API e para a tela.

`evento_auditoria` não tem RLS (plan da 001, §RLS): o isolamento entre empresas é o filtro de `consultar`, e só ele. A
função fica em `permissao` porque precisa de `escopos_da_acao`; `comum` não importa `permissao`. Chame dentro de
`com_permissao` (a rota e a página já o fazem): a leitura de nomes de empresa, fazenda e sub-área passa pela RLS delas.
"""

from datetime import timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

from comum.auditoria import auditar
from comum.auditoria_rotulos import rotulo_e_resumo
from comum.models import EventoAuditoria
from identidade.models import Pessoa
from permissao.models import Cargo
from permissao.pode import escopos_da_acao
from territorio.models import Empresa, Fazenda, SubArea

ACAO = 'ver_auditoria'
JANELA_PADRAO = timedelta(days=90)
REMOVIDA = 'removida'
SISTEMA = 'Sistema'
# Tipo gravado em `alvo_tipo` → como a tela o chama e onde achar o nome. Outro tipo cai só no nome do tipo.
_TIPOS = {'Empresa': ('Empresa', Empresa), 'Fazenda': ('Fazenda', Fazenda), 'SubArea': ('Sub-área', SubArea), 'Cargo': ('Cargo', Cargo)}
_TIPOS_SEM_NOME = {'Concessao': 'Acesso', 'Convite': 'Convite'}


def _id_inteiro(valor):
    """O `detalhes` é JSON gravado por código nosso, mas leitura não confia nele: só inteiro vira id (bool não é id)."""
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def _filtrar(escopos, desde, ate, acao, pessoa_id, alvo_pessoa_id, empresa_id):
    eventos = EventoAuditoria.objects.all()
    if not escopos.plataforma:
        # `empresa_id` nulo nunca entra aqui: `NULL IN (...)` não é verdade (A3).
        eventos = eventos.filter(empresa_id__in=escopos.empresas)
    if empresa_id is not None:
        if not escopos.plataforma and empresa_id not in escopos.empresas:
            raise ObjectDoesNotExist  # 404 comum, igual a empresa inexistente (R3)
        eventos = eventos.filter(empresa_id=empresa_id)
    eventos = eventos.filter(hora_servidor__gte=desde or timezone.now() - JANELA_PADRAO)
    if ate is not None:
        eventos = eventos.filter(hora_servidor__lte=ate)
    if acao:
        eventos = eventos.filter(acao=acao)
    if pessoa_id is not None:
        eventos = eventos.filter(pessoa_id=pessoa_id)
    if alvo_pessoa_id is not None:
        # Pessoa como alvo direto, ou citada em `detalhes.pessoa_id` (concessão e convite têm outro alvo). O texto do
        # JSON casa com o índice de expressão da migração 0003.
        eventos = eventos.annotate(pessoa_do_detalhe=KeyTextTransform('pessoa_id', 'detalhes')).filter(
            Q(alvo_tipo='Pessoa', alvo_id=alvo_pessoa_id) | Q(pessoa_do_detalhe=str(alvo_pessoa_id))
        )
    return eventos


def _nomes(eventos):
    """Nome de cada id da página, em poucas consultas (nunca uma por linha). Sem CPF: o campo nem é lido."""
    pessoas, empresas, por_tipo = set(), set(), {tipo: set() for tipo in _TIPOS}
    for e in eventos:
        pessoas.add(e.pessoa_id)
        empresas.add(e.empresa_id)
        pessoas.add(_id_inteiro(e.detalhes.get('pessoa_id')) if isinstance(e.detalhes, dict) else None)
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
    if tipo in _TIPOS_SEM_NOME:
        pessoa = _id_inteiro(detalhes.get('pessoa_id'))
        return _TIPOS_SEM_NOME[tipo] + (f' de {nomes["Pessoa"].get(pessoa, REMOVIDA)}' if pessoa is not None else '')
    return ''


def _linha(evento, nomes):
    rotulo, resumo = rotulo_e_resumo(evento.acao, evento.detalhes)
    if evento.pessoa_id is None:
        quem = SISTEMA
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


def _empresa_da_consulta(escopos, empresa_id):
    """Empresa que o evento da consulta leva: a pedida, ou a única do escopo; senão nenhuma (só a plataforma o vê)."""
    if empresa_id is not None:
        return empresa_id
    return next(iter(escopos.empresas)) if not escopos.plataforma and len(escopos.empresas) == 1 else None


def consultar(quem, *, limite=30, depois=0, desde=None, ate=None, acao=None, pessoa_id=None, alvo_pessoa_id=None, empresa_id=None):
    """Eventos que `quem` pode ler, do mais recente ao mais antigo, e se há mais além da página (`depois` = último id).

    Quem não lê auditoria em empresa alguma, ou pede empresa fora do escopo, recebe 404 (`ObjectDoesNotExist`). A
    primeira página (sem `depois`) grava `auditoria_consultada` na mesma transação, com os filtros usados.
    """
    escopos = escopos_da_acao(quem, ACAO)
    if not (escopos.plataforma or escopos.empresas):
        raise ObjectDoesNotExist
    eventos = _filtrar(escopos, desde, ate, acao, pessoa_id, alvo_pessoa_id, empresa_id)
    if depois:
        eventos = eventos.filter(pk__lt=depois)
    with transaction.atomic():
        pagina = list(eventos.order_by('-id')[: limite + 1])
        if not depois:
            usados = {'desde': desde and desde.isoformat(), 'ate': ate and ate.isoformat(), 'acao': acao,
                      'pessoa_id': pessoa_id, 'alvo_pessoa_id': alvo_pessoa_id, 'empresa_id': empresa_id}
            auditar('auditoria_consultada', quem, None, _empresa_da_consulta(escopos, empresa_id),
                    {chave: valor for chave, valor in usados.items() if valor is not None})
    mais = len(pagina) > limite
    pagina = pagina[:limite]
    nomes = _nomes(pagina)
    return [_linha(e, nomes) for e in pagina], mais
