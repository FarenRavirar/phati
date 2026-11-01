"""Escopo na URL (R3, D063): empresa e fazenda do endereço só existem para quem as alcança.

Inexistente, de outra empresa e sem permissão dão o mesmo 404, sem revelar existência. A autorização vem das
listagens, a mesma checagem que monta o seletor: não há segundo caminho de decisão.
"""

from django.http import Http404

from territorio.listagem import empresas_autorizadas, fazendas_autorizadas


def resolver_escopo(pessoa, empresa_id, fazenda_id=None):
    """Devolve `(empresa, fazenda)`; `fazenda` é None sem `fazenda_id`. Fora do alcance da pessoa: `Http404`.

    Aceita escopo arquivado: a leitura por URL direta segue valendo e `pode()` nega a escrita (003 R11)."""
    # Uma linha por consulta, sob a mesma autorização das listagens (Qodo e Sourcery, PR #19).
    empresa = next(iter(empresas_autorizadas(pessoa, pk=empresa_id, arquivadas=None)), None)
    if empresa is None:
        raise Http404
    if fazenda_id is None:
        return empresa, None
    fazenda = next((f for f in fazendas_autorizadas(pessoa, pk=fazenda_id, arquivadas=None) if f.empresa_id == empresa_id), None)
    if fazenda is None:
        raise Http404
    return empresa, fazenda
