# Gerada pelo Django 6.1.2 e completada à mão: chaves compostas e gatilhos no fim (RunSQL).

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Os gatilhos qualificam `public.*` e fixam o search_path: sem isso, `pg_temp.<tabela>` (TEMPORARY vem de PUBLIC)
# sombreia a tabela e valida contra linhas falsas (achado do Codex, PR #1).
# Chaves compostas (MATCH SIMPLE: coluna nula desliga a checagem, e `concessao_sub_area_exige_fazenda` fecha o caso
# sub-área sem fazenda): o cargo e o escopo pertencem à empresa da concessão, e a sub-área à fazenda dela.
CRIAR = """
ALTER TABLE concessao ADD CONSTRAINT concessao_cargo_da_empresa
    FOREIGN KEY (cargo_id, empresa_id) REFERENCES cargo (id, empresa_id);
ALTER TABLE concessao ADD CONSTRAINT concessao_fazenda_da_empresa
    FOREIGN KEY (fazenda_id, empresa_id) REFERENCES fazenda (id, empresa_id);
ALTER TABLE concessao ADD CONSTRAINT concessao_sub_area_da_fazenda
    FOREIGN KEY (sub_area_id, fazenda_id) REFERENCES sub_area (id, fazenda_id);

-- Base e empresa do cargo não mudam: trocar a base sob concessões já feitas mudaria a hierarquia de convite e
-- deixaria categoria presa a cargo que não a aceita.
CREATE FUNCTION cargo_validar() RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF OLD.base <> NEW.base OR OLD.empresa_id <> NEW.empresa_id THEN
        RAISE EXCEPTION 'cargo: base e empresa não mudam' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER cargo_validar BEFORE UPDATE ON cargo FOR EACH ROW EXECUTE FUNCTION cargo_validar();

-- Só o fim e a revogação mudam: trocar pessoa, cargo ou escopo de uma concessão é conceder de novo (R16).
CREATE FUNCTION concessao_validar() RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF OLD.pessoa_id <> NEW.pessoa_id OR OLD.cargo_id <> NEW.cargo_id OR OLD.empresa_id <> NEW.empresa_id
        OR OLD.fazenda_id IS DISTINCT FROM NEW.fazenda_id OR OLD.sub_area_id IS DISTINCT FROM NEW.sub_area_id
        OR OLD.inicio <> NEW.inicio OR OLD.concedida_por_id <> NEW.concedida_por_id THEN
        RAISE EXCEPTION 'concessao: só o fim e a revogação mudam' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER concessao_validar BEFORE UPDATE ON concessao FOR EACH ROW EXECUTE FUNCTION concessao_validar();

-- Categoria só em cargo de Técnico ou Usuário (D035) e da mesma empresa da concessão.
CREATE FUNCTION concessao_categoria_validar() RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    base_do_cargo text;
    empresa_da_concessao bigint;
    empresa_da_categoria bigint;
BEGIN
    SELECT c.base, k.empresa_id INTO base_do_cargo, empresa_da_concessao
        FROM public.concessao k JOIN public.cargo c ON c.id = k.cargo_id WHERE k.id = NEW.concessao_id;
    SELECT empresa_id INTO empresa_da_categoria FROM public.categoria_dado WHERE id = NEW.categoria_id;
    IF base_do_cargo IS NULL OR base_do_cargo NOT IN ('tecnico', 'usuario') THEN
        RAISE EXCEPTION 'concessao_categoria: só cargo de nível técnico ou usuário aceita categoria' USING ERRCODE = 'check_violation';
    END IF;
    IF empresa_da_categoria IS DISTINCT FROM empresa_da_concessao THEN
        RAISE EXCEPTION 'concessao_categoria: categoria de outra empresa' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER concessao_categoria_validar BEFORE INSERT OR UPDATE ON concessao_categoria
    FOR EACH ROW EXECUTE FUNCTION concessao_categoria_validar();
"""

