from django.db import models
from django.db.models import Q


class Empresa(models.Model):
    nome = models.CharField(max_length=200)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'empresa'


class NivelDivisao(models.Model):
    """Nome do nível da divisão da fazenda, por empresa (padrão gleba e talhão; R7)."""

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT)
    nivel = models.PositiveSmallIntegerField()
    nome = models.CharField(max_length=100)

    class Meta:
        db_table = 'nivel_divisao'
        constraints = [
            models.CheckConstraint(condition=Q(nivel__gte=1, nivel__lte=3), name='nivel_divisao_nivel_1_a_3'),
            models.UniqueConstraint(fields=['empresa', 'nivel'], name='nivel_divisao_unico_por_empresa'),
        ]


class Fazenda(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT)
    nome = models.CharField(max_length=200)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fazenda'
        constraints = [
            # Alvo da chave estrangeira composta de sub_area (migração 0002): fazenda e empresa andam juntas.
            models.UniqueConstraint(fields=['id', 'empresa'], name='fazenda_id_empresa_unico'),
        ]


class SubArea(models.Model):
    """Nó da divisão da fazenda, até 3 níveis.

    `caminho` guarda os ids dos ancestrais ('/' na raiz, '/1/5/' no neto do nó 1 via nó 5).
    Coerência de empresa/fazenda (chave composta) e de nível/pai/caminho (gatilho) é garantida
    no banco (migração 0002), não só por esta classe.
    """

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT)
    fazenda = models.ForeignKey(Fazenda, on_delete=models.PROTECT)
    pai = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT)
    nivel = models.PositiveSmallIntegerField()
    nome = models.CharField(max_length=200)
    caminho = models.TextField(default='/', editable=False)

    class Meta:
        db_table = 'sub_area'
        constraints = [
            models.CheckConstraint(condition=Q(nivel__gte=1, nivel__lte=3), name='sub_area_nivel_1_a_3'),
            models.CheckConstraint(
                condition=Q(nivel=1, pai__isnull=True) | Q(nivel__gt=1, pai__isnull=False),
                name='sub_area_raiz_sem_pai',
            ),
        ]
