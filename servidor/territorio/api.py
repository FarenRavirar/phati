"""Rotas territoriais da API: empresas, fazendas e sub-áreas (R7, R14, R17; plan.md §API e painel).

Toda rota abre `com_permissao` por `exige_permissao`, que carrega o alvo dentro do bloco (sob a RLS o alvo fora do
escopo nem existe e a rota responde 404) e devolve dado já materializado: o ninja serializa depois que o bloco fecha.
"""

from typing import Literal

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from ninja import Field, Router, Schema
from pydantic import field_validator

from permissao.pode import exige_permissao
from territorio import cadastro, listagem
from territorio.models import Empresa, Fazenda, SubArea

roteador = Router(tags=['territorio'])


# Os limites são os das colunas: sem eles, nome longo chegava ao banco e dava 500 (achado do Greptile, PR #14).
class EntradaEmpresa(Schema):
    nome: str = Field(max_length=200)
    nome_administrador: str = Field(max_length=200)
    email_administrador: str = Field(max_length=254)
    cpf_administrador: str

    @field_validator('email_administrador')
    @classmethod
    def email_valido(cls, valor):
        # Endereço malformado chegaria ao `on_commit` e estouraria depois de a empresa gravada (Sourcery, PR #14).
        try:
            validate_email(valor)
        except ValidationError as erro:
            raise ValueError('email_invalido') from erro
        return valor


class SaidaEmpresa(Schema):
    id: int
    nome: str
    administrador_id: int
    senha_temporaria: str  # mostrada uma vez a quem criou (R4); só o hash fica no banco


class EntradaNome(Schema):
    nome: str = Field(max_length=200)


class EntradaSubArea(Schema):
    nome: str = Field(max_length=200)
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


class SaidaTerritorio(Schema):
    id: int
    nome: str
    arquivada: bool  # arquivada ou desarquivada pelo ato; a leitura por id segue valendo (003 R11)


# Segmento da URL → modelo e função de renomear. Uma tabela só: rota nova de território entra aqui (R28).
TIPOS = {
    'empresas': (Empresa, cadastro.renomear_empresa),
    'fazendas': (Fazenda, cadastro.renomear_fazenda),
    'sub-areas': (SubArea, cadastro.renomear_sub_area),
}
Tipo = Literal['empresas', 'fazendas', 'sub-areas']


# Os três recebem `(requisicao, **parametros_da_rota)` de `exige_permissao`; `*_` absorve a requisição, que não usam.
def _empresa(*_, empresa_id, **__):
    return Empresa.objects.get(pk=empresa_id)


def _fazenda(*_, fazenda_id, **__):
    return Fazenda.objects.get(pk=fazenda_id)


def _alvo_da_sub_area(*_, fazenda_id, dados, **__):
    # Quem recebeu `criar_sub_area` só numa sub-área cria filha dela, não raiz da fazenda: o alvo é o pai quando há
    # pai (o serviço confere que o pai é da fazenda da URL). Achado do Sourcery, PR #14.
    return SubArea.objects.get(pk=dados.pai_id) if dados.pai_id is not None else _fazenda(fazenda_id=fazenda_id)


def _alvo_do_tipo(*_, tipo, alvo_id, **__):
    return TIPOS[tipo][0].objects.get(pk=alvo_id)


def _saida(alvo):
    return {'id': alvo.pk, 'nome': alvo.nome, 'arquivada': alvo.arquivada_em is not None}


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
    fazenda = cadastro.criar_fazenda(request.user, _empresa(empresa_id=empresa_id), dados.nome)
    return 201, {'id': fazenda.pk, 'nome': fazenda.nome, 'empresa_id': fazenda.empresa_id}


@roteador.get('fazendas', url_name='fazendas_listar', response=list[SaidaFazenda])
@exige_permissao('ver', listagem=True)
def listar_fazendas(request):
    return [{'id': f.pk, 'nome': f.nome, 'empresa_id': f.empresa_id} for f in listagem.fazendas_autorizadas(request.user)]


@roteador.post('fazendas/{fazenda_id}/sub-areas', url_name='sub_areas_criar', response={201: SaidaSubArea})
@exige_permissao('criar_sub_area', _alvo_da_sub_area)
def criar_sub_area(request, fazenda_id: int, dados: EntradaSubArea):
    pai = SubArea.objects.get(pk=dados.pai_id) if dados.pai_id is not None else None
    sub_area = cadastro.criar_sub_area(request.user, _fazenda(fazenda_id=fazenda_id), dados.nome, pai)
    return 201, {'id': sub_area.pk, 'nome': sub_area.nome, 'nivel': sub_area.nivel, 'fazenda_id': sub_area.fazenda_id}


@roteador.patch('territorio/{tipo}/{alvo_id}', url_name='territorio_renomear', response=SaidaTerritorio)
@exige_permissao('renomear', _alvo_do_tipo)
def renomear(request, tipo: Tipo, alvo_id: int, dados: EntradaNome):
    return _saida(TIPOS[tipo][1](request.user, _alvo_do_tipo(tipo=tipo, alvo_id=alvo_id), dados.nome))


@roteador.post('territorio/{tipo}/{alvo_id}/arquivar', url_name='territorio_arquivar', response=SaidaTerritorio)
@exige_permissao('arquivar', _alvo_do_tipo)
def arquivar(request, tipo: Tipo, alvo_id: int):
    return _saida(cadastro.arquivar(request.user, _alvo_do_tipo(tipo=tipo, alvo_id=alvo_id)))


@roteador.post('territorio/{tipo}/{alvo_id}/desarquivar', url_name='territorio_desarquivar', response=SaidaTerritorio)
@exige_permissao('desarquivar', _alvo_do_tipo)
def desarquivar(request, tipo: Tipo, alvo_id: int):
    return _saida(cadastro.desarquivar(request.user, _alvo_do_tipo(tipo=tipo, alvo_id=alvo_id)))
