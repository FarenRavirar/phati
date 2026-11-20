"""Metadados de §6.2 na versão (008 T2.3; R8). Só colunas e uma CHECK: as políticas de RLS são por linha, e o grant do
papel `app` é por tabela (0001), então as colunas novas herdam os dois. Reversível: a reversão tira a CHECK e as colunas.

Premissa: o catálogo não está implantado em nenhuma instalação, então a tabela não tem linhas. Com linha de `origem`
vazia, a CHECK falharia ao ser criada; o `default=''` existe só para a coluna NOT NULL ser criada e não fica no modelo."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('catalogo', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='versaocamada',
            name='origem',
            field=models.TextField(default=''),
            preserve_default=False,
        ),
        migrations.AddField(model_name='versaocamada', name='metodo', field=models.TextField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='escala_resolucao', field=models.TextField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='unidades', field=models.TextField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='limitacoes', field=models.TextField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='ressalvas', field=models.TextField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='notas_tecnicas', field=models.TextField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='validade_vigencia', field=models.TextField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='elaborador', field=models.TextField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='revisor', field=models.TextField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='data_coleta', field=models.DateField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='data_referencia', field=models.DateField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='data_elaboracao', field=models.DateField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='data_documento', field=models.DateField(null=True, blank=True)),
        migrations.AddField(model_name='versaocamada', name='data_publicacao', field=models.DateField(null=True, blank=True)),
        migrations.AddConstraint(
            model_name='versaocamada',
            constraint=models.CheckConstraint(condition=models.Q(origem__regex=r'[^[:space:]]'), name='versao_camada_origem_nao_vazia'),
        ),
    ]
