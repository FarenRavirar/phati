"""Listagens de território autorizadas (R14, R12): só o que a pessoa pode ver, pelo escopo de cada concessão ativa."""

from django.db.models import Q

from permissao.pode import com_permissao, escopos_da_acao
from territorio.models import Empresa, Fazenda, SubArea


def fazendas_autorizadas(pessoa, pk=None, empresa_id=None):
    """Fazendas da empresa inteira, da fazenda concedida ou da fazenda que contém a sub-área concedida.

    Com `pk`, só a fazenda pedida (se autorizada): a URL de escopo não carrega a lista inteira (Qodo e Sourcery, PR #19).
    Com `empresa_id`, só as dela, filtradas na consulta e não depois de carregar tudo (Sourcery, PR #21)."""
    escopos = escopos_da_acao(pessoa, 'ver')
    if escopos.plataforma:
        consulta = Fazenda.objects.all()
    else:
        consulta = Fazenda.objects.filter(
            Q(empresa_id__in=escopos.empresas) | Q(pk__in=escopos.fazendas | escopos.fazendas_das_sub_areas)
        )
    # Avaliada dentro de `com_permissao`: o papel `app` não vê fazenda sem as variáveis, e a lista preguiçosa
    # só consultaria o banco depois de o bloco terminar.
    if pk is not None:
        consulta = consulta.filter(pk=pk)
    if empresa_id is not None:
        consulta = consulta.filter(empresa_id=empresa_id)
    with com_permissao(pessoa, 'ver'):
        return list(consulta.order_by('nome', 'pk'))


def empresas_autorizadas(pessoa, pk=None):
    """Empresas em que a pessoa tem acesso de leitura, inclusive as que só contêm uma fazenda ou sub-área concedida.

    Com `pk`, só a empresa pedida (se autorizada)."""
    escopos = escopos_da_acao(pessoa, 'ver')
    if escopos.plataforma:
        consulta = Empresa.objects.all()
    else:
        consulta = Empresa.objects.filter(pk__in=escopos.empresas | escopos.empresas_das_fazendas)
    if pk is not None:
        consulta = consulta.filter(pk=pk)
    with com_permissao(pessoa, 'ver'):
        return list(consulta.order_by('nome', 'pk'))


def sub_areas_da_fazenda(pessoa, fazenda):
    """Sub-áreas da `fazenda` que a pessoa alcança: todas, se o acesso é da plataforma, da empresa ou da fazenda;
    com acesso só a sub-áreas, cada uma delas e as descendentes (o pai de uma raiz concedida não vem: monte a árvore
    tratando sub-área sem pai na lista como raiz)."""
    escopos = escopos_da_acao(pessoa, 'ver')
    consulta = SubArea.objects.filter(fazenda_id=fazenda.pk)
    if not (escopos.plataforma or fazenda.empresa_id in escopos.empresas or fazenda.pk in escopos.fazendas):
        filtro = Q(pk__in=escopos.sub_areas)
        for sub_area_id in escopos.sub_areas:
            filtro |= Q(caminho__contains=f'/{sub_area_id}/')
        consulta = consulta.filter(filtro)
    with com_permissao(pessoa, 'ver'):
        return list(consulta.order_by('nivel', 'nome', 'pk'))
