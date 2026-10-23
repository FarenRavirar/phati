# Gerada pelo Django 6.1.2 e completada à mão: chave composta e gatilho de sub_area no fim (RunSQL).

import django.db.models.deletion
from django.db import migrations, models

# O gatilho qualifica `public.sub_area` e fixa o search_path: sem isso, `pg_temp.sub_area` (TEMPORARY vem de PUBLIC)
# sombreia a tabela e valida contra linhas falsas (achado do Codex, PR #1).
# Chave composta: a empresa da sub-área é a empresa da fazenda dela, e `fazenda.empresa_id` não muda
# enquanto houver sub-área (a RLS da Fase 4 confia nessas colunas).
CRIAR = """
ALTER TABLE sub_area ADD CONSTRAINT sub_area_fazenda_da_empresa
    FOREIGN KEY (fazenda_id, empresa_id) REFERENCES fazenda (id, empresa_id);

CREATE FUNCTION sub_area_validar() RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    p public.sub_area%ROWTYPE;
BEGIN
    IF TG_OP = 'UPDATE' AND (
        OLD.pai_id IS DISTINCT FROM NEW.pai_id OR OLD.nivel <> NEW.nivel
        OR OLD.fazenda_id <> NEW.fazenda_id OR OLD.empresa_id <> NEW.empresa_id
    ) THEN
        -- Mover nó não recalcula o caminho dos descendentes; nenhuma tarefa pede mover.
        RAISE EXCEPTION 'sub_area: pai, nivel, fazenda e empresa não mudam' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.pai_id IS NULL THEN
        NEW.caminho := '/';
    ELSE
        SELECT * INTO p FROM public.sub_area WHERE id = NEW.pai_id;
        IF p.id IS NULL OR p.fazenda_id <> NEW.fazenda_id OR p.nivel <> NEW.nivel - 1 THEN
            RAISE EXCEPTION 'sub_area: pai de outra fazenda ou de nivel incoerente' USING ERRCODE = 'check_violation';
        END IF;
        NEW.caminho := p.caminho || p.id || '/';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER sub_area_validar BEFORE INSERT OR UPDATE ON sub_area
    FOR EACH ROW EXECUTE FUNCTION sub_area_validar();
"""

REMOVER = """
DROP TRIGGER sub_area_validar ON sub_area;
DROP FUNCTION sub_area_validar();
ALTER TABLE sub_area DROP CONSTRAINT sub_area_fazenda_da_empresa;
"""


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('comum', '0001_privilegios_app'),
    ]

    operations = [
        migrations.CreateModel(
            name='Empresa',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=200)),
                ('criada_em', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'empresa',
            },
        ),
        migrations.CreateModel(
            name='Fazenda',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=200)),
                ('criada_em', models.DateTimeField(auto_now_add=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='territorio.empresa')),
            ],
            options={
                'db_table': 'fazenda',
            },
        ),
        migrations.CreateModel(
            name='NivelDivisao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nivel', models.PositiveSmallIntegerField()),
                ('nome', models.CharField(max_length=100)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='territorio.empresa')),
            ],
            options={
                'db_table': 'nivel_divisao',
            },
        ),
        migrations.CreateModel(
            name='SubArea',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nivel', models.PositiveSmallIntegerField()),
                ('nome', models.CharField(max_length=200)),
                ('caminho', models.TextField(default='/', editable=False)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='territorio.empresa')),
                ('fazenda', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='territorio.fazenda')),
                ('pai', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='territorio.subarea')),
            ],
            options={
                'db_table': 'sub_area',
            },
        ),
        migrations.AddConstraint(
            model_name='fazenda',
            constraint=models.UniqueConstraint(fields=('id', 'empresa'), name='fazenda_id_empresa_unico'),
        ),
        migrations.AddConstraint(
            model_name='niveldivisao',
            constraint=models.CheckConstraint(condition=models.Q(('nivel__gte', 1), ('nivel__lte', 3)), name='nivel_divisao_nivel_1_a_3'),
        ),
        migrations.AddConstraint(
            model_name='niveldivisao',
            constraint=models.UniqueConstraint(fields=('empresa', 'nivel'), name='nivel_divisao_unico_por_empresa'),
        ),
        migrations.AddConstraint(
            model_name='subarea',
            constraint=models.CheckConstraint(condition=models.Q(('nivel__gte', 1), ('nivel__lte', 3)), name='sub_area_nivel_1_a_3'),
        ),
        migrations.AddConstraint(
            model_name='subarea',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('nivel', 1), ('pai__isnull', True)), models.Q(('nivel__gt', 1), ('pai__isnull', False)), _connector='OR'), name='sub_area_raiz_sem_pai'),
        ),
        migrations.RunSQL(CRIAR, REMOVER),
    ]
