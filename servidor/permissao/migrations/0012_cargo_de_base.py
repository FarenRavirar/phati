# Fase 4 da spec 012 (segunda migração de permissao, aprovada pelo mantenedor): marca `Cargo.de_base` e a carga da ação
# `exportar_dados` (T4.3, R34, Q20), que saiu de `territorio/0008` (ainda não mergeada).
#
# A marca diz quem é cargo-base de fábrica. Nos bancos que já existem ela é preenchida uma vez, por empresa: o
# administrador é o de menor pk da base administrador; cada uma das outras bases (curador, tecnico, usuario) é a de
# menor pk que vem depois do administrador (criar_cargos_base cria nessa ordem). Empresa sem administrador: nada.
# A restrição única (empresa, base) só vale para a marca, então a empresa tem um cargo-base por base.
#
# A carga liga `exportar_dados` ao cargo-base de base administrador (todos) e ao de base curador marcado. A ação não é
# delegável no catálogo. A ida só acrescenta linhas (`ignore_conflicts` refaz sem erro); a volta é noop, como nas
# outras cargas, para o guard de compatibilidade (comum/compat_migracao.py) não reprovar a carga inversa.
# Operações: AddField com default, RunPython de preenchimento e carga, AddConstraint. O guard aprova cada uma.

from django.db import migrations, models
from django.db.models import Q

BASES_APOS_ADMINISTRADOR = ('curador', 'tecnico', 'usuario')

# Cópia congelada (como nas outras migrações de permissao). Não delegável: só o Administrador a põe num cargo (Q20).
ACOES = [('exportar_dados', 'Exportar a lista de fazendas em CSV (só o Administrador e o Curador de base)', False)]


def marcar_cargos_base(apps, schema_editor):
    Cargo = apps.get_model('permissao', 'Cargo')
    admin_de = {}
    for empresa_id, pk in Cargo.objects.filter(base='administrador').order_by('pk').values_list('empresa_id', 'pk'):
        admin_de.setdefault(empresa_id, pk)
    marcar = []
    for empresa_id, pk_admin in admin_de.items():
        marcar.append(pk_admin)
        for base in BASES_APOS_ADMINISTRADOR:
            cargo = Cargo.objects.filter(empresa_id=empresa_id, base=base, pk__gt=pk_admin).order_by('pk').first()
            if cargo is not None:
                marcar.append(cargo.pk)
    Cargo.objects.filter(pk__in=marcar).update(de_base=True)


def carregar_exportar_dados(apps, schema_editor):
    Permissao = apps.get_model('permissao', 'Permissao')
    Permissao.objects.bulk_create(
        (Permissao(codigo=c, descricao=d, delegavel=g) for c, d, g in ACOES), ignore_conflicts=True,
    )
    Cargo = apps.get_model('permissao', 'Cargo')
    CargoPermissao = apps.get_model('permissao', 'CargoPermissao')
    cargos = Cargo.objects.filter(Q(base='administrador') | Q(base='curador', de_base=True))
    CargoPermissao.objects.bulk_create(
        (CargoPermissao(cargo=cargo, permissao_id=codigo) for cargo in cargos for codigo, _, _ in ACOES),
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('permissao', '0011_ver_auditoria'),
    ]

    operations = [
        migrations.AddField(
            model_name='cargo',
            name='de_base',
            field=models.BooleanField(default=False, db_default=False),
        ),
        migrations.RunPython(marcar_cargos_base, migrations.RunPython.noop),
        migrations.RunPython(carregar_exportar_dados, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='cargo',
            constraint=models.UniqueConstraint(
                condition=Q(('de_base', True)), fields=('empresa', 'base'), name='cargo_base_unica_por_empresa',
            ),
        ),
    ]
