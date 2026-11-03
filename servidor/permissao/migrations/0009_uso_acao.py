# Contador de uso de atalho (003 R26). Primeira tabela com RLS por pessoa, não por escopo: a política exige a identidade
# assinada da 0004 (`app_identidade_ok`), então só a aplicação, dentro de `permissao.uso`, lê ou grava as linhas de
# uma pessoa. O dono das tabelas ignora a RLS (sem FORCE), como nas demais.
#
# Apagar a pessoa apaga as linhas (LGPD) por `ON DELETE CASCADE` no banco, que a RLS não barra. Uma política de DELETE
# para a plataforma não serve (medido): o DELETE com WHERE também exige poder ler a linha, e isso abriria o uso de
# todas as pessoas à plataforma.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# O papel `app` não executa `app_identidade_ok` (test_contexto): a política chama este invólucro, que só confere a
# identidade assinada da transação contra a pessoa da linha e não devolve nada além de verdadeiro ou falso.
FUNCAO = """
CREATE FUNCTION app_identidade_propria(pessoa bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT public.app_identidade_ok(pessoa)
$$
"""

POLITICAS = (
    "CREATE POLICY propria ON uso_acao FOR ALL USING (app_identidade_propria(pessoa_id))",
)


CHAVE = (
    'ALTER TABLE uso_acao ADD CONSTRAINT uso_acao_pessoa_fk FOREIGN KEY (pessoa_id) REFERENCES pessoa (id)'
    ' ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED'
)


def ligar_rls(apps, schema_editor):
    app = schema_editor.quote_name(settings.DATABASES['app']['USER'])
    schema_editor.execute(FUNCAO)
    schema_editor.execute('REVOKE ALL ON FUNCTION app_identidade_propria(bigint) FROM PUBLIC')
    schema_editor.execute(f'GRANT EXECUTE ON FUNCTION app_identidade_propria(bigint) TO {app}')
    schema_editor.execute('ALTER TABLE uso_acao ENABLE ROW LEVEL SECURITY')
    for politica in POLITICAS:
        schema_editor.execute(politica)


def desligar_rls(apps, schema_editor):
    schema_editor.execute('DROP POLICY propria ON uso_acao')
    schema_editor.execute('ALTER TABLE uso_acao DISABLE ROW LEVEL SECURITY')
    schema_editor.execute('DROP FUNCTION app_identidade_propria(bigint)')


class Migration(migrations.Migration):
    dependencies = [
        ('permissao', '0008_revogar_concessoes_duplicadas'),
        ('identidade', '0002_acesso_substituido_em'),
    ]
    operations = [
        migrations.CreateModel(
            name='UsoAcao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('acao', models.CharField(max_length=64)),
                ('contagem', models.PositiveIntegerField(default=0)),
                ('ultimo_uso', models.DateTimeField(blank=True, null=True)),
                ('fixado', models.BooleanField(default=False)),
                ('oculto', models.BooleanField(default=False)),
                ('pessoa', models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, db_constraint=False, related_name='+', to='identidade.pessoa')),
            ],
            options={'db_table': 'uso_acao'},
        ),
        migrations.AddConstraint(
            model_name='usoacao',
            constraint=models.UniqueConstraint(fields=('pessoa', 'acao'), name='uso_acao_unico'),
        ),
        migrations.RunSQL(CHAVE, 'ALTER TABLE uso_acao DROP CONSTRAINT uso_acao_pessoa_fk'),
        migrations.RunPython(ligar_rls, desligar_rls),
    ]
