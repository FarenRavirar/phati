"""Tempo uniforme (R2, R5, A2; T5.5c): CPF existente e inexistente não se distinguem pelo tempo da resposta.

Medido em 2026-10-29, 15 rodadas por caso, banco local: a diferença de medianas fica em poucos ms (UPDATE do contador
em `entrar`; consulta e gravação do pedido em `solicitar`). `FOLGA` é bem maior que isso e bem menor que o `ATRASO`
do SMTP simulado, então o teste falha se o envio voltar ao caminho da resposta e não falha por ruído da máquina.
"""

import json
import statistics
import time

from django.test import Client

from identidade import email
from identidade.models import PedidoRedefinicao, Pessoa
from identidade.testes.conftest import CPF

# Guardado na importação, antes de a fixture automática do conftest trocar `_despachar` pela chamada direta.
_DESPACHO_REAL = email._despachar

RODADAS = 15
ATRASO = 0.3  # SMTP lento simulado, em segundos
FOLGA = 0.05  # diferença máxima aceita entre as medianas, em segundos


def _mediana(cliente, rota, corpo, antes=lambda: None):
    tempos = []
    for _ in range(RODADAS):
        antes()
        inicio = time.perf_counter()
        cliente.post(rota, json.dumps(corpo), content_type='application/json')
        tempos.append(time.perf_counter() - inicio)
    return statistics.median(tempos)


def _smtp_lento(monkeypatch):
    monkeypatch.setattr(email, '_despachar', _DESPACHO_REAL)
    monkeypatch.setattr(email.EmailMessage, 'send', lambda self: time.sleep(ATRASO))


def test_pedido_de_redefinicao_com_smtp_lento_leva_o_mesmo_tempo_para_cpf_existente_e_inexistente(pessoa, cpf_novo, monkeypatch):
    _smtp_lento(monkeypatch)
    rota = '/api/v1/redefinir-senha/solicitar'
    cliente = Client()
    # Pedido recente segura o novo: sem apagar, só a primeira rodada pagaria o caminho inteiro.
    existente = _mediana(cliente, rota, {'cpf': CPF}, antes=PedidoRedefinicao.objects.all().delete)
    inexistente = _mediana(cliente, rota, {'cpf': cpf_novo()})
    assert existente - inexistente < FOLGA


def test_entrada_com_senha_errada_leva_o_mesmo_tempo_para_cpf_existente_e_inexistente(pessoa, cpf_novo):
    rota = '/api/v1/entrar'
    cliente = Client()
    corpo = {'cpf': CPF, 'senha': 'senha errada de teste'}
    # Zera o contador: depois de algumas falhas a conta bloqueia e a rodada deixaria de gravar a falha.
    existente = _mediana(cliente, rota, corpo, antes=lambda: Pessoa.objects.update(falhas_consecutivas=0, bloqueada_ate=None))
    inexistente = _mediana(cliente, rota, {**corpo, 'cpf': cpf_novo()})
    assert abs(existente - inexistente) < FOLGA
