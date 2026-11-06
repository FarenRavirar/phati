from django.db import migrations

# Cópia congelada (como na 0001 e na 0007). Ação de plataforma (004b R13): só o Administrador da plataforma exerce,
# `delegavel=False` e fora de `cargo_permissao`, então nenhum cargo a ganha.
ACOES = [('ver_monitor_google', 'Ver o monitor de uso do Google (só o Administrador da plataforma)', False)]


def carregar(apps, schema_editor):
    modelo = apps.get_model('permissao', 'Permissao')
    modelo.objects.bulk_create(modelo(codigo=c, descricao=d, delegavel=g) for c, d, g in ACOES)


def descarregar(apps, schema_editor):
    codigos = [c for c, _, _ in ACOES]
    apps.get_model('permissao', 'CargoPermissao').objects.filter(permissao_id__in=codigos).delete()
    apps.get_model('permissao', 'Permissao').objects.filter(codigo__in=codigos).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('permissao', '0009_uso_acao'),
    ]

    operations = [
        migrations.RunPython(carregar, descarregar),
    ]
