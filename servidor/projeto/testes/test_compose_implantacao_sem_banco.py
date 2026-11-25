"""Implantação sem `banco` em `depends_on` (spec 009, R15, T5.4d).

Em `compose.yaml`, migracao, banco_extensoes e pgb_auth dependem de `banco`, e o compose sobe o `banco` mesmo com
`PHATI_BANCO_DESTINO=banco_novo`. O `compose.implantacao.yaml` tira essa dependência, porque o `implantar.sh` sobe o banco
ativo antes de qualquer `run`; o dev segue com ela.

Não sobe contêiner: `docker compose config` só lê os arquivos. Os valores são sintéticos e vêm do ambiente deste processo.
"""

import functools
import json

from projeto.testes.test_compose_troca_banco import _config

IMPLANTACAO = ('-f', 'compose.yaml', '-f', 'compose.implantacao.yaml')
DEV = ('-f', 'compose.yaml')
BANCOS = {'banco', 'banco_novo'}


def _servicos(flags, ambiente=None):
    rc, saida, erro = _config(flags, ambiente)
    assert rc == 0, f'config falhou (rc={rc}): {erro}'
    return json.loads(saida)['services']


def _dependem_de_banco(servicos):
    """Serviços que listam `banco` ou `banco_novo` em `depends_on`."""
    return sorted(nome for nome, servico in servicos.items() if BANCOS & set(servico.get('depends_on', {})))


@functools.cache
def _implantacao():
    return _servicos(IMPLANTACAO)


# Caminho feliz.

def test_nenhum_servico_de_implantacao_depende_do_banco():
    assert _dependem_de_banco(_implantacao()) == []


def test_com_destino_banco_novo_nenhum_servico_de_implantacao_depende_de_banco():
    assert _dependem_de_banco(_servicos(IMPLANTACAO, {'PHATI_BANCO_DESTINO': 'banco_novo'})) == []


def test_migracao_mantem_so_a_dependencia_do_postgis():
    depends = _implantacao()['migracao']['depends_on']
    assert set(depends) == {'banco_extensoes'}
    assert depends['banco_extensoes']['condition'] == 'service_completed_successfully'


def test_dev_sozinho_mantem_o_depends_on_do_banco():
    # Caso negativo da remoção: o compose.yaml de dev segue com a dependência (CI e `run --no-deps` dependem dela).
    assert set(_dependem_de_banco(_servicos(DEV))) == {'banco_extensoes', 'migracao', 'pgb_auth'}


# Caso infeliz: a dependência de volta reprova a checagem.

def test_override_que_volta_o_banco_e_detectado(tmp_path):
    # Mutação: a dependência de `banco` volta em `migracao` por um terceiro arquivo; a checagem tem que apontá-la.
    volta = tmp_path / 'volta.yaml'
    volta.write_text(
        'services:\n  migracao:\n    depends_on:\n      banco: {condition: service_healthy}\n',
        encoding='utf-8',
    )
    servicos = _servicos((*IMPLANTACAO, '-f', str(volta)))
    assert 'migracao' in _dependem_de_banco(servicos)
