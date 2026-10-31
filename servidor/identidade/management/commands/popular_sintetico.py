"""Popula o ambiente de teste de navegador com dado inventado (R20; T5.1). Nunca roda em ambiente real.

Cria duas empresas, fazendas com sub-áreas, pessoas com CPF sintético válido e um convite pendente. Escreve na saída padrão (JSON)
os CPFs, a senha e os ids que os testes de navegador usam. Roda com as credenciais do dono do banco (serviço
`migracao` do compose): o papel `app` não passa pela RLS de criação de empresa.
"""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from comum.sintetico import cpf_sintetico
from identidade import senha
from identidade.models import Pessoa
from permissao import convite, delegacao
from permissao.models import Cargo
from territorio import cadastro
from territorio.models import Empresa

CREDENCIAL_INVENTADA = 'Navegador-Inventado-2026'
NOME_EMPRESA_A = 'Empresa Inventada A'
# Cada projeto do Playwright (tamanho de tela) tem as próprias pessoas: os testes aceitam convite e trocam senha,
# e o segundo projeto não pode encontrar o estado que o primeiro deixou.
TURMAS = ('desktop', 'celular')


def _pessoa(nome, sequencia, administrador_plataforma=False):
    pessoa = Pessoa.objects.criar(nome, f'pessoa{sequencia}@exemplo.test', cpf_sintetico(sequencia))
    if administrador_plataforma:
        pessoa.administrador_plataforma = True
        pessoa.save(update_fields=['administrador_plataforma'])
    senha.definir_senha(pessoa, CREDENCIAL_INVENTADA)
    return pessoa


def _empresa(plataforma, nome, nome_administrador, sequencia):
    empresa, administrador, _ = cadastro.criar_empresa(
        plataforma, nome, nome_administrador, f'pessoa{sequencia}@exemplo.test', cpf_sintetico(sequencia)
    )
    senha.definir_senha(administrador, CREDENCIAL_INVENTADA)
    return empresa, administrador


def _turma(indice, administrador_a, administrador_b, empresa_a, empresa_b, fazendas_a):
    base = 10 + indice * 2
    usuaria = _pessoa(f'Usuaria Gama {TURMAS[indice]}', base)
    delegacao.conceder(administrador_a, usuaria, Cargo.objects.get(empresa=empresa_a, base='usuario'), fazendas_a[0])
    # A pessoa já existe: os dois convites ficam pendentes no Início dela (a empresa B e a fazenda A2).
    convite.convidar_por_cpf(
        administrador_b, usuaria.nome, usuaria.email, cpf_sintetico(base),
        Cargo.objects.get(empresa=empresa_b, base='usuario'), empresa_b,
    )
    convite.convidar_por_cpf(
        administrador_a, usuaria.nome, usuaria.email, cpf_sintetico(base),
        Cargo.objects.get(empresa=empresa_a, base='usuario'), fazendas_a[1],
    )
    cpf_troca = cpf_sintetico(base + 1)
    troca = Pessoa.objects.criar(f'Pessoa Troca {TURMAS[indice]}', f'pessoa{base + 1}@exemplo.test', cpf_troca)
    return {'usuaria': {'cpf': cpf_sintetico(base)}, 'troca': {'cpf': cpf_troca, 'senha_temporaria': senha.emitir_senha_temporaria(troca)}}


def popular():
    """Devolve o dicionário que os testes de navegador leem. Levanta `CommandError` se o ambiente já foi populado."""
    if Empresa.objects.filter(nome=NOME_EMPRESA_A).exists():
        raise CommandError('ja_populado')
    with transaction.atomic():
        plataforma = _pessoa('Plataforma Inventada', 1, administrador_plataforma=True)
        empresa_a, administrador_a = _empresa(plataforma, NOME_EMPRESA_A, 'Administradora Alfa', 2)
        empresa_b, administrador_b = _empresa(plataforma, 'Empresa Inventada B', 'Administrador Beta', 3)
        fazendas_a = [cadastro.criar_fazenda(administrador_a, empresa_a, f'Fazenda Inventada A{n}') for n in (1, 2, 3)]
        fazenda_b = cadastro.criar_fazenda(administrador_b, empresa_b, 'Fazenda Inventada B1')
        raiz = cadastro.criar_sub_area(administrador_a, fazendas_a[0], 'Talhao 1')
        filha = cadastro.criar_sub_area(administrador_a, fazendas_a[0], 'Gleba 1', raiz)
        cadastro.criar_sub_area(administrador_a, fazendas_a[0], 'Lote 1', filha)
        _pessoa('Pessoa Delta', 5)  # sem nenhum acesso nem convite
        turmas = {nome: _turma(i, administrador_a, administrador_b, empresa_a, empresa_b, fazendas_a) for i, nome in enumerate(TURMAS)}
    return {
        'senha': CREDENCIAL_INVENTADA,
        'plataforma': {'cpf': cpf_sintetico(1)},
        'administradora_a': {'cpf': cpf_sintetico(2)},
        'administrador_b': {'cpf': cpf_sintetico(3)},
        'turmas': turmas,
        'sem_acesso': {'cpf': cpf_sintetico(5)},
        'inexistente': {'cpf': cpf_sintetico(99)},  # CPF válido que ninguém tem: falha de login sem bloquear pessoa real
        'empresa_a': empresa_a.pk,
        'empresa_b': empresa_b.pk,
        'fazendas_a': [fazenda.pk for fazenda in fazendas_a],
        'fazenda_b': fazenda_b.pk,
    }


class Command(BaseCommand):
    help = 'Popula o ambiente de teste de navegador com dado inventado. Nunca use em ambiente real.'

    def handle(self, *args, **opcoes):
        self.stdout.write(json.dumps(popular(), indent=2))
