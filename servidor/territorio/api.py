"""Rotas territoriais da API: empresas, fazendas e sub-áreas (R7, R14, R17; plan.md §API e painel).

Toda rota abre `com_permissao` por `exige_permissao`, que carrega o alvo dentro do bloco (sob a RLS o alvo fora do
escopo nem existe e a rota responde 404) e devolve dado já materializado: o ninja serializa depois que o bloco fecha.
"""

from ninja import Router, Schema

from permissao.pode import exige_permissao
from territorio import cadastro, listagem
from territorio.models import Empresa, Fazenda, SubArea

roteador = Router(tags=['territorio'])


class EntradaEmpresa(Schema):
    nome: str
    nome_administrador: str
    email_administrador: str
    cpf_administrador: str


class SaidaEmpresa(Schema):
    id: int
    nome: str
    administrador_id: int
    senha_temporaria: str  # mostrada uma vez a quem criou (R4); só o hash fica no banco


class EntradaNome(Schema):
    nome: str


class EntradaSubArea(Schema):
    nome: str
    pai_id: int | None = None


class SaidaFazenda(Schema):
    id: int
    nome: str
    empresa_id: int


class SaidaSubArea(Schema):
    id: int
    nome: str
    nivel: int
    fazenda_id: int


def _empresa(request, empresa_id, **_):
    return Empresa.objects.get(pk=empresa_id)


def _fazenda(request, fazenda_id, **_):
    return Fazenda.objects.get(pk=fazenda_id)


@roteador.post('empresas', url_name='empresas_criar', response={201: SaidaEmpresa})
@exige_permissao('criar_empresa')
def criar_empresa(request, dados: EntradaEmpresa):
    empresa, administrador, temporaria = cadastro.criar_empresa(
        request.user, dados.nome, dados.nome_administrador, dados.email_administrador, dados.cpf_administrador
    )
    return 201, {'id': empresa.pk, 'nome': empresa.nome, 'administrador_id': administrador.pk, 'senha_temporaria': temporaria}


@roteador.post('empresas/{empresa_id}/fazendas', url_name='fazendas_criar', response={201: SaidaFazenda})
@exige_permissao('criar_fazenda', _empresa)
def criar_fazenda(request, empresa_id: int, dados: EntradaNome):
    fazenda = cadastro.criar_fazenda(request.user, _empresa(request, empresa_id), dados.nome)
    return 201, {'id': fazenda.pk, 'nome': fazenda.nome, 'empresa_id': fazenda.empresa_id}


@roteador.get('fazendas', url_name='fazendas_listar', response=list[SaidaFazenda])
@exige_permissao('ver', listagem=True)
def listar_fazendas(request):
    return [{'id': f.pk, 'nome': f.nome, 'empresa_id': f.empresa_id} for f in listagem.fazendas_autorizadas(request.user)]


@roteador.post('fazendas/{fazenda_id}/sub-areas', url_name='sub_areas_criar', response={201: SaidaSubArea})
@exige_permissao('criar_sub_area', _fazenda)
def criar_sub_area(request, fazenda_id: int, dados: EntradaSubArea):
    pai = SubArea.objects.get(pk=dados.pai_id) if dados.pai_id is not None else None
    sub_area = cadastro.criar_sub_area(request.user, _fazenda(request, fazenda_id), dados.nome, pai)
    return 201, {'id': sub_area.pk, 'nome': sub_area.nome, 'nivel': sub_area.nivel, 'fazenda_id': sub_area.fazenda_id}
