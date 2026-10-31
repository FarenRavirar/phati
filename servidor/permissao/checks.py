"""Verificação do segredo de RLS: `PHATI_SEGREDO_RLS` tem de ser o que a migração 0004 gravou em `rls_segredo`.

Segredo diferente (rotação sem `UPDATE`, ambientes que divergem) faz `app_contexto_ok()` negar tudo: toda consulta
volta vazia e nada no log diz o porquê (achado do Qodo, PR #15). A verificação roda com `manage.py check --database
default` e a `migracao` do compose a executa, então o deploy falha em vez de subir negando acesso a todos.
"""

import hashlib

from django.conf import settings
from django.core.checks import Error, Tags, register
from django.db import ProgrammingError, connections, transaction


@register(Tags.database)
def conferir_segredo_rls(app_configs, databases=None, **kwargs):
    esperada = hashlib.sha256(settings.SEGREDO_RLS).hexdigest()
    erros = []
    for alias in databases or ():
        try:
            # Ponto de salvamento: a função ainda não existe antes da 0004 (o `migrate` roda esta verificação antes).
            with transaction.atomic(using=alias), connections[alias].cursor() as consulta:
                consulta.execute('SELECT app_segredo_impressao()')
                gravada = consulta.fetchone()[0]
        except ProgrammingError:
            continue
        if gravada != esperada:
            erros.append(Error(
                f'PHATI_SEGREDO_RLS difere do segredo gravado em rls_segredo (banco "{alias}"): o banco nega todo acesso.',
                hint='Alinhe o ambiente com o banco ou faça UPDATE rls_segredo como dono (ver permissao/contexto.py).',
                id='permissao.E001',
            ))
    return erros
