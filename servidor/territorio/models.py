from django.db import models
from django.db.models import Q


class Arquivavel(models.Model):
    """Arquivar (R11): não há exclusão. As três colunas andam juntas (restrição `<tabela>_arquivamento_coerente`);
    `arquivamento` identifica o ato, para desarquivar restaurar só os filhos arquivados por ele."""

    arquivada_em = models.DateTimeField(null=True, blank=True)
    arquivada_por = models.ForeignKey('identidade.Pessoa', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    arquivamento = models.UUIDField(null=True, blank=True)
    arquivada_por_id: int | None  # anotação só para o pyright

    class Meta:
        abstract = True


def _arquivamento_coerente(tabela):
    todas_nulas = Q(arquivada_em__isnull=True, arquivada_por__isnull=True, arquivamento__isnull=True)
    todas_preenchidas = Q(arquivada_em__isnull=False, arquivada_por__isnull=False, arquivamento__isnull=False)
    return models.CheckConstraint(condition=todas_nulas | todas_preenchidas, name=f'{tabela}_arquivamento_coerente')


class Empresa(Arquivavel):
    nome = models.CharField(max_length=200)
    criada_em = models.DateTimeField(auto_now_add=True)
    # Administrador titular (R23): o primeiro, criado com a empresa. Só sai por transferência de titularidade
    # (permissao.delegacao). Nulo só no instante entre criar a empresa e convidar o titular, na mesma transação.
    titular = models.ForeignKey('identidade.Pessoa', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    titular_id: int | None  # anotação só para o pyright

    def __str__(self):
        return self.nome

    class Meta(Arquivavel.Meta):
        db_table = 'empresa'
        constraints = [_arquivamento_coerente('empresa')]


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


class Fazenda(Arquivavel):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT)
    nome = models.CharField(max_length=200)
    criada_em = models.DateTimeField(auto_now_add=True)
    empresa_id: int  # anotação só para o pyright: o Django cria a coluna `empresa_id`

    def __str__(self):
        return self.nome

    class Meta(Arquivavel.Meta):
        db_table = 'fazenda'
        constraints = [
            _arquivamento_coerente('fazenda'),
            # Alvo da chave estrangeira composta de sub_area (migração 0001): fazenda e empresa andam juntas.
            models.UniqueConstraint(fields=['id', 'empresa'], name='fazenda_id_empresa_unico'),
        ]


class SubArea(Arquivavel):
    """Nó da divisão da fazenda, até 3 níveis.

    `caminho` guarda os ids dos ancestrais ('/' na raiz, '/1/5/' no neto do nó 1 via nó 5).
    Coerência de empresa/fazenda (chave composta) e de nível/pai/caminho (gatilho) é garantida
    no banco (migração 0001), não só por esta classe.
    """

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT)
    fazenda = models.ForeignKey(Fazenda, on_delete=models.PROTECT)
    pai = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT)
    nivel = models.PositiveSmallIntegerField()
    nome = models.CharField(max_length=200)
    caminho = models.TextField(default='/', editable=False)
    empresa_id: int  # anotações só para o pyright: o Django cria as colunas `<campo>_id`
    fazenda_id: int

    def __str__(self):
        return self.nome

    class Meta(Arquivavel.Meta):
        db_table = 'sub_area'
        constraints = [
            _arquivamento_coerente('sub_area'),
            models.CheckConstraint(condition=Q(nivel__gte=1, nivel__lte=3), name='sub_area_nivel_1_a_3'),
            models.CheckConstraint(
                condition=Q(nivel=1, pai__isnull=True) | Q(nivel__gt=1, pai__isnull=False),
                name='sub_area_raiz_sem_pai',
            ),
            # Alvo da chave estrangeira composta de concessao (permissao 0002): sub-área e fazenda da concessão andam juntas.
            models.UniqueConstraint(fields=['id', 'fazenda'], name='sub_area_id_fazenda_unico'),
        ]