REMOVER = """
DROP TRIGGER concessao_categoria_validar ON concessao_categoria;
DROP FUNCTION concessao_categoria_validar();
DROP TRIGGER concessao_validar ON concessao;
DROP FUNCTION concessao_validar();
DROP TRIGGER cargo_validar ON cargo;
DROP FUNCTION cargo_validar();
ALTER TABLE concessao DROP CONSTRAINT concessao_sub_area_da_fazenda;
ALTER TABLE concessao DROP CONSTRAINT concessao_fazenda_da_empresa;
ALTER TABLE concessao DROP CONSTRAINT concessao_cargo_da_empresa;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('permissao', '0001_initial'),
        ('territorio', '0002_subarea_sub_area_id_fazenda_unico'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Cargo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=100)),
                ('base', models.CharField(choices=[('usuario', 'usuario'), ('tecnico', 'tecnico'), ('curador', 'curador'), ('administrador', 'administrador')], max_length=20)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='territorio.empresa')),
            ],
            options={
                'db_table': 'cargo',
            },
        ),
        migrations.CreateModel(
            name='CargoPermissao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cargo', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='permissao.cargo')),
                ('permissao', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='permissao.permissao')),
            ],
            options={
                'db_table': 'cargo_permissao',
            },
        ),
        migrations.AddField(
            model_name='cargo',
            name='permissoes',
            field=models.ManyToManyField(through='permissao.CargoPermissao', to='permissao.permissao'),
        ),
        migrations.CreateModel(
            name='CategoriaDado',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=100)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='territorio.empresa')),
            ],
            options={
                'db_table': 'categoria_dado',
            },
        ),
        migrations.CreateModel(
            name='Concessao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('inicio', models.DateTimeField(default=django.utils.timezone.now)),
                ('fim', models.DateTimeField(blank=True, null=True)),
                ('revogada_em', models.DateTimeField(blank=True, null=True)),
                ('cargo', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='permissao.cargo')),
                ('concedida_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='territorio.empresa')),
                ('fazenda', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='territorio.fazenda')),
                ('pessoa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ('revogada_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('sub_area', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='territorio.subarea')),
            ],
            options={
                'db_table': 'concessao',
            },
        ),
        migrations.CreateModel(
            name='ConcessaoCategoria',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('categoria', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='permissao.categoriadado')),
                ('concessao', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='permissao.concessao')),
            ],
            options={
                'db_table': 'concessao_categoria',
            },
        ),
        migrations.AddField(
            model_name='concessao',
            name='categorias',
            field=models.ManyToManyField(through='permissao.ConcessaoCategoria', to='permissao.categoriadado'),
        ),
        migrations.AddConstraint(
            model_name='cargopermissao',
            constraint=models.UniqueConstraint(fields=('cargo', 'permissao'), name='cargo_permissao_unico'),
        ),
        migrations.AddConstraint(
            model_name='cargo',
            constraint=models.CheckConstraint(condition=models.Q(('base__in', ['usuario', 'tecnico', 'curador', 'administrador'])), name='cargo_base_valida'),
        ),
        migrations.AddConstraint(
            model_name='cargo',
            constraint=models.UniqueConstraint(fields=('empresa', 'nome'), name='cargo_nome_unico_por_empresa'),
        ),
        migrations.AddConstraint(
            model_name='cargo',
            constraint=models.UniqueConstraint(fields=('id', 'empresa'), name='cargo_id_empresa_unico'),
        ),
        migrations.AddConstraint(
            model_name='categoriadado',
            constraint=models.UniqueConstraint(fields=('empresa', 'nome'), name='categoria_dado_nome_unico_por_empresa'),
        ),
        migrations.AddConstraint(
            model_name='concessaocategoria',
            constraint=models.UniqueConstraint(fields=('concessao', 'categoria'), name='concessao_categoria_unico'),
        ),
        migrations.AddConstraint(
            model_name='concessao',
            constraint=models.CheckConstraint(condition=models.Q(('sub_area__isnull', True), ('fazenda__isnull', False), _connector='OR'), name='concessao_sub_area_exige_fazenda'),
        ),
        migrations.AddConstraint(
            model_name='concessao',
            constraint=models.CheckConstraint(condition=models.Q(('fim__isnull', True), ('fim__gt', models.F('inicio')), _connector='OR'), name='concessao_periodo_valido'),
        ),
        migrations.AddConstraint(
            model_name='concessao',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('revogada_em__isnull', True), ('revogada_por__isnull', True)), models.Q(('revogada_em__isnull', False), ('revogada_por__isnull', False)), _connector='OR'), name='concessao_revogacao_completa'),
        ),
        migrations.RunSQL(CRIAR, REMOVER),
    ]
