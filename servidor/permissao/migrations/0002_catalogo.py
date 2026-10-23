from django.conf import settings
from django.db import migrations

# Cópia congelada do catálogo (plan.md §Catálogo de ações): migração não importa código que evolui.
# (codigo, descricao, delegavel)
ACOES = [
    ('ver', 'Ver o território e seus dados', True),
    ('baixar_pacote_offline', 'Baixar o pacote offline', True),
    ('baixar_documento', 'Baixar documento', True),
    ('criar_registro_campo', 'Criar registro de campo', True),
    ('propor_alteracao_atributo', 'Propor alteração de atributo', True),
    ('revisar_trabalho_de_outro', 'Revisar trabalho de outra pessoa', True),
    ('validar_registro', 'Validar registro de campo', True),
    ('validar_atributo', 'Validar atributo', True),
    ('conferir_revisao_enviada', 'Conferir revisão enviada', True),
    ('enviar_revisao_camada', 'Enviar revisão de camada', True),
    ('aprovar_atributo', 'Aprovar atributo', True),
    ('aprovar_geometria', 'Aprovar geometria', False),
    ('tornar_revisao_vigente', 'Tornar revisão vigente', False),
    ('publicar_camada', 'Publicar camada', True),
    ('subir_documento', 'Subir documento', True),
    ('definir_validade_documento', 'Definir validade de documento', True),
    ('convidar_pessoa', 'Convidar pessoa', True),
    ('revogar_acesso', 'Revogar acesso', True),
    ('redefinir_senha', 'Iniciar redefinição de senha de outra pessoa', True),
    ('configurar_prazos_escalada', 'Configurar prazos de escalada', True),
    ('configurar_categorias_campos', 'Configurar categorias e campos', True),
    ('configurar_niveis_divisao', 'Configurar níveis da divisão da fazenda', True),
    ('ajustar_expiracao_pacote', 'Ajustar expiração do pacote offline', True),
    ('criar_empresa', 'Criar empresa (só o Administrador da plataforma)', False),
    ('criar_fazenda', 'Criar fazenda', True),
    ('criar_sub_area', 'Criar sub-área', True),
    ('gerenciar_cargo', 'Criar e alterar cargo', True),
]


def carregar(apps, schema_editor):
    Permissao = apps.get_model('permissao', 'Permissao')
    Permissao.objects.bulk_create(Permissao(codigo=c, descricao=d, delegavel=g) for c, d, g in ACOES)
    # O catálogo só cresce por migração: o papel da aplicação lê, não escreve (achado do CodeRabbit, PR #1).
    app = schema_editor.quote_name(settings.DATABASES['app']['USER'])
    schema_editor.execute(f'REVOKE INSERT, UPDATE, DELETE ON permissao FROM {app}')


def descarregar(apps, schema_editor):
    # Só as ações desta migração; código acrescentado por migração posterior sai na reversão dela.
    apps.get_model('permissao', 'Permissao').objects.filter(codigo__in=[c for c, _, _ in ACOES]).delete()


class Migration(migrations.Migration):
    dependencies = [('permissao', '0001_initial')]
    operations = [migrations.RunPython(carregar, descarregar)]
