"""Popula o ambiente de teste de navegador com dado inventado (R20; T5.1). Nunca roda em ambiente real.

Cria duas empresas, fazendas com sub-áreas, pessoas com CPF sintético válido e convites pendentes. Escreve na saída
padrão (JSON) os CPFs, a senha e os ids que os testes de navegador usam. A senha é sorteada a cada execução. Roda com
as credenciais do dono do banco (serviço `migracao` do compose): o papel `app` não passa pela RLS de criação de empresa.
"""

import json
import os
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from catalogo.envios import criar_envio
from catalogo.models import Camada, EnvioCamada, Estudo, Feicao, Tema, VersaoCamada
from comum.sintetico import cpf_sintetico
from django.contrib.gis.geos import GEOSGeometry
from identidade import senha
from identidade.models import Pessoa
from pacote.sintetico import instalar_referencia
from permissao import convite, delegacao
from permissao.models import Cargo
from territorio import cadastro
from territorio.models import Empresa

NOME_EMPRESA_A = 'Empresa Inventada A'
# Cada projeto do Playwright (tamanho de tela) tem as próprias pessoas: os testes aceitam convite, trocam senha e
# erram a senha, e o segundo projeto não pode encontrar o estado que o primeiro deixou.
TURMAS = ('computador', 'celular')


def _pessoa(nome, sequencia, credencial, administrador_plataforma=False):
    pessoa = Pessoa.objects.criar(nome, f'pessoa{sequencia}@exemplo.test', cpf_sintetico(sequencia))
    if administrador_plataforma:
        pessoa.administrador_plataforma = True
        pessoa.save(update_fields=['administrador_plataforma'])
    senha.definir_senha(pessoa, credencial)
    return pessoa


def _empresa(plataforma, nome, nome_administrador, sequencia, credencial):
    empresa, administrador, _ = cadastro.criar_empresa(
        plataforma, nome, nome_administrador, f'pessoa{sequencia}@exemplo.test', cpf_sintetico(sequencia)
    )
    senha.definir_senha(administrador, credencial)
    return empresa, administrador


def _turma(indice, credencial, administrador_a, administrador_b, empresa_a, empresa_b, fazendas_a):
    base = 10 + indice * 3
    usuaria = _pessoa(f'Usuaria Gama {TURMAS[indice]}', base, credencial)
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
    troca = Pessoa.objects.criar(f'Pessoa Troca {TURMAS[indice]}', f'pessoa{base + 1}@exemplo.test', cpf_sintetico(base + 1))
    # Conta que só serve para errar a senha: a falha de login não pode bloquear as pessoas dos outros testes.
    _pessoa(f'Pessoa Errada {TURMAS[indice]}', base + 2, credencial)
    return {
        'usuaria': {'cpf': cpf_sintetico(base)},
        'troca': {'cpf': cpf_sintetico(base + 1), 'senha_temporaria': senha.emitir_senha_temporaria(troca)},
        'errada': {'cpf': cpf_sintetico(base + 2)},
    }


def _envio_vencido(administrador, fazenda):
    """Envio sintético já vencido na fazenda A1: a tela de camadas mostra o aviso de expiração sem alteração posterior no banco."""
    conteudo = json.dumps({'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'valor': 1}, 'geometry': {'type': 'Point', 'coordinates': [-48.3, -10.7]}},
    ]}).encode()
    envio = criar_envio(administrador, fazenda, conteudo)
    EnvioCamada.objects.filter(pk=envio.pk).update(expira_em=timezone.now() - timedelta(minutes=1))
    return str(envio.publico_id)


def _estudo(empresa, fazenda):
    """Estudo sintético na fazenda A3: a tela de publicação mostra o formulário. A A1 fica sem estudo de propósito."""
    tema = Tema.objects.create(empresa=empresa, nome='Tema sintético')
    return Estudo.objects.create(empresa=empresa, fazenda=fazenda, tema=tema, nome='Estudo sintético')


# Divisão sintética da A3 (008 R7): dois nós adjacentes. As coordenadas ficam aqui e são exportadas em `dados.json`, para o
# Playwright montar o GeoJSON sem número solto no spec. Os anéis são WGS 84 (SRID 4674 é o do banco, mesma origem).
NOS_DA_A3 = (
    ('Talhão A3-1', ((-48.31, -10.71), (-48.30, -10.71), (-48.30, -10.70), (-48.31, -10.70), (-48.31, -10.71))),
    ('Talhão A3-2', ((-48.30, -10.71), (-48.29, -10.71), (-48.29, -10.70), (-48.30, -10.70), (-48.30, -10.71))),
)
# Feição que cruza os dois nós (maior parte no nó 1: sugestão pela maior área) e feição fora de todo nó.
FEICAO_QUE_CRUZA = ((-48.3075, -10.7050), (-48.2975, -10.7050), (-48.2975, -10.6950), (-48.3075, -10.6950), (-48.3075, -10.7050))
FEICAO_FORA_DE_NOS = ((-48.50, -10.90), (-48.49, -10.90), (-48.49, -10.89), (-48.50, -10.89), (-48.50, -10.90))
# Feição em empate: metade sobre cada nó, mesma área (R7: sem sugestão, a pessoa escolhe).
FEICAO_EM_EMPATE = ((-48.305, -10.705), (-48.295, -10.705), (-48.295, -10.695), (-48.305, -10.695), (-48.305, -10.705))


