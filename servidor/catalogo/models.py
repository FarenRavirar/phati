"""Catálogo de camadas (spec 008, §Modelo; R1, R2, R10). Cada tabela tem RLS na migração 0002 (T1.3).

Tema → Estudo → Camada → VersaoCamada → Feição, com atributos da versão. Esta spec só cria versão "em análise":
a CHECK abaixo impede qualquer outro estado; tornar vigente é da spec de revisão e vigência (R2)."""

import uuid

from django.contrib.gis.db import models as gis
from django.db import models
from django.db.models import Q

ESTADO_EM_ANALISE = 'em_analise'
SRID_GUARDA = 4674  # SIRGAS 2000 geográfico (D114 / plan §Propostas)


class Tema(models.Model):
    """Tema de estudo, dentro de uma empresa."""
    empresa = models.ForeignKey('territorio.Empresa', on_delete=models.PROTECT, related_name='+')
    nome = models.CharField(max_length=200)
    empresa_id: int  # anotação para o pyright: o Django cria `empresa_id`

    class Meta:
        db_table = 'catalogo_tema'
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'nome'], name='tema_nome_unico_na_empresa'),
        ]


class Estudo(models.Model):
    """Estudo de uma fazenda, com identificador público opaco (R1)."""
    publico_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    empresa = models.ForeignKey('territorio.Empresa', on_delete=models.PROTECT, related_name='+')
    fazenda = models.ForeignKey('territorio.Fazenda', on_delete=models.PROTECT, related_name='+')
    tema = models.ForeignKey(Tema, on_delete=models.PROTECT, related_name='estudos')
    nome = models.CharField(max_length=200)
    empresa_id: int
    fazenda_id: int
    tema_id: int

    class Meta:
        db_table = 'catalogo_estudo'
        constraints = [
            # Chave que os filhos referenciam (FK composta, migração 0002): empresa e fazenda não andam separadas.
            models.UniqueConstraint(fields=['id', 'empresa', 'fazenda'], name='estudo_chave_composta'),
        ]


class Camada(models.Model):
    """Camada de um estudo, com identificador público opaco (R1)."""
    publico_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    estudo = models.ForeignKey(Estudo, on_delete=models.PROTECT, related_name='camadas')
    empresa = models.ForeignKey('territorio.Empresa', on_delete=models.PROTECT, related_name='+')
    fazenda = models.ForeignKey('territorio.Fazenda', on_delete=models.PROTECT, related_name='+')
    nome = models.CharField(max_length=200)
    estudo_id: int
    empresa_id: int
    fazenda_id: int

    class Meta:
        db_table = 'catalogo_camada'
        constraints = [
            models.UniqueConstraint(fields=['estudo', 'nome'], name='camada_nome_unico_no_estudo'),
            models.UniqueConstraint(fields=['id', 'empresa', 'fazenda'], name='camada_chave_composta'),
        ]


class VersaoCamada(models.Model):
    """Versão de uma camada. Nasce e fica "em análise" nesta spec (R2); o original fica em disco privado (R15)."""
    camada = models.ForeignKey(Camada, on_delete=models.PROTECT, related_name='versoes')
    empresa = models.ForeignKey('territorio.Empresa', on_delete=models.PROTECT, related_name='+')
    fazenda = models.ForeignKey('territorio.Fazenda', on_delete=models.PROTECT, related_name='+')
    numero = models.PositiveIntegerField()
    estado = models.CharField(max_length=20, default=ESTADO_EM_ANALISE)
    sistema_original = models.CharField(max_length=50)
    hash_original = models.CharField(max_length=64)
    caminho_original = models.CharField(max_length=300)  # interno, nunca servido por rota (R15)
    enviada_por = models.ForeignKey('identidade.Pessoa', on_delete=models.PROTECT, related_name='+')
    criada_em = models.DateTimeField(auto_now_add=True)
    camada_id: int
    empresa_id: int
    fazenda_id: int
    enviada_por_id: int

    class Meta:
        db_table = 'catalogo_versao_camada'
        constraints = [
            models.UniqueConstraint(fields=['camada', 'numero'], name='versao_camada_numero_unico'),
            models.CheckConstraint(condition=Q(numero__gte=1), name='versao_camada_numero_positivo'),
            models.CheckConstraint(condition=Q(estado=ESTADO_EM_ANALISE), name='versao_camada_so_em_analise'),
            models.UniqueConstraint(fields=['id', 'empresa', 'fazenda'], name='versao_camada_chave_composta'),
        ]


class AtributoVersao(models.Model):
    """Coluna do arquivo como atributo consultável da versão (R9). Ocultar é ação auditada (T1.4)."""
    versao = models.ForeignKey(VersaoCamada, on_delete=models.CASCADE, related_name='atributos')
    empresa = models.ForeignKey('territorio.Empresa', on_delete=models.PROTECT, related_name='+')
    fazenda = models.ForeignKey('territorio.Fazenda', on_delete=models.PROTECT, related_name='+')
    nome = models.CharField(max_length=100)
    rotulo = models.CharField(max_length=200, blank=True)
    unidade = models.CharField(max_length=50, blank=True)
    visivel = models.BooleanField(default=True)
    versao_id: int
    empresa_id: int
    fazenda_id: int

    class Meta:
        db_table = 'catalogo_atributo_versao'
        constraints = [
            models.UniqueConstraint(fields=['versao', 'nome'], name='atributo_nome_unico_na_versao'),
        ]


class Feicao(models.Model):
    """Feição de uma versão, em SIRGAS 2000 (R5). `sub_area` nulo = fazenda inteira. Ausente fica ausente no jsonb (R10)."""
    versao = models.ForeignKey(VersaoCamada, on_delete=models.CASCADE, related_name='feicoes')
    empresa = models.ForeignKey('territorio.Empresa', on_delete=models.PROTECT, related_name='+')
    fazenda = models.ForeignKey('territorio.Fazenda', on_delete=models.PROTECT, related_name='+')
    geometria = gis.GeometryField(srid=SRID_GUARDA)
    sub_area = models.ForeignKey('territorio.SubArea', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    valores = models.JSONField(default=dict)
    versao_id: int
    empresa_id: int
    fazenda_id: int


class EnvioCamada(models.Model):
    """Envio em prévia: linha temporária com expiração, não versão (R12). O arquivo temporário expira com ela."""
    criado_por = models.ForeignKey('identidade.Pessoa', on_delete=models.PROTECT, related_name='+')
    empresa = models.ForeignKey('territorio.Empresa', on_delete=models.PROTECT, related_name='+')
    fazenda = models.ForeignKey('territorio.Fazenda', on_delete=models.PROTECT, related_name='+')
    arquivo_temporario = models.CharField(max_length=300)
    expira_em = models.DateTimeField()
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por_id: int
    empresa_id: int
    fazenda_id: int

    class Meta:
        db_table = 'catalogo_envio_camada'
