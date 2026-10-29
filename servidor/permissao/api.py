"""Rotas de permissão da API: pessoas, concessões, redefinição de senha por Administrador, cargos e catálogo (R9, R10, R17).

Toda rota abre `com_permissao` por `exige_permissao`. A tabela `pessoa` fica fora da RLS (o login precisa lê-la antes
de haver identidade), então a única proteção da lista de pessoas é o filtro explícito de `pessoas_do_escopo`.
"""

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import validate_email
from django.db.models import Q
from django.utils import timezone
from ninja import Field, Router, Schema
from pydantic import AwareDatetime, field_validator, model_validator

from identidade import cpf as modulo_cpf
from identidade import redefinicao
from identidade.models import Pessoa
from permissao import delegacao
from permissao.models import Cargo, CategoriaDado, Concessao, Permissao, concessoes_ativas
from permissao.pode import age_em_algum_escopo, escopos_da_acao, exige_permissao, pode
from territorio.models import Empresa, Fazenda, SubArea

roteador = Router(tags=['permissao'])


class EntradaEscopo(Schema):
    """Exatamente um dos três: a concessão vale para a empresa inteira, uma fazenda ou uma sub-área."""

    empresa_id: int | None = None
    fazenda_id: int | None = None
    sub_area_id: int | None = None

    @model_validator(mode='after')
    def um_so(self):
        if sum(valor is not None for valor in (self.empresa_id, self.fazenda_id, self.sub_area_id)) != 1:
            raise ValueError('escopo_invalido')
        return self


class EntradaConcessao(Schema):
    cargo_id: int
    escopo: EntradaEscopo
    categoria_ids: list[int] = Field(default_factory=list, max_length=100)
    inicio: AwareDatetime | None = None
    fim: AwareDatetime | None = None

    @model_validator(mode='after')
    def periodo_valido(self):
        # O banco recusa `fim <= inicio` com erro de integridade; sem isto a entrada ruim virava 500.
        if self.fim is not None and self.fim <= (self.inicio or timezone.now()):
            raise ValueError('periodo_invalido')
        return self


class EntradaConvite(EntradaConcessao):
    nome: str = Field(max_length=200)
    email: str = Field(max_length=254)
    cpf: str

    @field_validator('email')
    @classmethod
    def email_valido(cls, valor):
        # Endereço malformado chegaria ao `on_commit` depois de a pessoa gravada (mesmo achado de `EntradaEmpresa`).
        try:
            validate_email(valor)
        except ValidationError as erro:
            raise ValueError('email_invalido') from erro
        return valor


class SaidaPessoa(Schema):
    id: int
    nome: str
    email: str
    empresa_origem_id: int | None
    deve_trocar_senha: bool


class SaidaConvite(Schema):
    id: int
    concessao_id: int
    senha_temporaria: str  # mostrada uma vez a quem convidou (R4); só o hash fica no banco


class SaidaConcessao(Schema):
    id: int
    pessoa_id: int
    cargo_id: int
    empresa_id: int
    fazenda_id: int | None
    sub_area_id: int | None
    inicio: AwareDatetime
    fim: AwareDatetime | None


class SaidaCargo(Schema):
    id: int
    empresa_id: int
    nome: str
    base: str
    permissoes: list[str]


class SaidaPermissao(Schema):
    codigo: str
    descricao: str
    delegavel: bool


def _escopo(escopo):
    if escopo.sub_area_id is not None:
        return SubArea.objects.get(pk=escopo.sub_area_id)
    if escopo.fazenda_id is not None:
        return Fazenda.objects.get(pk=escopo.fazenda_id)
    return Empresa.objects.get(pk=escopo.empresa_id)


def escopo_da_concessao(concessao):
    if concessao.sub_area_id is not None:
        return SubArea.objects.get(pk=concessao.sub_area_id)
    if concessao.fazenda_id is not None:
        return Fazenda.objects.get(pk=concessao.fazenda_id)
    return Empresa.objects.get(pk=concessao.empresa_id)


def _alvo_do_corpo(*_, dados, **__):
    return _escopo(dados.escopo)


def _alvo_da_revogacao(*_, pessoa_id, concessao_id, **__):
    return escopo_da_concessao(Concessao.objects.get(pk=concessao_id, pessoa_id=pessoa_id))


def _alvo_da_redefinicao(*_, pessoa_id, **__):
    """Quem não enxerga nenhuma empresa da pessoa recebe 404, igual a pessoa inexistente."""
    empresa = redefinicao.empresa_de_atuacao(Pessoa.objects.get(pk=pessoa_id))
    if empresa is None:
        raise ObjectDoesNotExist
    return empresa


def _empresa_do(escopo):
    return escopo.pk if isinstance(escopo, Empresa) else escopo.empresa_id


def _categorias(dados, escopo):
    pedidas = set(dados.categoria_ids)
    achadas = list(CategoriaDado.objects.filter(pk__in=pedidas, empresa_id=_empresa_do(escopo)))
    if len(achadas) != len(pedidas):
        raise ValidationError('Categoria inexistente na empresa.', code='categoria_invalida')
    return achadas


