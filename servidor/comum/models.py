from django.db import models
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Now


class EventoAuditoria(models.Model):
    """Ação administrativa relevante, só de acréscimo (R16; plan.md §Auditoria).

    O papel `app` recebe só INSERT e SELECT nesta tabela (migração 0002). `pessoa_id` é quem agiu (nulo para o
    sistema ou para quem ainda não se identificou, como a falha de login). Ids sem chave estrangeira: o registro
    sobrevive à pessoa ou à empresa apagadas, e o papel `app` não precisa de UPDATE para a chave estrangeira anular
    nada. `detalhes` nunca leva senha, token nem CPF em claro.
    """

    pessoa_id = models.BigIntegerField(null=True)
    acao = models.CharField(max_length=60)
    alvo_tipo = models.CharField(max_length=60, blank=True)
    alvo_id = models.BigIntegerField(null=True)
    empresa_id = models.BigIntegerField(null=True)
    detalhes = models.JSONField(default=dict)
    hora_servidor = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = 'evento_auditoria'
        # Leitura da auditoria (005 R8): cursor por id decrescente dentro de empresa, de quem agiu e da pessoa afetada.
        # `pessoa_id` nos `detalhes` guarda a pessoa afetada por eventos cujo alvo é outro objeto (concessão, convite).
        indexes = [
            models.Index(fields=['empresa_id', '-id'], name='auditoria_empresa_id'),
            models.Index(fields=['pessoa_id', '-id'], name='auditoria_pessoa_id'),
            models.Index(fields=['alvo_tipo', 'alvo_id'], name='auditoria_alvo'),
            models.Index(KeyTextTransform('pessoa_id', 'detalhes'), name='auditoria_detalhe_pessoa'),
        ]