def _divisao_da_a3(administrador, empresa, fazenda, estudo):
    """Divisão da A3: camada com `coluna_no` (marca a divisão, D119), uma versão e as feições dos dois nós. Nó criado por
    `cadastro`; a feição de cada nó leva o nó (`sub_area`), e a divisão é a união deles (`contornos_da_divisao`)."""
    nos = []
    for nome, anel in NOS_DA_A3:
        no = cadastro.criar_sub_area(administrador, fazenda, nome)
        nos.append((no, GEOSGeometry('POLYGON((%s))' % ', '.join(f'{x} {y}' for x, y in anel), srid=4674)))
    camada = Camada.objects.create(estudo=estudo, empresa=empresa, fazenda=fazenda, nome='Divisão sintética', coluna_no='no')
    versao = VersaoCamada.objects.create(camada=camada, empresa=empresa, fazenda=fazenda, numero=1,
                                         sistema_original='WGS 84', origem='Divisão sintética', enviada_por=administrador)
    for no, geometria in nos:
        Feicao.objects.create(versao=versao, empresa=empresa, fazenda=fazenda, sub_area=no, geometria=geometria, valores={'no': no.nome})
    return [no.pk for no, _ in nos]


def popular():
    """Devolve o dicionário que os testes de navegador leem.

    Recusa quando `PHATI_AMBIENTE` não é `local`, `homologacao` ou `teste` (ausente vale `producao`): ele cria logins com
    CPF conhecido, e a checagem do nome da empresa sozinha não distingue um banco descartável de um real (achado do Qodo,
    PR #22). Um conceito de ambiente só (004 R21). Segunda trava, por conteúdo (achado do Qodo, PR #35): só semeia banco
    sem pessoa nem empresa, porque um banco real rotulado `homologacao` por engano sempre tem dado. Levanta
    `CommandError` se já foi populado.
    """
    if os.environ.get('PHATI_AMBIENTE', 'producao') not in settings.AMBIENTES_DE_TESTE:
        raise CommandError('so_em_ambiente_de_teste')
    if Empresa.objects.filter(nome=NOME_EMPRESA_A).exists():
        raise CommandError('ja_populado')
    if Pessoa.objects.exists() or Empresa.objects.exists():
        raise CommandError('banco_nao_vazio')
    credencial = secrets.token_urlsafe(18)
    with transaction.atomic():
        plataforma = _pessoa('Plataforma Inventada', 1, credencial, administrador_plataforma=True)
        empresa_a, administrador_a = _empresa(plataforma, NOME_EMPRESA_A, 'Administradora Alfa', 2, credencial)
        empresa_b, administrador_b = _empresa(plataforma, 'Empresa Inventada B', 'Administrador Beta', 3, credencial)
        fazendas_a = [cadastro.criar_fazenda(administrador_a, empresa_a, f'Fazenda Inventada A{n}') for n in (1, 2, 3)]
        fazenda_b = cadastro.criar_fazenda(administrador_b, empresa_b, 'Fazenda Inventada B1')
        envio_vencido = _envio_vencido(administrador_a, fazendas_a[0])
        estudo_a3 = _estudo(empresa_a, fazendas_a[2])  # estudo na A3 para a publicação (008 T4.2); a A1 segue sem estudo (estado vazio)
        nos_a3 = _divisao_da_a3(administrador_a, empresa_a, fazendas_a[2], estudo_a3)
        instalar_referencia(fazendas_a[1])  # pacote de referência só na A2: as fazendas A1 e A3 seguem sem pacote (testes do mapa da 004 e da 004b)
        raiz = cadastro.criar_sub_area(administrador_a, fazendas_a[0], 'Talhao 1')
        filha = cadastro.criar_sub_area(administrador_a, fazendas_a[0], 'Gleba 1', raiz)
        cadastro.criar_sub_area(administrador_a, fazendas_a[0], 'Lote 1', filha)
        _pessoa('Pessoa Delta', 5, credencial)  # sem nenhum acesso nem convite
        turmas = {
            nome: _turma(i, credencial, administrador_a, administrador_b, empresa_a, empresa_b, fazendas_a)
            for i, nome in enumerate(TURMAS)
        }
    return {
        'senha': credencial,
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
        'camadas': {
            'envio_vencido': envio_vencido,  # tela de camadas (008 T4.2): aviso de envio expirado sem mexer no banco depois
            'nos_a3': nos_a3,
            'cruza': [list(p) for p in FEICAO_QUE_CRUZA],
            'fora': [list(p) for p in FEICAO_FORA_DE_NOS],
            'empate': [list(p) for p in FEICAO_EM_EMPATE],
        },
    }


class Command(BaseCommand):
    help = 'Popula o ambiente de teste de navegador com dado inventado. Nunca use em ambiente real.'

    def handle(self, *args, **opcoes):
        self.stdout.write(json.dumps(popular(), indent=2))