def _concessao_saida(concessao):
    return {
        'id': concessao.pk, 'pessoa_id': concessao.pessoa_id, 'cargo_id': concessao.cargo_id,
        'empresa_id': concessao.empresa_id, 'fazenda_id': concessao.fazenda_id,
        'sub_area_id': concessao.sub_area_id, 'inicio': concessao.inicio, 'fim': concessao.fim,
    }


def pessoas_do_escopo(quem):
    escopos = escopos_da_acao(quem, 'convidar_pessoa')
    if escopos.plataforma:
        return Pessoa.objects.order_by('pk')
    fazendas = escopos.fazendas | escopos.fazendas_das_sub_areas
    candidatas = concessoes_ativas().filter(Q(empresa_id__in=escopos.empresas) | Q(fazenda_id__in=fazendas))
    # Sub-área tem granularidade só em `pode()`: a concessão entra se `quem` age no escopo dela.
    ids = {c.pessoa_id for c in candidatas if pode(quem, 'convidar_pessoa', escopo_da_concessao(c))}
    return Pessoa.objects.filter(Q(pk__in=ids) | Q(empresa_origem_id__in=escopos.empresas)).order_by('pk')


@roteador.get('pessoas', url_name='pessoas_listar', response=list[SaidaPessoa])
@exige_permissao('convidar_pessoa', listagem=True)
def listar_pessoas(request):
    return [
        {'id': p.pk, 'nome': p.nome, 'email': p.email, 'empresa_origem_id': p.empresa_origem_id,
         'deve_trocar_senha': p.deve_trocar_senha}
        for p in pessoas_do_escopo(request.user)
    ]


@roteador.post('pessoas', url_name='pessoas_convidar', response={201: SaidaConvite})
@exige_permissao('convidar_pessoa', _alvo_do_corpo)
def convidar_pessoa(request, dados: EntradaConvite):
    escopo = _escopo(dados.escopo)
    pessoa, temporaria = delegacao.convidar(
        request.user, dados.nome, dados.email, dados.cpf, Cargo.objects.get(pk=dados.cargo_id), escopo,
        _categorias(dados, escopo), dados.inicio, dados.fim,
    )
    concessao = Concessao.objects.filter(pessoa=pessoa).get()
    return 201, {'id': pessoa.pk, 'concessao_id': concessao.pk, 'senha_temporaria': temporaria}


@roteador.post('pessoas/{pessoa_id}/concessoes', url_name='concessoes_criar', response={201: SaidaConcessao})
@exige_permissao('convidar_pessoa', _alvo_do_corpo)
def conceder(request, pessoa_id: int, dados: EntradaConcessao):
    escopo = _escopo(dados.escopo)
    concessao = delegacao.conceder(
        request.user, Pessoa.objects.get(pk=pessoa_id), Cargo.objects.get(pk=dados.cargo_id), escopo,
        _categorias(dados, escopo), dados.inicio, dados.fim,
    )
    return 201, _concessao_saida(concessao)


@roteador.delete('pessoas/{pessoa_id}/concessoes/{concessao_id}', url_name='concessoes_revogar', response={204: None})
@exige_permissao('revogar_acesso', _alvo_da_revogacao)
def revogar(request, pessoa_id: int, concessao_id: int):
    delegacao.revogar_concessao(request.user, Concessao.objects.get(pk=concessao_id, pessoa_id=pessoa_id))
    return 204, None


@roteador.post('pessoas/{pessoa_id}/redefinir-senha', url_name='pessoas_redefinir_senha', response={204: None})
@exige_permissao('redefinir_senha', _alvo_da_redefinicao)
def redefinir_senha(request, pessoa_id: int):
    alvo = Pessoa.objects.get(pk=pessoa_id)
    if not redefinicao.pode_iniciar_redefinicao(request.user, alvo):
        raise ObjectDoesNotExist
    redefinicao.pedir_redefinicao(modulo_cpf.decifrar(alvo.cpf_cifrado), solicitante=request.user)
    return 204, None


@roteador.get('cargos', url_name='cargos_listar', response=list[SaidaCargo])
@exige_permissao('convidar_pessoa', listagem=True)
def listar_cargos(request):
    escopos = escopos_da_acao(request.user, 'convidar_pessoa')
    cargos = Cargo.objects.prefetch_related('permissoes').order_by('pk')
    if not escopos.plataforma:
        cargos = cargos.filter(empresa_id__in=escopos.empresas | escopos.empresas_das_fazendas)
    return [
        {'id': c.pk, 'empresa_id': c.empresa_id, 'nome': c.nome, 'base': c.base,
         'permissoes': sorted(p.codigo for p in c.permissoes.all())}
        for c in cargos
    ]


@roteador.get('permissoes', url_name='permissoes_listar', response=list[SaidaPermissao])
@exige_permissao('convidar_pessoa', listagem=True)
def listar_permissoes(request):
    # O catálogo é global e não é dado de empresa; só quem age em algum escopo precisa dele para montar um cargo.
    if not age_em_algum_escopo(request.user, 'convidar_pessoa'):
        return []
    return [
        {'codigo': p.codigo, 'descricao': p.descricao, 'delegavel': p.delegavel}
        for p in Permissao.objects.order_by('codigo')
    ]
