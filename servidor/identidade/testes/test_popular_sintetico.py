"""Comando `popular_sintetico` (R20; T5.1): o ambiente de navegador nasce com dado inventado e acessos distintos."""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from identidade import login
from identidade.models import Pessoa
from permissao.convite import convites_da_pessoa
from territorio.listagem import fazendas_autorizadas
from territorio.models import Empresa, Fazenda, SubArea


@pytest.fixture
def dados(db, monkeypatch):
    monkeypatch.setenv('PHATI_AMBIENTE_TESTE', '1')
    saida = StringIO()
    call_command('popular_sintetico', stdout=saida)
    return json.loads(saida.getvalue())


def _pessoa(dados, cpf):
    return login.autenticar(cpf, dados['senha'])


def test_pessoas_com_senha_definida_entram_sem_troca_pendente(dados):
    cpfs = [dados[papel]['cpf'] for papel in ('plataforma', 'administradora_a', 'administrador_b', 'sem_acesso')]
    cpfs += [turma['usuaria']['cpf'] for turma in dados['turmas'].values()]
    pessoas = [_pessoa(dados, cpf) for cpf in cpfs]
    entraram = [pessoa for pessoa in pessoas if pessoa is not None]
    assert len(entraram) == len(cpfs)
    assert not any(pessoa.deve_trocar_senha for pessoa in entraram)


def test_pessoa_de_troca_entra_so_com_a_senha_temporaria_e_deve_trocar(dados):
    for turma in dados['turmas'].values():
        pessoa = login.autenticar(turma['troca']['cpf'], turma['troca']['senha_temporaria'])
        assert pessoa is not None
        assert pessoa.deve_trocar_senha
        assert _pessoa(dados, turma['troca']['cpf']) is None


def test_cada_turma_tem_pessoas_proprias(dados):
    cpfs = [cpf for turma in dados['turmas'].values() for cpf in (turma['usuaria']['cpf'], turma['troca']['cpf'])]
    assert len(set(cpfs)) == len(cpfs)
    assert len(cpfs) == 4
    assert Pessoa.objects.count() == 4 + len(cpfs)


def test_usuaria_ve_so_a_fazenda_a1_e_tem_dois_convites_pendentes(dados):
    for turma in dados['turmas'].values():
        usuaria = _pessoa(dados, turma['usuaria']['cpf'])
        assert [fazenda.pk for fazenda in fazendas_autorizadas(usuaria)] == [dados['fazendas_a'][0]]
        assert len(convites_da_pessoa(usuaria)) == 2


def test_cpf_inexistente_e_valido_e_de_ninguem(dados):
    assert _pessoa(dados, dados['inexistente']['cpf']) is None
    assert dados['inexistente']['cpf'] not in {dados[p]['cpf'] for p in ('plataforma', 'administradora_a', 'administrador_b', 'sem_acesso')}


def test_pessoa_sem_acesso_nao_ve_fazenda_nem_convite(dados):
    pessoa = _pessoa(dados, dados['sem_acesso']['cpf'])
    assert list(fazendas_autorizadas(pessoa)) == []
    assert convites_da_pessoa(pessoa) == []


def test_territorio_criado_tem_duas_empresas_quatro_fazendas_e_arvore_de_tres_niveis(dados):
    assert Empresa.objects.count() == 2
    assert Fazenda.objects.count() == 4
    assert sorted(SubArea.objects.values_list('nivel', flat=True)) == [1, 2, 3]


def test_sem_a_variavel_de_ambiente_de_teste_recusa_e_nada_e_criado(db, monkeypatch):
    monkeypatch.delenv('PHATI_AMBIENTE_TESTE', raising=False)
    saida = StringIO()
    with pytest.raises(CommandError, match='so_em_ambiente_de_teste'):
        call_command('popular_sintetico', stdout=saida)
    assert Pessoa.objects.count() == 0


def test_segunda_execucao_recusa_com_ja_populado(dados):
    saida = StringIO()
    with pytest.raises(CommandError, match='ja_populado'):
        call_command('popular_sintetico', stdout=saida)
