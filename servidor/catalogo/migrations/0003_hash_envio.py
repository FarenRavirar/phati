"""Hash do original no envio (008 T2.4; R15). Só uma coluna e uma CHECK: RLS por linha e grant por tabela (0001) seguem.
Reversível. Premissa igual à da 0002: o catálogo não está implantado, então a tabela não tem linhas."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('catalogo', '0002_metadados_versao')]

    operations = [
        migrations.AddField(
            model_name='enviocamada',
            name='hash_original',
            field=models.CharField(max_length=64, default=''),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name='enviocamada',
            constraint=models.CheckConstraint(condition=models.Q(hash_original__regex=r'^[0-9a-f]{64}$'), name='envio_camada_hash_valido'),
        ),
    ]
