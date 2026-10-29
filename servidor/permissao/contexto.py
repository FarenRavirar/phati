"""Contexto de RLS assinado (R12; plan.md §Camada de banco).

O papel `app` consegue fixar qualquer variável `app.*` na própria sessão, então as políticas não confiam nelas
sozinhas: exigem `app.assinatura`, um HMAC-SHA256 do número da transação e dos quatro escopos, com o segredo que só a
aplicação e a tabela `rls_segredo` (sem acesso do `app`) conhecem. Quem executa SQL fora de `com_permissao` não sabe
assinar; a assinatura de outra transação não vale na seguinte; mudar o escopo depois de assinado a invalida.
`vinculos_da_pessoa` pede, do mesmo modo, a assinatura da identidade (`app.assinatura_pessoa`).

Rotação do segredo: gerar outro, gravar `UPDATE rls_segredo SET valor = <32 bytes>` como dono e trocar
`PHATI_SEGREDO_RLS` no mesmo instante; entre um passo e outro o banco nega tudo (falha fechada).
"""

import hashlib
import hmac

from django.conf import settings

_NUMERO_DA_TRANSACAO = 'SELECT pg_current_xact_id()::text'
_VARIAVEIS = ('plataforma', 'empresas', 'empresas_de_fazendas', 'fazendas', 'assinatura')
_LER = 'SELECT ' + ', '.join(f"coalesce(current_setting('app.{nome}', true), '')" for nome in _VARIAVEIS)
# `is_local = true`: vale só até o fim da transação. `false` valeria para a sessão inteira e vazaria para a
# transação seguinte da mesma conexão (test_set_config_local barra isso no código).
_FIXAR = 'SELECT ' + ', '.join(f"set_config('app.{nome}', %s, true)" for nome in _VARIAVEIS)
_FIXAR_IDENTIDADE = "SELECT set_config('app.assinatura_pessoa', %s, true)"


def _assinar(*partes):
    return hmac.new(settings.SEGREDO_RLS, '|'.join(partes).encode(), hashlib.sha256).hexdigest()


def _numero_da_transacao(consulta):
    consulta.execute(_NUMERO_DA_TRANSACAO)
    return consulta.fetchone()[0]


def ler_contexto(consulta):
    """Os quatro escopos e a assinatura que a sessão tem agora (vazios quando não há)."""
    consulta.execute(_LER)
    return consulta.fetchone()


def fixar_contexto(consulta, plataforma, empresas, empresas_de_fazendas, fazendas):
    """Fixa os escopos e a assinatura deles na transação corrente; exige transação aberta (`atomic`)."""
    escopos = (plataforma, empresas, empresas_de_fazendas, fazendas)
    consulta.execute(_FIXAR, [*escopos, _assinar(_numero_da_transacao(consulta), *escopos)])


def restaurar_contexto(consulta, anteriores):
    """Devolve o que `ler_contexto` leu: a assinatura anterior continua valendo, é da mesma transação."""
    consulta.execute(_FIXAR, anteriores)


def fixar_identidade(consulta, pessoa_id):
    """Assina, na transação corrente, a identidade que `vinculos_da_pessoa` aceita consultar."""
    consulta.execute(_FIXAR_IDENTIDADE, [_assinar(_numero_da_transacao(consulta), str(pessoa_id))])
