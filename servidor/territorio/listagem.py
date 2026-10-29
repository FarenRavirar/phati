"""Listagem de fazendas autorizadas (R14): só as que a pessoa pode ver, pelo escopo de cada concessão ativa."""

from django.db.models import Q

from permissao.pode import escopos_da_acao
from territorio.models import Fazenda


def fazendas_autorizadas(pessoa):
    """Fazendas da empresa inteira, da fazenda concedida ou da fazenda que contém a sub-área concedida."""
    escopos = escopos_da_acao(pessoa, 'ver')
    if escopos.plataforma:
        return Fazenda.objects.order_by('nome', 'pk')
    return Fazenda.objects.filter(
        Q(empresa_id__in=escopos.empresas) | Q(pk__in=escopos.fazendas | escopos.fazendas_das_sub_areas)
    ).order_by('nome', 'pk')
