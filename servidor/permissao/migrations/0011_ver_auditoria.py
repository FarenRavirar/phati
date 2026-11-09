from django.db import migrations

# Cópia congelada (como na 0001, na 0007 e na 0010). Ler a auditoria (005 R1): `delegavel=False`, então só os cargos-base
# `administrador` a ganham (aqui, nos que já existem; `criar_cargos_base` cuida dos novos). O Administrador da plataforma
# a exerce por `pode()` sem concessão.
ACOES = [('ver_auditoria', 'Ler a auditoria da empresa (só o Administrador)', False)]


def carregar(apps, schema_editor):
    permissao = apps.get_model('permissao', 'Permissao')
    permissao.objects.bulk_create(permissao(codigo=c, descricao=d, delegavel=g) for c, d, g in ACOES)
    cargo_permissao = apps.get_model('permissao', 'CargoPermissao')
    cargos = apps.get_model('permissao', 'Cargo').objects.filter(base='administrador')
    cargo_permissao.objects.bulk_create(
        cargo_permissao(cargo=cargo, permissao_id=codigo) for cargo in cargos for codigo, _, _ in ACOES
    )


def descarregar(apps, schema_editor):
    codigos = [c for c, _, _ in ACOES]
    apps.get_model('permissao', 'CargoPermissao').objects.filter(permissao_id__in=codigos).delete()
    apps.get_model('permissao', 'Permissao').objects.filter(codigo__in=codigos).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('permissao', '0010_acao_monitor_google'),
    ]

    operations = [
        migrations.RunPython(carregar, descarregar),
    ]
