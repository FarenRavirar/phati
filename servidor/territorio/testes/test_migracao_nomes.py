"""Migração `territorio/0006`: nome repetido entre itens ativos é renomeado antes do índice único, sem apagar dado."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

ANTES = ('territorio', '0005_niveis_padrao')
DEPOIS = ('territorio', '0006_nome_ativo_unico')


def _migrar_para(alvo):
    executor = MigrationExecutor(connection)
    executor.migrate([alvo])
    return executor.loader.project_state([alvo]).apps


def test_nomes_repetidos_ganham_sufixo_e_nada_e_apagado():
    try:
        antigos = _migrar_para(ANTES)
        empresa_antiga = antigos.get_model('territorio', 'Empresa')
        fazenda_antiga = antigos.get_model('territorio', 'Fazenda')
        sub_area_antiga = antigos.get_model('territorio', 'SubArea')
        primeira = empresa_antiga.objects.create(nome='Empresa Norte')
        empresa_antiga.objects.create(nome='empresa norte')
        outra = empresa_antiga.objects.create(nome='Outra')
        for empresa in (primeira, outra):
            fazenda_antiga.objects.create(empresa=empresa, nome='Norte')
        fazenda_antiga.objects.create(empresa=primeira, nome='NORTE')
        fazenda_antiga.objects.create(empresa=primeira, nome='NORTE (2)')  # o sufixo candidato já existe
        fazenda_antiga.objects.create(empresa=primeira, nome='NORTE')
        fazenda = fazenda_antiga.objects.filter(empresa=primeira).order_by('pk').first()
        for nome in ('Gleba', 'gleba'):
            sub_area_antiga.objects.create(empresa=primeira, fazenda=fazenda, nivel=1, nome=nome)

        novos = _migrar_para(DEPOIS)
        empresa = novos.get_model('territorio', 'Empresa')
        fazenda_nova = novos.get_model('territorio', 'Fazenda')
        sub_area = novos.get_model('territorio', 'SubArea')
        assert list(empresa.objects.order_by('pk').values_list('nome', flat=True)) == ['Empresa Norte', 'empresa norte (2)', 'Outra']
        assert list(fazenda_nova.objects.filter(empresa_id=primeira.pk).order_by('pk').values_list('nome', flat=True)) == [
            'Norte', 'NORTE (3)', 'NORTE (2)', 'NORTE (4)',
        ]
        assert fazenda_nova.objects.filter(empresa_id=outra.pk).get().nome == 'Norte'  # outro lugar: não conta como repetido
        assert list(sub_area.objects.order_by('pk').values_list('nome', flat=True)) == ['Gleba', 'gleba (2)']
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
