"""Uso dos tiles do Google nas duas janelas da cota (004b R13, R14).

A contagem vem de uma `fonte` injetada (Cloud Monitoring, métrica do projeto: decisão da T3.1). Sem fonte, ou com a
fonte falhando, `usados` fica `None` e a tela diz "não medido": ausente nunca vira zero, e estimativa nunca passa por
medição (AGENTS §Código). Renovação: meia-noite do Pacífico, a cota diária todo dia e a franquia no dia 1 (doc do Google,
2026-11-06).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

REGISTRO = logging.getLogger(__name__)
PACIFICO = ZoneInfo('America/Los_Angeles')
NAO_MEDIDO = 'não medido'


@dataclass(frozen=True)
class Janela:
    nome: str
    usados: int | None
    total: int
    renova_em: datetime
    origem: str

    @property
    def porcentagem(self):
        """Pode passar de 100 (uso acima do total). Total zero ou uso não medido: `None`, nunca divisão por zero."""
        if self.usados is None or self.total <= 0:
            return None
        return self.usados / self.total * 100


def _meia_noite(dia):
    """Meia-noite do fuso do Pacífico no dia de `dia`."""
    return datetime(dia.year, dia.month, dia.day, tzinfo=PACIFICO)


def inicio_e_renovacao_diaria(agora):
    """Início do dia no Pacífico e a próxima meia-noite (renovação da cota diária)."""
    hoje = _meia_noite(agora.astimezone(PACIFICO))
    return hoje, _meia_noite(hoje + timedelta(days=1))  # soma em relógio de parede: vale na troca de horário de verão


def inicio_e_renovacao_mensal(agora):
    """Início do mês no Pacífico e o dia 1 do mês seguinte (renovação da franquia grátis)."""
    local = agora.astimezone(PACIFICO)
    inicio = _meia_noite(local.replace(day=1))
    proximo = (local.replace(day=28) + timedelta(days=4)).replace(day=1)
    return inicio, _meia_noite(proximo)


def _contar(fonte, inicio, fim):
    """`(usados, origem)`. Sem fonte, fonte sem nenhum ponto (`None`) ou fonte que falha: `(None, NAO_MEDIDO)`."""
    if fonte is None:
        return None, NAO_MEDIDO
    try:
        usados = fonte.contar(inicio, fim)
        return (None, NAO_MEDIDO) if usados is None else (usados, fonte.origem)
    except Exception:  # fonte fora do ar não derruba a tela: "não medido", e a causa fica no log
        REGISTRO.exception('Falha ao ler o uso do Google em %s.', fonte.origem)
        return None, NAO_MEDIDO


def janelas(agora, total_diario, total_mensal, fonte=None):
    """Janela diária (cota do projeto) e mensal (franquia grátis), nessa ordem."""
    resultado = []
    for nome, total, (inicio, renovacao) in (
        ('Diária (cota do projeto)', total_diario, inicio_e_renovacao_diaria(agora)),
        ('Mensal (franquia grátis)', total_mensal, inicio_e_renovacao_mensal(agora)),
    ):
        usados, origem = _contar(fonte, inicio, agora)
        resultado.append(Janela(nome, usados, total, renovacao, origem))
    return resultado
