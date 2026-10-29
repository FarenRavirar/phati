"""Decisão de acesso (R11; plan.md §Permissão — função pode()).

Nega por padrão. A permissão sai das concessões ativas da pessoa, lidas uma vez e guardadas no próprio objeto da
pessoa: o objeto vive o tempo de uma requisição (o Django carrega a pessoa de novo a cada uma), então revogação e
vencimento valem na requisição seguinte. Nada vai para a sessão. Quem mantém o mesmo objeto por mais tempo (teste,
comando) chama `esquecer()` depois de mudar concessões.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db import DEFAULT_DB_ALIAS, connection, connections, transaction
from django.utils import timezone

from permissao.contexto import fixar_contexto, fixar_identidade, ler_contexto, restaurar_contexto
from permissao.models import BASES_COM_CATEGORIA, Concessao, Permissao
from territorio.models import Empresa, Fazenda, SubArea

# Ações que só o Administrador da plataforma exerce; nenhum cargo as concede, mesmo que `cargo_permissao` as traga.
ACOES_DA_PLATAFORMA = frozenset({'criar_empresa'})
# O Administrador conta como quem tem estas, mesmo que o cargo personalizado não as liste (D043); o escopo de RLS
# delas segue a mesma regra, senão o papel `app` barraria o que `pode_conceder` autoriza.
ACOES_DE_DELEGACAO = frozenset({'convidar_pessoa', 'revogar_acesso'})
_ATRIBUTO_MEMORIA = '_memoria_do_pode'


@dataclass(frozen=True)
class Alvo:
    """Onde a ação acontece: a empresa, a fazenda (se houver) e a sub-área (se houver) com o caminho dos ancestrais."""

    empresa_id: int
    fazenda_id: int | None = None
    sub_area_id: int | None = None
    caminho: str = '/'


def alvo_de(objeto):
    """Empresa, Fazenda ou SubArea já salva → Alvo. Outra coisa (ou objeto sem `pk`) → None, e `pode()` nega.

    Passe a sub-área lida do banco: o `caminho` de uma instância recém-criada só chega depois de `refresh_from_db()`.
    """
    if getattr(objeto, 'pk', None) is None:
        return None
    if isinstance(objeto, Empresa):
        return Alvo(objeto.pk)
    if isinstance(objeto, Fazenda):
        return Alvo(objeto.empresa_id, objeto.pk)
    if isinstance(objeto, SubArea):
        return Alvo(objeto.empresa_id, objeto.fazenda_id, objeto.pk, objeto.caminho)
    return None


@dataclass(frozen=True)
class Vinculo:
    """Uma concessão ativa com o que o cargo dela permite."""

    concessao: Concessao
    base: str
    permissoes: frozenset[str]
    categorias: frozenset[int]

    def tem(self, acao):
        """O Administrador conta como quem tem todo o catálogo no escopo (D043); os demais, só o que o cargo lista."""
        return self.base == 'administrador' or acao in self.permissoes

    def cobre(self, alvo):
        """Empresa cobre tudo dela; fazenda cobre as sub-áreas; sub-área cobre os descendentes pelo `caminho`."""
        concessao = self.concessao
        if concessao.empresa_id != alvo.empresa_id:
            return False
        if concessao.fazenda_id is None:
            return True
        if concessao.fazenda_id != alvo.fazenda_id:
            return False
        if concessao.sub_area_id is None:
            return True
        return alvo.sub_area_id is not None and (
            alvo.sub_area_id == concessao.sub_area_id or f'/{concessao.sub_area_id}/' in alvo.caminho
        )

    def permite(self, acao, alvo, categoria):
        if acao not in self.permissoes or not self.cobre(alvo):
            return False
        if categoria is not None and self.base in BASES_COM_CATEGORIA:
            # Lista vazia nega: nega por padrão (inferência a confirmar, T3.1: ver tasks.md).
            return categoria.pk in self.categorias
        return True


@dataclass(frozen=True)
class Memoria:
    catalogo: dict[str, bool]  # código da ação → delegável
    vinculos: tuple[Vinculo, ...]


def memoria_de(pessoa):
    memoria = getattr(pessoa, _ATRIBUTO_MEMORIA, None)
    if memoria is None:
        with transaction.atomic(), connection.cursor() as consulta:
            # Função do banco (migração 0003): lê as concessões da própria pessoa sem depender das variáveis de RLS
            # que `com_permissao` ainda vai calcular a partir delas. O filtro de "ativa" repete `concessoes_ativas`;
            # test_rls confere os dois nas bordas. A identidade assinada (migração 0004) vale só nesta transação.
            fixar_identidade(consulta, pessoa.pk)
            consulta.execute('SELECT * FROM vinculos_da_pessoa(%s, %s)', [pessoa.pk, timezone.now()])
            linhas = consulta.fetchall()
        vinculos = tuple(
            Vinculo(
                Concessao(id=cid, empresa_id=empresa, fazenda_id=fazenda, sub_area_id=sub_area, fim=fim),
                base,
                frozenset(permissoes),
                frozenset(categorias),
            )
            for cid, empresa, fazenda, sub_area, fim, base, permissoes, categorias in linhas
        )
        memoria = Memoria(dict(Permissao.objects.values_list('codigo', 'delegavel')), vinculos)
        setattr(pessoa, _ATRIBUTO_MEMORIA, memoria)
    return memoria


def esquecer(pessoa):
    if hasattr(pessoa, _ATRIBUTO_MEMORIA):
        delattr(pessoa, _ATRIBUTO_MEMORIA)


def _identificada(pessoa):
    return pessoa is not None and pessoa.is_authenticated


def pode(pessoa, acao, alvo=None, categoria=None):
    """Decide se `pessoa` exerce `acao` sobre `alvo` (Empresa, Fazenda ou SubArea), na `categoria` do dado se houver.

    Sem `alvo` só decide o Administrador da plataforma: ação sem lugar para cobrir não é concedida por escopo.
    A categoria só restringe cargo de Técnico e Usuário; Curador e Administrador não têm limite por categoria.
    """
    if not _identificada(pessoa):
        return False
    memoria = memoria_de(pessoa)
    if acao not in memoria.catalogo:
        return False
    if pessoa.administrador_plataforma:
        return True
    if acao in ACOES_DA_PLATAFORMA or alvo is None:
        return False
    alvo_resolvido = alvo_de(alvo)
    return alvo_resolvido is not None and any(
        vinculo.permite(acao, alvo_resolvido, categoria) for vinculo in memoria.vinculos
    )


def administrador_da_empresa(pessoa, empresa_id):
    """Administrador da empresa inteira (nível base administrador, escopo de empresa) com `redefinir_senha` (R5)."""
    return _identificada(pessoa) and any(
        vinculo.base == 'administrador'
        and vinculo.concessao.fazenda_id is None
        and vinculo.concessao.empresa_id == empresa_id
        and 'redefinir_senha' in vinculo.permissoes
        for vinculo in memoria_de(pessoa).vinculos
    )


@dataclass(frozen=True)
class Escopos:
    """Onde `pessoa` exerce uma ação: base da listagem de fazendas (R14) e das variáveis de RLS (Fase 4)."""

    plataforma: bool = False
    empresas: frozenset[int] = frozenset()
    fazendas: frozenset[int] = frozenset()
    sub_areas: frozenset[int] = frozenset()
    fazendas_das_sub_areas: frozenset[int] = frozenset()
    empresas_das_fazendas: frozenset[int] = frozenset()  # empresa de cada fazenda ou sub-área do escopo (só leitura)


def escopos_da_acao(pessoa, acao):
    if not _identificada(pessoa):
        return Escopos()
    memoria = memoria_de(pessoa)
    if acao not in memoria.catalogo:
        return Escopos()
    if pessoa.administrador_plataforma:
        return Escopos(plataforma=True)
    if acao in ACOES_DA_PLATAFORMA:
        return Escopos()
    concessoes = [
        vinculo.concessao
        for vinculo in memoria.vinculos
        if (vinculo.tem(acao) if acao in ACOES_DE_DELEGACAO else acao in vinculo.permissoes)
    ]
    return Escopos(
        empresas=frozenset(c.empresa_id for c in concessoes if c.fazenda_id is None),
        fazendas=frozenset(c.fazenda_id for c in concessoes if c.fazenda_id is not None and c.sub_area_id is None),
        sub_areas=frozenset(c.sub_area_id for c in concessoes if c.sub_area_id is not None),
        fazendas_das_sub_areas=frozenset(
            c.fazenda_id for c in concessoes if c.sub_area_id is not None and c.fazenda_id is not None
        ),
        empresas_das_fazendas=frozenset(c.empresa_id for c in concessoes if c.fazenda_id is not None),
    )


@contextmanager
def com_permissao(pessoa, *acoes, usando=DEFAULT_DB_ALIAS):
    """Abre a transação com as variáveis de RLS da `pessoa` (R12): a união dos escopos das `acoes` (padrão `ver`).

    Sem este bloco o papel `app` não vê linha alguma das tabelas com RLS. Ao sair sem erro devolve os valores que já
    estavam (bloco dentro de bloco, ou dentro da transação do chamador); com erro a transação ou o ponto de
    salvamento desfaz tudo, as variáveis inclusive. Granularidade de sub-área e de categoria continua em `pode()`.
    """
    escopos = [escopos_da_acao(pessoa, acao) for acao in (acoes or ('ver',))]
    def lista(*conjuntos):
        return ','.join(str(pk) for pk in sorted(set().union(*conjuntos)))

    novos = (
        '1' if any(escopo.plataforma for escopo in escopos) else '',
        lista(*(e.empresas for e in escopos)),
        lista(*(e.empresas_das_fazendas for e in escopos)),
        lista(*(e.fazendas | e.fazendas_das_sub_areas for e in escopos)),
    )
    with transaction.atomic(using=usando), connections[usando].cursor() as consulta:
        anteriores = ler_contexto(consulta)
        fixar_contexto(consulta, *novos)
        yield
        restaurar_contexto(consulta, anteriores)


def exige_permissao(acao, obter_alvo=None, obter_categoria=None, listagem=False):
    """Decorador de rota: nega com `PermissionDenied` (403) antes de a rota rodar, dentro de `com_permissao`.

    `obter_alvo(requisicao, *args, **kwargs)` devolve o alvo da ação e `obter_categoria(...)`, a categoria do dado, se
    a rota trata dado categorizado: sem ela, Técnico e Usuário com categoria passariam por qualquer categoria
    (achado do Sourcery, PR #11). A rota decorada leva `acao_exigida`, que a varredura de rotas da Fase 5 confere.

    `listagem=True` é para rota que devolve vários itens e não tem um alvo só: abre o bloco da ação (a RLS vale) e
    não chama `pode()`, porque `pode()` sem alvo só passa a plataforma. A rota filtra por `escopos_da_acao` (ou por
    serviço que o faz) e materializa a lista antes de sair do bloco; a varredura lê `listagem` e o teste negativo
    de cada listagem prova que pessoa sem concessão recebe lista vazia.
    """

    def decorar(funcao):
        @wraps(funcao)
        def interna(requisicao, *args, **kwargs):
            # O escopo vem antes de `obter_alvo`: na produção o papel `app` só carrega o alvo (Fazenda, SubArea,
            # CategoriaDado) que a RLS deixa ver; alvo fora do escopo some e a rota responde como não encontrado.
            with com_permissao(requisicao.user, acao):
                alvo = obter_alvo(requisicao, *args, **kwargs) if obter_alvo else None
                categoria = obter_categoria(requisicao, *args, **kwargs) if obter_categoria else None
                if not listagem and not pode(requisicao.user, acao, alvo, categoria):
                    raise PermissionDenied
                return funcao(requisicao, *args, **kwargs)

        setattr(interna, 'acao_exigida', acao)
        setattr(interna, 'listagem', listagem)
        return interna

    return decorar
