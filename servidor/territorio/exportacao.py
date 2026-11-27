"""Exportação CSV da lista de fazendas (spec 012, R30): formato para o Excel em português e neutralização de fórmula.

Separador `;` e UTF-8 com BOM: formato que o Excel pt-BR abre sem assistente de importação (a confirmar). Célula que começa
com `=`, `+`, `-`, `@`, tab, retorno ou quebra de linha ganha apóstrofo na frente, contra CSV injection (fonte:
https://owasp.org/www-community/attacks/CSV_Injection, consultada em 2026-11-27). A própria OWASP avisa que o apóstrofo
pode não resistir a salvar e reabrir no Excel, então a neutralização é mitigação, não garantia. Ausente vira "Sem dados",
nunca 0.
"""

import csv
import io
from collections import Counter

from django.db import transaction
from django.utils import timezone

from comum.auditoria import auditar
from permissao.pode import com_permissao

CABECALHO = ('Fazenda', 'Empresa', 'Município', 'Área (ha)', 'Talhões', 'Situação', 'Atualizado')
SEM_DADOS = 'Sem dados'
_INICIO_PERIGOSO = ('=', '+', '-', '@', '\t', '\r', '\n')
_BOM = '﻿'


def neutralizar(celula: str) -> str:
    return "'" + celula if celula.startswith(_INICIO_PERIGOSO) else celula


def _texto(valor):
    return SEM_DADOS if valor in (None, '') else str(valor)


def _area(valor):
    # Vírgula decimal, como o Excel pt-BR lê como número; ausente segue "Sem dados", nunca 0.
    return SEM_DADOS if valor is None else f'{valor:.2f}'.replace('.', ',')


def _celulas(linha):
    fazenda = linha.fazenda
    return (
        fazenda.nome,
        fazenda.empresa.nome,
        _texto(fazenda.municipio),
        _area(linha.area),
        str(linha.talhoes),
        'Arquivada' if fazenda.arquivada_em else 'Ativa',
        timezone.localtime(linha.atualizado).strftime('%d/%m/%Y'),
    )


def csv_das_fazendas(linhas) -> str:
    """Texto do CSV (com BOM): cabeçalho e uma linha por fazenda, todas as células neutralizadas."""
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=';')
    escritor.writerow(CABECALHO)
    for linha in linhas:
        escritor.writerow([neutralizar(celula) for celula in _celulas(linha)])
    return _BOM + saida.getvalue()


def registrar_exportacao(pessoa, linhas) -> None:
    """Um evento de auditoria por empresa com fazenda exportada, com a quantidade. A busca não entra no registro (R30)."""
    por_empresa = Counter(linha.fazenda.empresa_id for linha in linhas)
    with transaction.atomic(), com_permissao(pessoa, 'exportar_dados'):
        for empresa_id, quantidade in por_empresa.items():
            auditar('dados_exportados', pessoa, None, empresa_id, {'quantidade': quantidade})
