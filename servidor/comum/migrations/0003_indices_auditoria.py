from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models
from django.db.models.fields.json import KeyTextTransform


class Migration(migrations.Migration):
    # `CREATE INDEX CONCURRENTLY` não roda em transação: a auditoria segue recebendo gravação enquanto os índices nascem
    # (Sourcery, PR #55). Reverso: `RemoveIndexConcurrently`, que o Django deriva sozinho.
    atomic = False

    dependencies = [
        ('comum', '0002_evento_auditoria'),
    ]

    operations = [
        AddIndexConcurrently('eventoauditoria', models.Index(fields=['empresa_id', '-id'], name='auditoria_empresa_id')),
        AddIndexConcurrently('eventoauditoria', models.Index(fields=['pessoa_id', '-id'], name='auditoria_pessoa_id')),
        AddIndexConcurrently('eventoauditoria', models.Index(fields=['alvo_tipo', 'alvo_id'], name='auditoria_alvo')),
        AddIndexConcurrently(
            'eventoauditoria', models.Index(KeyTextTransform('pessoa_id', 'detalhes'), name='auditoria_detalhe_pessoa'),
        ),
        AddIndexConcurrently('eventoauditoria', models.Index(KeyTextTransform('de', 'detalhes'), name='auditoria_detalhe_de')),
        AddIndexConcurrently('eventoauditoria', models.Index(fields=['acao', '-id'], name='auditoria_acao_id')),
        AddIndexConcurrently('eventoauditoria', models.Index(fields=['hora_servidor'], name='auditoria_hora')),
    ]
