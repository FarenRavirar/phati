from django.db import migrations

# Cópia congelada de `NOMES_PADRAO_DOS_NIVEIS` (003 R10): migração não importa código que evolui.
NOMES_PADRAO = {1: 'Gleba', 2: 'Talhão'}


def preencher(apps, schema_editor):
    """Empresa criada antes da 003 não tem os níveis 1 e 2; recebe os nomes padrão sem tocar em nome já configurado."""
    modelo_empresa = apps.get_model('territorio', 'Empresa')
    modelo_nivel = apps.get_model('territorio', 'NivelDivisao')
    existentes = set(modelo_nivel.objects.values_list('empresa_id', 'nivel'))
    modelo_nivel.objects.bulk_create(
        modelo_nivel(empresa_id=empresa_id, nivel=nivel, nome=nome)
        for empresa_id in modelo_empresa.objects.values_list('pk', flat=True)
        for nivel, nome in NOMES_PADRAO.items()
        if (empresa_id, nivel) not in existentes
    )


class Migration(migrations.Migration):

    dependencies = [
        ('territorio', '0004_arquivamento'),
    ]

    operations = [
        # Sem reversão do dado: apagar nomes de nível depois do uso destruiria configuração de empresa.
        migrations.RunPython(preencher, migrations.RunPython.noop),
    ]
