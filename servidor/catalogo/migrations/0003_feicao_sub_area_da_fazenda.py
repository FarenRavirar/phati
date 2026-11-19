# Feição só aponta sub-área da própria fazenda (008 T1.3, pendência de D115 fechada). FK composta pelas três colunas;
# `sub_area_id` nulo (fazenda inteira, R7) não é checado pelo banco, que é o comportamento padrão do MATCH SIMPLE.

from django.db import migrations

ADICIONAR = (
    'ALTER TABLE catalogo_feicao ADD CONSTRAINT feicao_sub_area_da_fazenda '
    'FOREIGN KEY (sub_area_id, empresa_id, fazenda_id) REFERENCES sub_area (id, empresa_id, fazenda_id)'
)
REMOVER = 'ALTER TABLE catalogo_feicao DROP CONSTRAINT feicao_sub_area_da_fazenda'


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0002_rls_chave_composta'),
        ('territorio', '0007_sub_area_chave_composta'),
    ]

    operations = [
        migrations.RunSQL(sql=ADICIONAR, reverse_sql=REMOVER),
    ]
