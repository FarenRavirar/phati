from django.db import models
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
