"""Nome dos níveis da divisão da fazenda, por empresa (003 R10): gleba e talhão por padrão, o nível 3 sem nome."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from comum.auditoria import auditar
from permissao.pode import pode
from territorio.cadastro import NIVEL_MAXIMO, nome_valido
from territorio.models import NivelDivisao


def nome_do_nivel(empresa, nivel):
    """Nome configurado do nível, ou "Nível N" se não há (nunca um nome inventado)."""
    nome = NivelDivisao.objects.filter(empresa_id=empresa.pk, nivel=nivel).values_list('nome', flat=True).first()
    return nome or f'Nível {nivel}'


def nomes_configurados(empresa):
    """`{nível: nome}` só dos níveis que têm nome (o formulário de níveis parte daqui)."""
    return dict(NivelDivisao.objects.filter(empresa_id=empresa.pk).values_list('nivel', 'nome'))


def nomes_dos_niveis(empresa):
    """`{1: nome, 2: nome, 3: nome}` dos três níveis, numa consulta."""
    configurados = nomes_configurados(empresa)
    return {nivel: configurados.get(nivel) or f'Nível {nivel}' for nivel in range(1, NIVEL_MAXIMO + 1)}


def definir_nivel(solicitante, empresa, nivel, nome):
    """Dá nome ao `nivel` (1 a 3) da empresa; grava `auditar` com o nome antigo e o novo."""
    if nivel not in range(1, NIVEL_MAXIMO + 1):
        raise ValidationError('O nível vai de 1 a 3.', code='nivel_invalido')
    nome = nome_valido(nome, maximo=100)
    with transaction.atomic():
        if not pode(solicitante, 'configurar_niveis_divisao', empresa):
            raise PermissionDenied
        registro, criado = NivelDivisao.objects.select_for_update().get_or_create(empresa=empresa, nivel=nivel, defaults={'nome': nome})
        antigo = None if criado else registro.nome
        registro.nome = nome
        registro.save(update_fields=['nome'])
        auditar('nivel_definido', solicitante, registro, empresa.pk, {'nivel': nivel, 'nome_antigo': antigo, 'nome_novo': nome})
    return registro
