from django.db import models
from django.db.models import Q


class VersaoPacote(models.Model):
    """Uma versão do pacote offline de uma fazenda (004b R2, R20). Escopada por empresa, com RLS (migração 0001).

    O número é único por fazenda e uma só linha é `vigente` por fazenda: o banco garante os dois, não só `geracao.py`.
    O papel `app` só atualiza `vigente` (migração 0001): `manifesto` e `numero` nunca mudam depois de gravados."""

    empresa = models.ForeignKey('territorio.Empresa', on_delete=models.PROTECT, related_name='+')
    fazenda = models.ForeignKey('territorio.Fazenda', on_delete=models.PROTECT, related_name='+')
    numero = models.PositiveIntegerField()
    gerado_em = models.DateTimeField(auto_now_add=True)
    manifesto = models.JSONField()
    vigente = models.BooleanField(default=False)
    empresa_id: int  # anotações só para o pyright: o Django cria as colunas `<campo>_id`
    fazenda_id: int

    class Meta:
        db_table = 'versao_pacote'
        constraints = [
            models.UniqueConstraint(fields=['fazenda', 'numero'], name='versao_pacote_numero_unico'),
            models.UniqueConstraint(fields=['fazenda'], condition=Q(vigente=True), name='versao_pacote_uma_vigente'),
            models.CheckConstraint(condition=Q(numero__gte=1), name='versao_pacote_numero_positivo'),
        ]
