from django.db import models
from django.db.models import Q
from django.utils import timezone


class Permissao(models.Model):
    """Ação do catálogo fixo (R8). Cresce só por migração (risco R-7 da spec)."""

    codigo = models.CharField(max_length=64, primary_key=True)
    descricao = models.CharField(max_length=200)
    delegavel = models.BooleanField()

    class Meta:
        db_table = 'permissao'


# Nível hierárquico do cargo (R8, R10): quem convida só alcança cargo de nível estritamente abaixo do seu.
NIVEL_DA_BASE = {'usuario': 1, 'tecnico': 2, 'curador': 3, 'administrador': 4}
# Só estes dois níveis têm categoria de dado na concessão (D035).
BASES_COM_CATEGORIA = ('tecnico', 'usuario')


class Cargo(models.Model):
    """Conjunto de permissões, por empresa (R8). `base` e `empresa` não mudam depois de criados (gatilho na migração
    0002): trocar a base sob concessões já feitas mudaria a hierarquia de convite e as categorias em silêncio."""

    empresa = models.ForeignKey('territorio.Empresa', on_delete=models.PROTECT)
    nome = models.CharField(max_length=100)
    base = models.CharField(max_length=20, choices=[(base, base) for base in NIVEL_DA_BASE])
    empresa_id: int  # anotação só para o pyright
    permissoes = models.ManyToManyField(Permissao, through='CargoPermissao')

    class Meta:
        db_table = 'cargo'
        constraints = [
            models.CheckConstraint(condition=Q(base__in=list(NIVEL_DA_BASE)), name='cargo_base_valida'),
            models.UniqueConstraint(fields=['empresa', 'nome'], name='cargo_nome_unico_por_empresa'),
            # Alvo da chave estrangeira composta de concessao (migração 0002): o cargo é da empresa da concessão.
            models.UniqueConstraint(fields=['id', 'empresa'], name='cargo_id_empresa_unico'),
        ]


class CargoPermissao(models.Model):
    cargo = models.ForeignKey(Cargo, on_delete=models.CASCADE)
    permissao = models.ForeignKey(Permissao, on_delete=models.PROTECT)

    class Meta:
        db_table = 'cargo_permissao'
        constraints = [models.UniqueConstraint(fields=['cargo', 'permissao'], name='cargo_permissao_unico')]


class CategoriaDado(models.Model):
    """Categoria de dado, eixo da concessão de Técnico e Usuário (D035). Lista mínima nesta spec."""

    empresa = models.ForeignKey('territorio.Empresa', on_delete=models.PROTECT)
    nome = models.CharField(max_length=100)

    class Meta:
        db_table = 'categoria_dado'
        constraints = [models.UniqueConstraint(fields=['empresa', 'nome'], name='categoria_dado_nome_unico_por_empresa')]


class Concessao(models.Model):
    """Pessoa + cargo + escopo (empresa, fazenda ou sub-área) + categorias + período (R9).

    Coerência de empresa/fazenda/sub-área/cargo (chaves compostas) e imutabilidade fora de `fim` e da revogação
    (gatilho) são garantidas no banco (migração 0002), não só por esta classe.
    """

    pessoa = models.ForeignKey('identidade.Pessoa', on_delete=models.PROTECT)
    cargo = models.ForeignKey(Cargo, on_delete=models.PROTECT)
    empresa = models.ForeignKey('territorio.Empresa', on_delete=models.PROTECT)
    fazenda = models.ForeignKey('territorio.Fazenda', null=True, blank=True, on_delete=models.PROTECT)
    sub_area = models.ForeignKey('territorio.SubArea', null=True, blank=True, on_delete=models.PROTECT)
    inicio = models.DateTimeField(default=timezone.now)
    fim = models.DateTimeField(null=True, blank=True)
    revogada_em = models.DateTimeField(null=True, blank=True)
    concedida_por = models.ForeignKey('identidade.Pessoa', on_delete=models.PROTECT, related_name='+')
    revogada_por = models.ForeignKey('identidade.Pessoa', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    categorias = models.ManyToManyField(CategoriaDado, through='ConcessaoCategoria')

    # Anotações só para o pyright: o Django cria as colunas `<campo>_id`, que o verificador de tipos não enxerga.
    pessoa_id: int
    cargo_id: int
    empresa_id: int
    fazenda_id: int | None
    sub_area_id: int | None

    class Meta:
        db_table = 'concessao'
        constraints = [
            models.CheckConstraint(condition=Q(sub_area__isnull=True) | Q(fazenda__isnull=False), name='concessao_sub_area_exige_fazenda'),
            models.CheckConstraint(condition=Q(fim__isnull=True) | Q(fim__gt=models.F('inicio')), name='concessao_periodo_valido'),
            models.CheckConstraint(
                condition=Q(revogada_em__isnull=True, revogada_por__isnull=True) | Q(revogada_em__isnull=False, revogada_por__isnull=False),
                name='concessao_revogacao_completa',
            ),
        ]


def concessoes_ativas(agora=None):
    """Início já chegou, fim não chegou (ou não há), não revogada (R9, R11)."""
    agora = agora or timezone.now()
    return Concessao.objects.filter(revogada_em__isnull=True, inicio__lte=agora).filter(Q(fim__isnull=True) | Q(fim__gt=agora))


class ConcessaoCategoria(models.Model):
    concessao = models.ForeignKey(Concessao, on_delete=models.CASCADE)
    categoria = models.ForeignKey(CategoriaDado, on_delete=models.PROTECT)

    class Meta:
        db_table = 'concessao_categoria'
        constraints = [models.UniqueConstraint(fields=['concessao', 'categoria'], name='concessao_categoria_unico')]
