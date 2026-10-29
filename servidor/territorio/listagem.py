"""Listagem de fazendas autorizadas (R14): só as que a pessoa pode ver, pelo escopo de cada concessão ativa."""

from django.db.models import Q

from permissao.pode import com_permissao, escopos_da_acao
from territorio.models import Fazenda


def fazendas_autorizadas(pessoa):
    """Fazendas da empresa inteira, da fazenda concedida ou da fazenda que contém a sub-área concedida."""
    escopos = escopos_da_acao(pessoa, 'ver')
    if escopos.plataforma:
        consulta = Fazenda.objects.all()
    else:
        consulta = Fazenda.objects.filter(
            Q(empresa_id__in=escopos.empresas) | Q(pk__in=escopos.fazendas | escopos.fazendas_das_sub_areas)
        )
    # Avaliada dentro de `com_permissao`: o papel `app` não vê fazenda sem as variáveis, e a lista preguiçosa
    # só consultaria o banco depois de o bloco terminar.
    with com_permissao(pessoa, 'ver'):
        return list(consulta.order_by('nome', 'pk'))
