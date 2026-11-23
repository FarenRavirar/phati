"""Passo de portas do CI (spec 009 T4.2, spec 006 A1): a implantação não publica porta em nenhum serviço.

O passo "Implantação não publica porta em nenhum serviço" do `.github/workflows/ci.yml` roda `docker compose config`
com os dois arquivos da implantação e falha se achar `ports`. Este módulo confere que o passo existe com essa forma e
que o mesmo `config`, rodado aqui, não publica porta. Não sobe contêiner: `docker compose config` só lê os arquivos.
"""

import json
import re
from pathlib import Path

import pytest
from django.conf import settings

from projeto.testes.test_compose_bluegreen import IMPLANTACAO, _config

RAIZ = Path(settings.DIRETORIO_BASE)
CI = (RAIZ.parent / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')


def _passo_de_portas(ci):
    """Bloco do passo de portas dentro do ci.yml, ou None se o passo não existe."""
    bloco = re.search(r'^      - name: Implantação não publica porta.*?(?=^      - |\Z)', ci, re.M | re.S)
    return bloco.group(0) if bloco else None


def _verifica_passo(ci):
    passo = _passo_de_portas(ci)
    assert passo is not None, 'passo de portas ausente no ci.yml'
    assert 'compose.yaml -f compose.implantacao.yaml config' in passo, 'passo não roda config com os dois arquivos'
    assert 'select(.value.ports)' in passo, 'passo não confere ports de cada serviço'
    assert 'test -z "$publicadas"' in passo, 'passo não falha quando acha porta publicada'


def _publicados(servicos):
    """Nomes dos serviços com `ports` no config expandido."""
    return [nome for nome, servico in servicos.items() if servico.get('ports')]


def test_ci_tem_o_passo_de_portas_com_os_dois_arquivos():
    _verifica_passo(CI)


def _passo_presente():
    passo = _passo_de_portas(CI)
    assert passo is not None, 'pré-condição: o passo de portas precisa existir no ci.yml para a mutação'
    return passo


def test_passo_sem_o_comando_falha():
    # Caso negativo: sem o passo, nada no CI barra porta publicada na implantação.
    with pytest.raises(AssertionError, match='ausente'):
        _verifica_passo(CI.replace(_passo_presente(), ''))


def test_passo_que_nao_confere_portas_falha():
    passo = _passo_presente()
    with pytest.raises(AssertionError, match='não confere ports'):
        _verifica_passo(CI.replace(passo, passo.replace('select(.value.ports)', 'select(false)')))


def test_passo_sem_o_arquivo_de_implantacao_falha():
    # Caso negativo: `config` só com o compose de dev não vê o que a implantação publica.
    passo = _passo_presente()
    mutado = passo.replace('compose.yaml -f compose.implantacao.yaml config', 'compose.yaml config')
    with pytest.raises(AssertionError, match='dois arquivos'):
        _verifica_passo(CI.replace(passo, mutado))


def test_config_da_implantacao_nao_publica_porta_em_nenhum_servico():
    rc, saida, erro = _config(IMPLANTACAO)
    assert rc == 0, erro
    assert _publicados(json.loads(saida)['services']) == []
    assert '"published"' not in saida


def test_detector_acha_servico_com_porta_publicada():
    # Caso negativo do detector: um serviço com `ports` tem que aparecer na lista.
    servicos = {'app_azul': {'ports': [{'published': '8000', 'target': 8000}]}, 'banco': {}}
    assert _publicados(servicos) == ['app_azul']
