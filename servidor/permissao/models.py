from django.db import models


class Permissao(models.Model):
    """Ação do catálogo fixo (R8). Cresce só por migração (risco R-7 da spec)."""

    codigo = models.CharField(max_length=64, primary_key=True)
    descricao = models.CharField(max_length=200)
    delegavel = models.BooleanField()

    class Meta:
        db_table = 'permissao'
