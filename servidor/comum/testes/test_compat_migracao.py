"""Compatibilidade expand-only das migrações (spec 009, R4, R5 e A4). Sem banco: o verificador só lê texto."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from comum.compat_migracao import (
    MARCADOR,
    TAMANHO_MAXIMO,
    ErroAnalise,
    analisar_arquivo,
    verificar_arquivo,
)

SERVIDOR = Path(__file__).resolve().parents[2]


def _fonte(*elementos, antes=''):
    ops = ''.join(f'        {e},\n' for e in elementos)
    return f'from django.db import migrations, models\n{antes}\n\nclass Migration(migrations.Migration):\n    operations = [\n{ops}    ]\n'


def _arquivo(tmp_path, conteudo, nome='0005_teste.py'):
    caminho = tmp_path / nome
    caminho.write_text(conteudo, encoding='utf-8')
    return caminho


def _verificar(tmp_path, *elementos, antes='', nome='0005_teste.py'):
    return verificar_arquivo(_arquivo(tmp_path, _fonte(*elementos, antes=antes), nome))


def _cli(*argumentos, diretorio=SERVIDOR):
    # `diretorio` é o diretório de trabalho do CLI: o CLI só analisa arquivo dentro dele, então os testes com tmp_path o passam.
    ambiente = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONPATH': str(SERVIDOR)}
    return subprocess.run(
        [sys.executable, '-m', 'comum.compat_migracao', *argumentos],
        cwd=diretorio, capture_output=True, text=True, encoding='utf-8', env=ambiente, timeout=60,
    )


# --- Caminho feliz: compatível ---------------------------------------------------------------------------------

@pytest.mark.parametrize('elemento', [
    "migrations.AddField(model_name='camada', name='descricao', field=models.TextField(null=True))",
    "migrations.AddField(model_name='camada', name='ordem', field=models.IntegerField(db_default=0))",
    "migrations.AddField(model_name='camada', name='tags', field=models.ManyToManyField(to='x.tag'))",
    "migrations.AddIndexConcurrently(model_name='camada', index=models.Index(fields=['nome'], name='camada_nome_idx'))",
    "migrations.CreateModel(name='Nova', fields=[('id', models.BigAutoField(primary_key=True))])",
    "migrations.AddIndex(model_name='camada', index=models.Index(fields=['nome'], name='camada_nome_idx'))",
    "migrations.AddConstraint(model_name='camada', constraint=models.UniqueConstraint(fields=['nome'], name='camada_nome_uq'))",
    "migrations.AlterModelOptions(name='camada', options={'ordering': ['nome']})",
    "migrations.RunSQL('CREATE INDEX camada_nome ON camada (nome)')",
    "migrations.RunSQL([('CREATE TABLE x (id int)', None)])",
    "migrations.RunSQL('DELETE FROM camada WHERE id = 1')",
    "migrations.RunSQL('CREATE TABLE x (id int)', reverse_sql='DROP TABLE x')",
    "migrations.RunSQL('ALTER TABLE camada ADD COLUMN ordem integer NULL')",
    "migrations.RunSQL('ALTER TABLE camada ADD COLUMN ordem integer NOT NULL DEFAULT 0')",
    "migrations.RunPython(carregar, migrations.RunPython.noop)",
])
def test_operacao_compativel_e_aprovada(tmp_path, elemento):
    antes = 'def carregar(apps, schema_editor):\n    pass\n'
    assert _verificar(tmp_path, elemento, antes=antes) == []


def test_migracao_sem_operacoes_e_aprovada(tmp_path):
    assert _verificar(tmp_path) == []


def test_run_python_que_so_le_e_aprovado(tmp_path):
    antes = 'def carregar(apps, schema_editor):\n    Camada = apps.get_model("camada", "Camada")\n    Camada.objects.filter(nome="x").update(ativo=True)\n'
    assert _verificar(tmp_path, 'migrations.RunPython(carregar)', antes=antes) == []


# --- Caminho infeliz: cada operação reprovada, com operação e motivo específicos -------------------------------

@pytest.mark.parametrize(('elemento', 'operacao', 'trecho'), [
    ("migrations.RemoveField(model_name='camada', name='nome')", 'RemoveField', 'remove coluna'),
    ("migrations.DeleteModel(name='Camada')", 'DeleteModel', 'apaga tabela'),
    ("migrations.RenameField(model_name='camada', old_name='a', new_name='b')", 'RenameField', 'renomeia coluna'),
    ("migrations.RenameModel(old_name='A', new_name='B')", 'RenameModel', 'renomeia tabela'),
    ("migrations.AlterField(model_name='camada', name='nome', field=models.CharField(max_length=10))", 'AlterField', 'altera campo'),
    ("migrations.AlterModelTable(name='camada', table='x')", 'AlterModelTable', 'troca o nome'),
    ("migrations.RemoveConstraint(model_name='camada', name='c')", 'RemoveConstraint', 'remove restrição'),
    ("migrations.RemoveIndex(model_name='camada', name='i')", 'RemoveIndex', 'remove índice'),
    ("migrations.AlterUniqueTogether(name='camada', unique_together={('a', 'b')})", 'AlterUniqueTogether', 'unicidade composta'),
    ("migrations.AlterIndexTogether(name='camada', index_together=set())", 'AlterIndexTogether', 'índice composto'),
])
def test_operacao_reprovada_aponta_operacao_e_motivo(tmp_path, elemento, operacao, trecho):
    (violacao,) = _verificar(tmp_path, elemento)
    assert violacao.operacao == operacao
    assert violacao.motivo.startswith(f'{operacao}: ')
    assert trecho in violacao.motivo
    assert violacao.linha == 6
    assert violacao.arquivo.endswith('0005_teste.py')


@pytest.mark.parametrize('elemento', [
    "migrations.AddField(model_name='camada', name='nome', field=models.CharField(max_length=10))",
    "migrations.AddField(model_name='camada', name='nome', field=models.CharField(max_length=10, null=False))",
    "migrations.AddField(model_name='camada', name='nome', field=models.IntegerField(default=None))",
    "migrations.AddField(model_name='camada', name='nome', field=models.IntegerField(null=flag))",
])
def test_addfield_not_null_sem_valor_e_reprovado(tmp_path, elemento):
    (violacao,) = _verificar(tmp_path, elemento)
    assert violacao.operacao == 'AddField'
    assert 'NOT NULL sem valor' in violacao.motivo


def test_addfield_default_sozinho_e_reprovado_com_motivo_proprio(tmp_path):
    (violacao,) = _verificar(tmp_path, "migrations.AddField(model_name='camada', name='ordem', field=models.IntegerField(default=0))")
    assert violacao.operacao == 'AddField'
    assert violacao.motivo == (
        'AddField: o default do Django não existe no banco: o INSERT da versão anterior quebra em NOT NULL (use db_default=)'
    )


def test_addfield_foreignkey_not_null_segue_a_regra_de_coluna(tmp_path):
    (violacao,) = _verificar(tmp_path, "migrations.AddField(model_name='camada', name='tema', field=models.ForeignKey(on_delete=models.CASCADE, to='x.tema'))")
    assert violacao.operacao == 'AddField'
    assert 'NOT NULL sem valor' in violacao.motivo


def test_addfield_com_campo_nao_analisavel_e_reprovado(tmp_path):
    (violacao,) = _verificar(tmp_path, "migrations.AddField(model_name='camada', name='x', field=CAMPO)")
    assert violacao.operacao == 'AddField'
    assert 'não analisável' in violacao.motivo


@pytest.mark.parametrize('sql', [
    'ALTER TABLE camada DROP COLUMN nome',
    'alter table camada rename column nome to x',
    'ALTER TABLE camada ALTER COLUMN nome SET NOT NULL',
    'ALTER TABLE camada ALTER COLUMN nome TYPE text',
    'ALTER TABLE camada ALTER nome TYPE text',
    'ALTER TABLE camada ADD COLUMN ordem integer NOT NULL',
    'ALTER TABLE camada ADD ordem integer NOT NULL',
    'ALTER TABLE camada ALTER COLUMN nome SET DATA TYPE text',
    'TRUNCATE camada',
    'DELETE FROM camada',
    'DELETE FROM camada; SELECT 1',
    'DROP\nTABLE camada',
])
def test_runsql_destrutivo_e_reprovado(tmp_path, sql):
    (violacao,) = _verificar(tmp_path, f'migrations.RunSQL({sql!r})')
    assert violacao.operacao == 'RunSQL'
    assert 'SQL destrutivo' in violacao.motivo


def test_runsql_add_column_not_null_sem_default_no_mesmo_comando_e_reprovado(tmp_path):
    # Só a própria coluna nova conta: o DEFAULT de outro comando não salva o ADD COLUMN.
    sql = 'ALTER TABLE camada ADD COLUMN ordem integer NOT NULL; ALTER TABLE x ADD COLUMN y integer DEFAULT 0'
    (violacao,) = _verificar(tmp_path, f'migrations.RunSQL({sql!r})')
    assert 'ADD COLUMN NOT NULL sem DEFAULT' in violacao.motivo


def test_runsql_destrutivo_em_lista_de_tuplas_e_reprovado(tmp_path):
    (violacao,) = _verificar(tmp_path, "migrations.RunSQL([('DROP TABLE x', None)])")
    assert 'DROP' in violacao.motivo


@pytest.mark.parametrize('sql_fonte', [
    'sql',
    "f'DROP TABLE {nome}'",
    "'DROP ' + 'TABLE x'",
    "monta_sql()",
])
def test_runsql_com_sql_nao_literal_e_reprovado(tmp_path, sql_fonte):
    (violacao,) = _verificar(tmp_path, f'migrations.RunSQL({sql_fonte})', antes='nome = "x"')
    assert violacao.operacao == 'RunSQL'
    assert 'não literal' in violacao.motivo


def test_runsql_no_reverso_nao_e_analisado(tmp_path):
    # Reverso não roda no fluxo de troca: DROP POLICY dele não pode reprovar a migração de RLS.
    assert _verificar(tmp_path, "migrations.RunSQL('CREATE POLICY p ON t', reverse_sql='DROP POLICY p ON t')") == []


@pytest.mark.parametrize('antes, elemento', [
    ('def carregar(apps, schema_editor):\n    Camada.objects.all().delete()\n', 'migrations.RunPython(carregar)'),
    ('def carregar(apps, schema_editor):\n    apps.get_model("c", "C").objects.filter(a=1).delete()\n', 'migrations.RunPython(carregar)'),
    ('def carregar(apps, schema_editor):\n    schema_editor.execute("DROP TABLE x")\n', 'migrations.RunPython(carregar)'),
    ('def carregar(apps, schema_editor):\n    schema_editor.execute("ALTER TABLE x RENAME TO y")\n', 'migrations.RunPython(carregar)'),
])
def test_runpython_que_apaga_ou_renomeia_e_reprovado(tmp_path, antes, elemento):
    (violacao,) = _verificar(tmp_path, elemento, antes=antes)
    assert violacao.operacao == 'RunPython'
    assert violacao.linha >= 1


def test_runpython_com_funcao_fora_do_arquivo_e_reprovado(tmp_path):
    (violacao,) = _verificar(tmp_path, 'migrations.RunPython(carregar)', antes='from outro import carregar')
    assert violacao.operacao == 'RunPython'
    assert 'não está no arquivo' in violacao.motivo


def test_runpython_com_funcao_nao_nomeada_e_reprovado(tmp_path):
    (violacao,) = _verificar(tmp_path, 'migrations.RunPython(lambda a, s: None)')
    assert violacao.operacao == 'RunPython'
    assert 'não referenciada por nome' in violacao.motivo


def test_operacao_nao_listada_e_reprovada(tmp_path):
    (violacao,) = _verificar(tmp_path, "migrations.RenameIndex(model_name='c', new_name='n', old_name='o')")
    assert violacao.operacao == 'RenameIndex'
    assert 'não listada' in violacao.motivo


def test_remove_index_concurrently_e_reprovado_como_remove_index(tmp_path):
    antes = 'from django.contrib.postgres.operations import RemoveIndexConcurrently'
    (violacao,) = _verificar(tmp_path, "RemoveIndexConcurrently(model_name='c', name='i')", antes=antes)
    assert violacao.operacao == 'RemoveIndexConcurrently'
    assert 'remove índice' in violacao.motivo


def test_operacao_do_contrib_postgres_fora_da_lista_e_reprovada(tmp_path):
    antes = 'from django.contrib.postgres.operations import BtreeIndexOp'
    (violacao,) = _verificar(tmp_path, "BtreeIndexOp(model_name='c')", antes=antes)
    assert violacao.operacao == 'BtreeIndexOp'
    assert 'não listada' in violacao.motivo


def test_constante_literal_de_modulo_em_runsql_e_analisada(tmp_path):
    antes = 'CRIAR = "CREATE INDEX i ON x (a)"\nLISTA = (("CREATE TABLE y (id int)", None),)'
    assert _verificar(tmp_path, 'migrations.RunSQL(CRIAR)', 'migrations.RunSQL(LISTA)', antes=antes) == []


def test_constante_lista_mutavel_nao_e_resolvida_mesmo_sem_reatribuicao(tmp_path):
    # `.append` não é reatribuição: a lista mutada com DROP não pode ser lida como a constante original.
    antes = 'LISTA = [("CREATE TABLE y (id int)", None)]\nLISTA.append(("DROP TABLE x", None))'
    (violacao,) = _verificar(tmp_path, 'migrations.RunSQL(LISTA)', antes=antes)
    assert violacao.operacao == 'RunSQL'
    assert 'não literal' in violacao.motivo


def test_constante_literal_com_drop_e_reprovada(tmp_path):
    (violacao,) = _verificar(tmp_path, 'migrations.RunSQL(DESFAZER)', antes='DESFAZER = "DROP TABLE x"')
    assert violacao.operacao == 'RunSQL'
    assert 'SQL destrutivo' in violacao.motivo


@pytest.mark.parametrize('antes', [
    'CRIAR = monta()',
    'CRIAR = "CREATE TABLE x"\nCRIAR = "DROP TABLE x"',
    'CRIAR = "CREATE TABLE x (" + "id int)"',
])
def test_constante_nao_literal_ou_reatribuida_e_reprovada(tmp_path, antes):
    (violacao,) = _verificar(tmp_path, 'migrations.RunSQL(CRIAR)', antes=antes)
    assert violacao.operacao == 'RunSQL'
    assert 'não literal' in violacao.motivo


def test_separate_reprova_remocao_em_database_operations(tmp_path):
    elemento = "migrations.SeparateDatabaseAndState(database_operations=[migrations.RemoveField(model_name='c', name='n')])"
    (violacao,) = _verificar(tmp_path, elemento)
    assert violacao.operacao == 'RemoveField'


def test_separate_posicional_reprova_remocao_em_database_operations(tmp_path):
    # Django aceita database_operations como primeiro argumento posicional.
    elemento = "migrations.SeparateDatabaseAndState([migrations.RemoveField(model_name='c', name='n')])"
    (violacao,) = _verificar(tmp_path, elemento)
    assert violacao.operacao == 'RemoveField'


def test_separate_posicional_reprova_drop_em_runsql(tmp_path):
    (violacao,) = _verificar(tmp_path, "migrations.SeparateDatabaseAndState([migrations.RunSQL('DROP TABLE camada')])")
    assert violacao.operacao == 'RunSQL'
    assert 'SQL destrutivo' in violacao.motivo


def test_separate_posicional_em_state_operations_e_ignorado(tmp_path):
    # Segundo posicional é state_operations: só mexe no estado do Django, não no banco.
    elemento = "migrations.SeparateDatabaseAndState(None, [migrations.RemoveField(model_name='c', name='n')])"
    assert _verificar(tmp_path, elemento) == []


def test_separate_ignora_state_operations(tmp_path):
    elemento = (
        "migrations.SeparateDatabaseAndState("
        "state_operations=[migrations.RemoveField(model_name='c', name='n')], "
        "database_operations=[migrations.AddField(model_name='c', name='n', field=models.TextField(null=True))])"
    )
    assert _verificar(tmp_path, elemento) == []


def test_separate_com_database_operations_nao_literal_e_reprovado(tmp_path):
    elemento = 'migrations.SeparateDatabaseAndState(database_operations=OPS)'
    (violacao,) = _verificar(tmp_path, elemento, antes='OPS = []')
    assert 'não literal' in violacao.motivo


# --- Estrutura da migração que não se analisa -----------------------------------------------------------------

def test_operations_montada_por_codigo_e_reprovada(tmp_path):
    conteudo = (
        'from django.db import migrations, models\n'
        'class Migration(migrations.Migration):\n'
        '    operations = [migrations.CreateModel(name="A", fields=[])] + [migrations.RemoveField(model_name="a", name="b")]\n'
    )
    (violacao,) = verificar_arquivo(_arquivo(tmp_path, conteudo))
    assert violacao.operacao == '(operations)'
    assert 'montada' in violacao.motivo


def test_operations_aumentada_com_mais_e_reprovada(tmp_path):
    conteudo = (
        'from django.db import migrations\n'
        'class Migration(migrations.Migration):\n'
        '    operations = []\n'
        '    operations += [migrations.RemoveField(model_name="a", name="b")]\n'
    )
    assert verificar_arquivo(_arquivo(tmp_path, conteudo))[0].operacao == '(operations)'


def test_operations_dentro_de_condicional_e_reprovada(tmp_path):
    conteudo = (
        'from django.db import migrations\n'
        'import os\n'
        'if os.environ.get("X"):\n'
        '    class Migration(migrations.Migration):\n'
        '        operations = [migrations.RemoveField(model_name="a", name="b")]\n'
    )
    (violacao,) = verificar_arquivo(_arquivo(tmp_path, conteudo))
    assert violacao.operacao == '(migração)'
    assert 'sem class Migration' in violacao.motivo


def test_operacao_em_lista_condicional_com_estrela_e_reprovada(tmp_path):
    (violacao,) = _verificar(tmp_path, '*([migrations.RemoveField(model_name="a", name="b")] if FLAG else [])', antes='FLAG = 1')
    assert violacao.operacao == '(operação)'
    assert 'não analisável' in violacao.motivo


def test_elemento_que_nao_e_chamada_e_reprovado(tmp_path):
    (violacao,) = _verificar(tmp_path, '[migrations.RemoveField(model_name="a", name="b") for _ in range(2)]')
    assert violacao.operacao == '(operação)'


def test_operacao_com_args_estrelados_e_reprovada(tmp_path):
    (violacao,) = _verificar(tmp_path, 'migrations.AddField(*ARGS)', antes='ARGS = []')
    assert violacao.operacao == 'AddField'
    assert '*args' in violacao.motivo


def test_operations_com_valor_nao_literal_e_reprovada(tmp_path):
    conteudo = 'from django.db import migrations\nclass Migration(migrations.Migration):\n    operations = OPS if X else []\n'
    (violacao,) = verificar_arquivo(_arquivo(tmp_path, conteudo))
    assert violacao.operacao == '(operations)'


def test_migracao_sem_operations_e_reprovada(tmp_path):
    conteudo = 'from django.db import migrations\nclass Migration(migrations.Migration):\n    dependencies = []\n'
    (violacao,) = verificar_arquivo(_arquivo(tmp_path, conteudo))
    assert violacao.operacao == '(operations)'
    assert 'ausente' in violacao.motivo


# --- Migração inicial (0001 ou initial = True) ----------------------------------------------------------------

_NOVA_COM_FK_NOT_NULL = (
    "migrations.CreateModel(name='Estudo', fields=[('id', models.BigAutoField(primary_key=True))])",
    "migrations.AddField(model_name='estudo', name='tema', field=models.ForeignKey(on_delete=models.CASCADE, to='x.tema'))",
)


def test_inicial_aprova_addfield_not_null_em_modelo_criado_no_mesmo_arquivo(tmp_path):
    assert _verificar(tmp_path, *_NOVA_COM_FK_NOT_NULL, nome='0001_initial.py') == []


def test_inicial_marcada_por_atributo_tambem_aprova(tmp_path):
    conteudo = _fonte(*_NOVA_COM_FK_NOT_NULL).replace('class Migration(migrations.Migration):', 'class Migration(migrations.Migration):\n    initial = True')
    assert verificar_arquivo(_arquivo(tmp_path, conteudo, nome='0007_qualquer.py')) == []


def test_mesma_addfield_fora_da_inicial_e_reprovada(tmp_path):
    (violacao,) = _verificar(tmp_path, *_NOVA_COM_FK_NOT_NULL, nome='0005_teste.py')
    assert violacao.operacao == 'AddField'


def test_inicial_reprova_addfield_em_modelo_que_nao_foi_criado_no_arquivo(tmp_path):
    (violacao,) = _verificar(
        tmp_path,
        "migrations.AddField(model_name='camada', name='tema', field=models.ForeignKey(on_delete=models.CASCADE, to='x.tema'))",
        nome='0001_initial.py',
    )
    assert violacao.operacao == 'AddField'


def test_inicial_reprova_addfield_antes_do_createmodel_da_tabela(tmp_path):
    # A ordem importa: a tabela só conta como criada depois do CreateModel.
    antes_do_create = (_NOVA_COM_FK_NOT_NULL[1], _NOVA_COM_FK_NOT_NULL[0])
    (violacao,) = _verificar(tmp_path, *antes_do_create, nome='0001_initial.py')
    assert violacao.operacao == 'AddField'


def test_inicial_reprova_addfield_quando_tabela_so_esta_em_state_operations(tmp_path):
    # state_operations mexe só no estado do Django: a tabela não foi criada no banco.
    criacao_so_no_estado = f"migrations.SeparateDatabaseAndState(state_operations=[{_NOVA_COM_FK_NOT_NULL[0]}])"
    (violacao,) = _verificar(tmp_path, criacao_so_no_estado, _NOVA_COM_FK_NOT_NULL[1], nome='0001_initial.py')
    assert violacao.operacao == 'AddField'


def test_inicial_aprova_addfield_apos_createmodel_em_database_operations(tmp_path):
    criacao_no_banco = f"migrations.SeparateDatabaseAndState(database_operations=[{_NOVA_COM_FK_NOT_NULL[0]}])"
    assert _verificar(tmp_path, criacao_no_banco, _NOVA_COM_FK_NOT_NULL[1], nome='0001_initial.py') == []


def test_inicial_nao_relaxa_remocao(tmp_path):
    (violacao,) = _verificar(tmp_path, "migrations.RemoveField(model_name='estudo', name='x')", nome='0001_initial.py')
    assert violacao.operacao == 'RemoveField'


# --- Borda e hostil: falha fechada ----------------------------------------------------------------------------

def test_arquivo_vazio_nao_e_migracao_e_reprova(tmp_path):
    (violacao,) = verificar_arquivo(_arquivo(tmp_path, ''))
    assert violacao.operacao == '(migração)'
    assert 'sem class Migration' in violacao.motivo


@pytest.mark.parametrize('conteudo', ['def (', 'x = 1\x00\n', 'class A\n', 'x = f(a=1, a=2)\n'])
def test_sintaxe_ou_byte_nulo_levanta_erro_de_analise(tmp_path, conteudo):
    caminho = _arquivo(tmp_path, conteudo)
    with pytest.raises(ErroAnalise):
        verificar_arquivo(caminho)


def test_codificacao_invalida_levanta_erro_de_analise(tmp_path):
    caminho = tmp_path / '0005_teste.py'
    caminho.write_bytes(b'\xff\xfe\x00 invalido')
    with pytest.raises(ErroAnalise):
        verificar_arquivo(caminho)


def test_arquivo_inexistente_levanta_erro_de_analise(tmp_path):
    with pytest.raises(ErroAnalise, match='ilegível'):
        verificar_arquivo(tmp_path / 'nao_existe.py')


def test_diretorio_levanta_erro_de_analise(tmp_path):
    with pytest.raises(ErroAnalise):
        verificar_arquivo(tmp_path)


def test_arquivo_acima_do_teto_levanta_erro_sem_analisar(tmp_path):
    caminho = tmp_path / '0005_teste.py'
    caminho.write_bytes(b'#' * (TAMANHO_MAXIMO + 1))
    with pytest.raises(ErroAnalise, match='acima de'):
        verificar_arquivo(caminho)


def test_caminho_com_ponto_ponto_e_analisado_pelo_arquivo_real(tmp_path):
    (tmp_path / 'sub').mkdir()
    _arquivo(tmp_path, _fonte("migrations.RemoveField(model_name='a', name='b')"))
    (violacao,) = verificar_arquivo(tmp_path / 'sub' / '..' / '0005_teste.py')
    assert violacao.operacao == 'RemoveField'


def test_caminho_com_ponto_ponto_inexistente_levanta_erro(tmp_path):
    with pytest.raises(ErroAnalise):
        verificar_arquivo(tmp_path / 'sub' / '..' / 'nao_existe.py')


def test_marcador_em_string_nao_conta_como_comentario(tmp_path):
    conteudo = _fonte("migrations.RemoveField(model_name='a', name='b')", antes=f'TEXTO = "{MARCADOR}"')
    resultado = analisar_arquivo(_arquivo(tmp_path, conteudo))
    assert resultado.marcado is False
    assert len(resultado.violacoes) == 1


# --- CLI: códigos de saída e formato da saída -----------------------------------------------------------------

def test_cli_aprova_com_rc_0_e_imprime_ok(tmp_path):
    arquivo = _arquivo(tmp_path, _fonte("migrations.AddField(model_name='a', name='b', field=models.TextField(null=True))"))
    saida = _cli(str(arquivo), diretorio=tmp_path)
    assert (saida.returncode, saida.stdout.strip()) == (0, f'OK {arquivo.resolve()}')


def test_cli_reprova_com_rc_1_e_formato_da_linha(tmp_path):
    arquivo = _arquivo(tmp_path, _fonte("migrations.RemoveField(model_name='a', name='b')"))
    saida = _cli(str(arquivo), diretorio=tmp_path)
    assert saida.returncode == 1
    assert saida.stdout.startswith(f'REPROVADA {arquivo.resolve()}:6 RemoveField: ')


def test_cli_caminho_relativo_dentro_do_diretorio_e_analisado(tmp_path):
    _arquivo(tmp_path, _fonte("migrations.RemoveField(model_name='a', name='b')"))
    esperado = (tmp_path / '0005_teste.py').resolve()
    saida = _cli('0005_teste.py', diretorio=tmp_path)
    assert saida.returncode == 1
    assert saida.stdout.startswith(f'REPROVADA {esperado}:6 RemoveField: ')


def test_cli_recusa_caminho_com_ponto_ponto_fora_do_diretorio(tmp_path):
    # Caso negativo: `../fora.py` existe e reprovaria (rc 1); o CLI tem de recusar antes de ler (rc 2).
    trabalho = tmp_path / 'trabalho'
    trabalho.mkdir()
    _arquivo(tmp_path, _fonte("migrations.RemoveField(model_name='a', name='b')"), 'fora.py')
    saida = _cli('../fora.py', diretorio=trabalho)
    assert saida.returncode == 2
    assert 'fora do diretório de trabalho' in saida.stderr
    assert saida.stdout == ''


def test_cli_recusa_arquivo_que_nao_e_py(tmp_path):
    # Caso negativo: texto sem `.py` não é migração; o CLI recusa o tipo antes de ler (rc 2).
    segredo = tmp_path / 'notas.txt'
    segredo.write_text('x = 1\n', encoding='utf-8')
    saida = _cli(str(segredo), diretorio=tmp_path)
    assert saida.returncode == 2
    assert 'só arquivo .py' in saida.stderr


@pytest.mark.parametrize('conteudo', ['def (', '', 'x = f(a=1, a=2)\n'])
def test_cli_sintaxe_rc_2_e_arquivo_vazio_rc_1(tmp_path, conteudo):
    arquivo = _arquivo(tmp_path, conteudo)
    esperado = 2 if conteudo else 1
    assert _cli(str(arquivo), diretorio=tmp_path).returncode == esperado


def test_cli_arquivo_inexistente_rc_2(tmp_path):
    saida = _cli(str(tmp_path / 'nao_existe.py'), diretorio=tmp_path)
    assert saida.returncode == 2
    assert 'ERRO' in saida.stderr


def test_cli_sem_argumento_rc_2():
    assert _cli().returncode == 2


def test_cli_marcador_com_reprovada_rc_3_e_fora_do_fluxo(tmp_path):
    conteudo = _fonte("migrations.RemoveField(model_name='a', name='b')").replace('class Migration', f'{MARCADOR}\nclass Migration')
    arquivo = _arquivo(tmp_path, conteudo)
    saida = _cli(str(arquivo), diretorio=tmp_path)
    assert saida.returncode == 3
    assert saida.stdout.startswith(f'FORA_DO_FLUXO {arquivo.resolve()}')


def test_cli_marcador_com_aprovada_continua_ok(tmp_path):
    conteudo = _fonte("migrations.AddField(model_name='a', name='b', field=models.TextField(null=True))").replace('class Migration', f'{MARCADOR}\nclass Migration')
    assert _cli(str(_arquivo(tmp_path, conteudo)), diretorio=tmp_path).returncode == 0


def test_cli_marcador_com_erro_de_sintaxe_continua_rc_2(tmp_path):
    arquivo = _arquivo(tmp_path, f'{MARCADOR}\ndef (')
    assert _cli(str(arquivo), diretorio=tmp_path).returncode == 2


def test_cli_lote_misto_reprovada_vence_fora_do_fluxo(tmp_path):
    ok = _arquivo(tmp_path, _fonte("migrations.AddField(model_name='a', name='b', field=models.TextField(null=True))"), 'a.py')
    marcada = _arquivo(tmp_path, _fonte("migrations.RemoveField(model_name='a', name='b')").replace('class Migration', f'{MARCADOR}\nclass Migration'), 'b.py')
    reprovada = _arquivo(tmp_path, _fonte("migrations.RemoveField(model_name='a', name='b')"), 'c.py')
    assert _cli(str(ok), str(marcada), diretorio=tmp_path).returncode == 3
    assert _cli(str(ok), str(marcada), str(reprovada), diretorio=tmp_path).returncode == 1


def test_cli_lote_com_erro_vence_reprovada(tmp_path):
    reprovada = _arquivo(tmp_path, _fonte("migrations.RemoveField(model_name='a', name='b')"), 'a.py')
    erro = _arquivo(tmp_path, 'def (', 'b.py')
    assert _cli(str(reprovada), str(erro), diretorio=tmp_path).returncode == 2


# --- Migração 0001 do catálogo (R5: o implantar a verifica pelo CLI, a partir de `servidor/`) -----------------

def test_migracao_0001_do_catalogo_e_compativel_pelo_cli():
    # Se a 0001 reprovar, a implantação recusa o SHA: este teste falha antes disso.
    assert (SERVIDOR / 'catalogo' / 'migrations' / '0001_initial.py').is_file()
    resultado = _cli('catalogo/migrations/0001_initial.py')
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert resultado.stdout.startswith('OK ')
    assert resultado.stdout.rstrip().endswith('0001_initial.py')


# --- Migrações reais do repositório (informação: o teste não exige que todas passem) -------------------------

def test_migracoes_reais_sao_analisadas_sem_erro():
    arquivos = sorted(p for p in SERVIDOR.glob('*/migrations/*.py') if p.name != '__init__.py')
    assert arquivos, 'nenhuma migração encontrada: o teste não está olhando o lugar certo'
    linhas = []
    for arquivo in arquivos:
        nome = arquivo.relative_to(SERVIDOR).as_posix()
        resultado = analisar_arquivo(arquivo)  # levantar aqui seria erro de análise de migração real
        if not resultado.violacoes:
            linhas.append(f'OK {nome}')
        else:
            estado = 'FORA_DO_FLUXO' if resultado.marcado else 'REPROVADA'
            linhas.append(f'{estado} {nome} :: ' + ' | '.join(f'{v.linha} {v.motivo}' for v in resultado.violacoes))
    print('\n'.join(linhas))


def test_subclasse_unaccent_sem_volta_e_aprovada(tmp_path):
    antes = (
        'from django.contrib.postgres.operations import UnaccentExtension\n\n'
        'class ExtensaoUnaccentSemVolta(UnaccentExtension):\n    pass\n'
    )
    assert _verificar(tmp_path, 'ExtensaoUnaccentSemVolta()', antes=antes) == []


def test_unaccent_do_django_sem_subclasse_e_reprovada(tmp_path):
    # O reverso da classe de Django faz DROP EXTENSION: sem subclasse que apague a volta, não é aprovada.
    antes = 'from django.contrib.postgres.operations import UnaccentExtension'
    (violacao,) = _verificar(tmp_path, 'UnaccentExtension()', antes=antes)
    assert violacao.operacao == 'UnaccentExtension'
    assert 'não listada' in violacao.motivo


def test_operacao_desconhecida_do_contrib_postgres_continua_reprovada(tmp_path):
    antes = 'from django.contrib.postgres.operations import TrigramExtension'
    (violacao,) = _verificar(tmp_path, 'TrigramExtension()', antes=antes)
    assert violacao.operacao == 'TrigramExtension'
    assert 'não listada' in violacao.motivo
