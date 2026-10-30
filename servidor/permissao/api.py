"""Rotas de permissão da API: pessoas, concessões, redefinição de senha por Administrador, cargos e catálogo (R9, R10, R17).

Toda rota abre `com_permissao` por `exige_permissao`. A tabela `pessoa` fica fora da RLS (o login precisa lê-la antes
de haver identidade), então a única proteção da lista de pessoas é o filtro explícito de `pessoas_do_escopo`.
"""

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import validate_email
from django.db.models import Q
from django.utils import timezone
from ninja import Field, Query, Router, Schema
from pydantic import AwareDatetime, field_validator, model_validator

from identidade import cpf as modulo_cpf
from identidade import redefinicao
from identidade.models import Pessoa
from permissao import convite, delegacao
from permissao.models import Cargo, CategoriaDado, Concessao, Convite, Permissao, concessoes_ativas
from permissao.pode import age_em_algum_escopo, escopos_da_acao, exige_permissao, filtro_do_escopo, pode, unir_escopos
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


class ParametrosDaLista(Schema):
    limite: int = Field(30, ge=1, le=100)
    depois: int = Field(0, ge=0)


class SaidaPessoa(Schema):
    id: int
    nome: str
    email: str
    empresa_origem_id: int | None
    deve_trocar_senha: bool


class SaidaConvite(Schema):
    """CPF novo: a pessoa, a concessão e a senha temporária (mostrada uma vez, R4). CPF que já existe: só `pendente`,
    sem identificador nem dado da pessoa (R24)."""

    pendente: bool
    id: int | None = None
    concessao_id: int | None = None
    senha_temporaria: str | None = None


class SaidaConviteEnviado(Schema):
    """Sem dado da pessoa convidada: quem convida não vê quem já existe (R24)."""

    id: int
    cargo_nome: str
    empresa_nome: str
    criado_em: AwareDatetime
    expira_em: AwareDatetime
    vencido: bool


class SaidaConviteRecebido(Schema):
    id: int
    empresa_nome: str
    cargo_nome: str
    convidado_por_nome: str
    inicio: AwareDatetime | None
    fim: AwareDatetime | None
    expira_em: AwareDatetime


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


def _alvo_do_convite_enviado(requisicao, *_, convite_id, **__):
    return escopo_da_concessao(Convite.objects.get(pk=convite_id, convidado_por=requisicao.user))


def _alvo_da_revogacao(*_, pessoa_id, concessao_id, **__):
    return escopo_da_concessao(Concessao.objects.get(pk=concessao_id, pessoa_id=pessoa_id))


def _alvo_da_redefinicao(requisicao, *_, pessoa_id, **__):
    """Quem não enxerga nenhuma empresa da pessoa recebe 404, igual a pessoa inexistente. Conta da plataforma não
    tem empresa: só a plataforma age sobre ela (`pode()` sem alvo), o resto recebe 404 (Greptile, PR #16)."""
    empresa = redefinicao.empresa_de_atuacao(Pessoa.objects.get(pk=pessoa_id), requisicao.user)
    if empresa is None and not requisicao.user.administrador_plataforma:
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


def pessoas_do_escopo(quem, acoes=('convidar_pessoa',)):
    escopos = unir_escopos(quem, *acoes)
    if escopos.plataforma:
        return Pessoa.objects.order_by('pk')
    # Um filtro só, sem `pode()` por concessão (era uma consulta ou duas por linha; Qodo, PR #16).
    ids = concessoes_ativas().filter(filtro_do_escopo(escopos)).values_list('pessoa_id', flat=True)
    return Pessoa.objects.filter(Q(pk__in=ids) | Q(empresa_origem_id__in=escopos.empresas)).order_by('pk')


@roteador.get('pessoas', url_name='pessoas_listar', response=list[SaidaPessoa])
@exige_permissao('convidar_pessoa', listagem=True)
def listar_pessoas(request, filtros: Query[ParametrosDaLista]):
    # Cursor por id (`depois` = último id recebido): sem contagem e estável com a lista mudando. Padrão de mercado
    # (pesquisa de 2026-10-29): GitHub 30 por página com teto de 100; Stripe 10 com teto de 100, também por cursor.
    return [
        {'id': p.pk, 'nome': p.nome, 'email': p.email, 'empresa_origem_id': p.empresa_origem_id,
         'deve_trocar_senha': p.deve_trocar_senha}
        for p in pessoas_do_escopo(request.user).filter(pk__gt=filtros.depois)[: filtros.limite]
    ]


