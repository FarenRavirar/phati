"""Contador de uso de atalho por pessoa (003 R26, D083). A tabela `uso_acao` tem RLS por pessoa (migração 0009): toda
leitura e gravação assina a identidade só durante o bloco, como `pode.memoria_de`. Não guarda alvo, só ação e contagem."""

import logging
from contextlib import contextmanager

from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from permissao.contexto import fixar_identidade, limpar_identidade
from permissao.models import UsoAcao

registro = logging.getLogger(__name__)


@contextmanager
def _como_a_propria_pessoa(pessoa):
    # Com erro, `atomic()` desfaz a transação e a assinatura vai junto; limpar no `finally` rodaria SQL em transação abortada.
    with transaction.atomic(), connection.cursor() as consulta:
        fixar_identidade(consulta, pessoa.pk)
        yield
        limpar_identidade(consulta)


def registrar_uso(pessoa, acao):
    """Soma um uso da ação. Falha vira log e não propaga: contar nunca derruba a ação principal (R26)."""
    try:
        with _como_a_propria_pessoa(pessoa):
            agora = timezone.now()
            filtro = UsoAcao.objects.filter(pessoa=pessoa, acao=acao)
            if not filtro.update(contagem=F('contagem') + 1, ultimo_uso=agora):
                _, criada = UsoAcao.objects.get_or_create(pessoa=pessoa, acao=acao, defaults={'contagem': 1, 'ultimo_uso': agora})
                if not criada:  # outra requisição criou a linha entre o UPDATE e o INSERT
                    filtro.update(contagem=F('contagem') + 1, ultimo_uso=agora)
    except Exception:  # noqa: BLE001  qualquer erro, de banco ou não, fica no log e a página segue
        registro.exception('Falha ao registrar uso da ação %s', acao)


def usos_da_pessoa(pessoa):
    """`{acao: UsoAcao}` da própria pessoa. Falha de leitura vira log e devolve vazio: o Início cai na ordem fixa."""
    try:
        with _como_a_propria_pessoa(pessoa):
            return {uso.acao: uso for uso in UsoAcao.objects.filter(pessoa=pessoa)}
    except Exception:  # noqa: BLE001  mesmo motivo de `registrar_uso`
        registro.exception('Falha ao ler o uso de ações')
        return {}


def definir_estado(pessoa, acao, *, fixado=None, oculto=None):
    """Grava Fixar e Ocultar da própria pessoa. Escolha explícita: o erro sobe, não é engolido."""
    with _como_a_propria_pessoa(pessoa):
        uso, _ = UsoAcao.objects.get_or_create(pessoa=pessoa, acao=acao)
        if fixado is not None:
            uso.fixado = fixado
        if oculto is not None:
            uso.oculto = oculto
        uso.save(update_fields=['fixado', 'oculto'])
