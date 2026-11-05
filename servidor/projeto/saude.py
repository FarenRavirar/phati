"""Rota de saúde (006 R10): 200 só se o app alcança o banco. Sem sessão, sem dado, sem versão: base do healthcheck do
contêiner e da conferência pós-deploy; o corpo não revela usuário nem nome de banco."""

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
@never_cache
def saude(requisicao):
    try:
        with connection.cursor() as consulta:
            consulta.execute('SELECT 1')
    except DatabaseError:
        return JsonResponse({'estado': 'indisponivel'}, status=503)
    return JsonResponse({'estado': 'ok'})

# Rota de dados da web: entra na matriz de cobertura (R22); a sonda não tem tela de propósito.
setattr(saude, 'dados_da_web', True)