@roteador.post('pessoas', url_name='pessoas_convidar', response={201: SaidaConvite})
@exige_permissao('convidar_pessoa', _alvo_do_corpo)
def convidar_pessoa(request, dados: EntradaConvite):
    escopo = _escopo(dados.escopo)
    pessoa, temporaria = convite.convidar_por_cpf(
        request.user, dados.nome, dados.email, dados.cpf, Cargo.objects.get(pk=dados.cargo_id), escopo,
        _categorias(dados, escopo), dados.inicio, dados.fim,
    )
    if pessoa is None:  # CPF que já existe: convite pendente, nada da pessoa na resposta (R24)
        return 201, {'pendente': True}
    concessao = Concessao.objects.filter(pessoa=pessoa).get()
    return 201, {'pendente': False, 'id': pessoa.pk, 'concessao_id': concessao.pk, 'senha_temporaria': temporaria}


@roteador.post('pessoas/{pessoa_id}/concessoes', url_name='concessoes_criar', response={201: SaidaConcessao})
@exige_permissao('convidar_pessoa', _alvo_do_corpo)
def conceder(request, pessoa_id: int, dados: EntradaConcessao):
    escopo = _escopo(dados.escopo)
    # `pessoa` não tem RLS e o id é sequencial: só quem está no alcance de quem concede. Fora dele, 404 igual ao de
    # id inexistente, senão a rota enumera pessoas de outras empresas e as puxa para esta (Qodo, PR #16).
    pessoa = pessoas_do_escopo(request.user).get(pk=pessoa_id)
    concessao = delegacao.conceder(
        request.user, pessoa, Cargo.objects.get(pk=dados.cargo_id), escopo,
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


# Convites recebidos (R24): rotas da própria pessoa, sem `exige_permissao`. A permissão de quem convidou é refeita
# dentro de `convite.aceitar`, e `convites/{id}` só alcança convite dirigido a quem chama (outro id, 404).
@roteador.get('convites', url_name='convites_listar', response=list[SaidaConviteRecebido])
def listar_convites(request):
    return [
        {'id': c.pk, 'empresa_nome': c.empresa_nome, 'cargo_nome': c.cargo_nome,
         'convidado_por_nome': Pessoa.objects.get(pk=c.convidado_por_id).nome, 'inicio': c.inicio, 'fim': c.fim,
         'expira_em': c.expira_em}
        for c in convite.convites_da_pessoa(request.user)
    ]


@roteador.post('convites/{convite_id}/aceitar', url_name='convites_aceitar', response={204: None})
def aceitar_convite(request, convite_id: int):
    convite.aceitar(request.user, convite_id)
    return 204, None


@roteador.post('convites/{convite_id}/recusar', url_name='convites_recusar', response={204: None})
def recusar_convite(request, convite_id: int):
    convite.recusar(request.user, convite_id)
    return 204, None


# Convites de quem convidou: listar, cancelar e reenviar (padrão de GitHub e Entra). Só os próprios; a resposta não
# carrega a pessoa convidada.
@roteador.get('convites-enviados', url_name='convites_enviados_listar', response=list[SaidaConviteEnviado])
@exige_permissao('convidar_pessoa', listagem=True)
def listar_convites_enviados(request):
    return [
        {'id': c.pk, 'cargo_nome': c.cargo_nome, 'empresa_nome': c.empresa_nome, 'criado_em': c.criado_em,
         'expira_em': c.expira_em, 'vencido': c.expira_em <= timezone.now()}
        for c in convite.convites_enviados(request.user)
    ]


@roteador.delete('convites-enviados/{convite_id}', url_name='convites_enviados_cancelar', response={204: None})
@exige_permissao('convidar_pessoa', _alvo_do_convite_enviado)
def cancelar_convite_enviado(request, convite_id: int):
    convite.cancelar(request.user, convite_id)
    return 204, None


@roteador.post('convites-enviados/{convite_id}/reenviar', url_name='convites_enviados_reenviar', response={204: None})
@exige_permissao('convidar_pessoa', _alvo_do_convite_enviado)
def reenviar_convite_enviado(request, convite_id: int):
    convite.reenviar(request.user, convite_id)
    return 204, None
