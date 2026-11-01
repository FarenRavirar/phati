from django.db import migrations

# Cópia congelada (como na 0001): migração não importa código que evolui. Só a base Administrador recebe estas ações
# (003 R9, R11); `delegavel=False` impede que um cargo personalizado as ganhe.
ACOES = [
    ('renomear', 'Renomear empresa, fazenda ou sub-área', False),
    ('arquivar', 'Arquivar empresa, fazenda ou sub-área', False),
    ('desarquivar', 'Desarquivar empresa, fazenda ou sub-área', False),
]


def carregar(apps, schema_editor):
    Permissao = apps.get_model('permissao', 'Permissao')
    Cargo = apps.get_model('permissao', 'Cargo')
    CargoPermissao = apps.get_model('permissao', 'CargoPermissao')
    Permissao.objects.bulk_create(Permissao(codigo=c, descricao=d, delegavel=g) for c, d, g in ACOES)
    # Cargos "administrador" já existentes acompanham o catálogo (cargos_base.py).
    CargoPermissao.objects.bulk_create(
        CargoPermissao(cargo=cargo, permissao_id=codigo)
        for cargo in Cargo.objects.filter(base='administrador')
        for codigo, _, _ in ACOES
    )


def descarregar(apps, schema_editor):
    codigos = [c for c, _, _ in ACOES]
    apps.get_model('permissao', 'CargoPermissao').objects.filter(permissao_id__in=codigos).delete()
    apps.get_model('permissao', 'Permissao').objects.filter(codigo__in=codigos).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('permissao', '0006_cargo_versao'),
    ]

    operations = [
        migrations.RunPython(carregar, descarregar),
    ]
