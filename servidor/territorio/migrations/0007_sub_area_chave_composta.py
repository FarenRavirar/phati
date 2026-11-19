# Chave que o catálogo referencia (008 T1.3, D115): `sub_area (id, empresa_id, fazenda_id)` é única, para a FK composta
# de `catalogo_feicao` garantir que a sub-área é da mesma fazenda da feição. Só acrescenta restrição.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('territorio', '0006_nome_ativo_unico'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='subarea',
            constraint=models.UniqueConstraint(fields=('id', 'empresa', 'fazenda'), name='sub_area_chave_composta'),
        ),
    ]
