"""Tempo uniforme (R2, R5, A2; T5.5c): CPF existente e inexistente não se distinguem pelo tempo da resposta.

Medido em 2026-10-29, 15 rodadas por caso, banco local: a diferença de medianas fica em poucos ms (UPDATE do contador
em `entrar`; consulta e gravação do pedido em `solicitar`). `FOLGA` é bem maior que isso e bem menor que o atraso
do SMTP simulado (`smtp_lento`, 200 ms), então o teste falha se o envio voltar ao caminho da resposta e não falha por ruído da máquina.
"""

import json
import statistics
import time

from django.test import Client

from identidade.models import PedidoRedefinicao, Pessoa
from identidade.testes.conftest import CPF

RODADAS = 15
FOLGA = 0.05  # diferença máxima aceita entre as medianas, em segundos
TETO = 0.15  # mediana máxima do pedido de redefinição, abaixo do atraso do SMTP simulado (200 ms)


def _mediana(cliente, rota, corpo, esperado, antes=lambda: None):
    tempos = []
    for _ in range(RODADAS):
        antes()
        inicio = time.perf_counter()
        resposta = cliente.post(rota, json.dumps(corpo), content_type='application/json')
        tempos.append(time.perf_counter() - inicio)
        # Pedido que falha rápido nos dois casos passaria no teste sem exercitar o caminho (Sourcery, PR #17).
        assert resposta.status_code == esperado
    return statistics.median(tempos)


def test_pedido_de_redefinicao_com_smtp_lento_leva_o_mesmo_tempo_para_cpf_existente_e_inexistente(pessoa, cpf_novo, smtp_lento):
    rota = '/api/v1/redefinir-senha/solicitar'
    cliente = Client()
    # Pedido recente segura o novo: sem apagar, só a primeira rodada pagaria o caminho inteiro.
    existente = _mediana(cliente, rota, {'cpf': CPF}, 204, antes=PedidoRedefinicao.objects.all().delete)
    inexistente = _mediana(cliente, rota, {'cpf': cpf_novo()}, 204)
    assert abs(existente - inexistente) < FOLGA
    # Envio síncrono nos dois caminhos soma o mesmo atraso às duas medianas e passaria acima; o teto prova que o
    # SMTP lento (200 ms) ficou fora da resposta (Sourcery, PR #18).
    assert max(existente, inexistente) < TETO


def test_entrada_com_senha_errada_leva_o_mesmo_tempo_para_cpf_existente_e_inexistente(pessoa, cpf_novo):
    rota = '/api/v1/entrar'
    cliente = Client()
    corpo = {'cpf': CPF, 'senha': 'senha errada de teste'}
    # Zera o contador: depois de algumas falhas a conta bloqueia e a rodada deixaria de gravar a falha.
    existente = _mediana(cliente, rota, corpo, 401, antes=lambda: Pessoa.objects.update(falhas_consecutivas=0, bloqueada_ate=None))
    inexistente = _mediana(cliente, rota, {**corpo, 'cpf': cpf_novo()}, 401)
    assert abs(existente - inexistente) < FOLGA
