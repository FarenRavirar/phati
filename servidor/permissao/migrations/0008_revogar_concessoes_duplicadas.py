"""Revoga as concessões repetidas que existam de antes de `conceder` ser idempotente (mantenedor, 2026-11-02, PR #32).

Duas concessões ativas da mesma pessoa, com o mesmo cargo, lugar, fim e categorias, dão o mesmo acesso: revogar uma deixava a
outra valendo. Fica a que começou primeiro (a de menor `inicio`, e a de menor `id` no empate) e as outras são revogadas, cada
uma com um evento de auditoria que diz qual foi mantida. A revogação grava `revogada_por` com quem concedeu a repetida: a
constraint exige uma pessoa, e a migração não age como ninguém. Cópia congelada da regra de `concessao_igual`: migração não
importa código que evolui. Sem repetidas, não muda nada. Não se desfaz: o gatilho `concessao_validar` proíbe revogada voltar; o evento de auditoria de cada revogação diz o que mudou.
"""

from collections import defaultdict

from django.db import migrations
from django.db.models import Q
from django.utils import timezone

MARCA = '0008_revogar_concessoes_duplicadas'


def revogar_repetidas(apps, schema_editor):
    concessao = apps.get_model('permissao', 'Concessao')
    ligacao = apps.get_model('permissao', 'ConcessaoCategoria')
    evento = apps.get_model('comum', 'EventoAuditoria')
    agora = timezone.now()
    ativas = list(concessao.objects.filter(revogada_em__isnull=True).filter(Q(fim__isnull=True) | Q(fim__gt=agora)).order_by('inicio', 'id'))
    categorias = defaultdict(set)
    for concessao_id, categoria_id in ligacao.objects.filter(concessao_id__in=[c.pk for c in ativas]).values_list('concessao_id', 'categoria_id'):
        categorias[concessao_id].add(categoria_id)
    mantidas = {}
    for c in ativas:
        chave = (c.pessoa_id, c.cargo_id, c.empresa_id, c.fazenda_id, c.sub_area_id, c.fim, frozenset(categorias[c.pk]))
        if chave not in mantidas:
            mantidas[chave] = c
            continue
        concessao.objects.filter(pk=c.pk).update(revogada_em=agora, revogada_por_id=c.concedida_por_id)
        evento.objects.create(
            pessoa_id=None, acao='concessao_revogada', alvo_tipo='Concessao', alvo_id=c.pk, empresa_id=c.empresa_id,
            detalhes={'pessoa_id': c.pessoa_id, 'motivo': 'duplicada', 'mantida': mantidas[chave].pk, 'migracao': MARCA},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('permissao', '0007_acoes_territorio'),
        ('comum', '0002_evento_auditoria'),
    ]

    operations = [
        migrations.RunPython(revogar_repetidas, migrations.RunPython.noop),
    ]
