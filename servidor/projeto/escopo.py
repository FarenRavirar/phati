"""Escopo na URL (R3, D063) e empresa escolhida na casca (R17).

Escopo na URL: inexistente, de outra empresa e sem permissão dão o mesmo 404, sem revelar existência. A autorização vem
das listagens, a mesma checagem que monta o seletor: não há segundo caminho de decisão.

Empresa escolhida: fica na sessão, sob `CHAVE_EMPRESA`, e é revalidada a cada requisição contra `empresas_autorizadas`.
Sem acesso, é descartada da sessão. Empresa na URL prevalece sobre ela (D063).
"""

from django.http import Http404

from permissao.models import Concessao
from permissao.pode import com_permissao, memoria_de, unir_escopos
from territorio.listagem import empresas_autorizadas, fazendas_autorizadas

CHAVE_EMPRESA = 'empresa_escolhida'


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


def alcance_na_empresa(pessoa, empresa, acoes, inteira=False):
    """Se `pessoa` tem alguma das `acoes` no alcance de `empresa`: a empresa inteira, e fazenda ou sub-área dela só com
    `inteira=False` (as telas de pessoas). Com `inteira=True`, só a empresa inteira (cargo é da empresa, 003 R18).
    Usada pelas views e pelo menu: a mesma decisão nos dois."""
    escopos = unir_escopos(pessoa, *acoes)
    if escopos.plataforma:
        return True
    lugares = escopos.empresas if inteira else escopos.empresas | escopos.empresas_das_fazendas
    return empresa.pk in lugares


def empresa_lembrada(requisicao):
    """Empresa escolhida no seletor, revalidada agora: sem acesso, sai da sessão e a pessoa fica sem escolha.

    shortcut: quem alcança uma só empresa a tem como escolhida sem gravar nada; subir para a escolha explícita se a
    pessoa passar a ter várias sem escolher (hoje o menu de Pessoas e Cargos some até ela escolher)."""
    pessoa = requisicao.user
    sessao = requisicao.session
    pk = sessao.get(CHAVE_EMPRESA)
    if pk is not None:
        empresa = next(iter(empresas_autorizadas(pessoa, pk=pk)), None)
        if empresa is not None:
            return empresa
        sessao.pop(CHAVE_EMPRESA, None)
    alcancadas = list(empresas_autorizadas(pessoa))
    return alcancadas[0] if len(alcancadas) == 1 else None


def seletor_da_pessoa(pessoa):
    """Conteúdo do seletor de escopo (R17): empresas e fazendas autorizadas; os links de Empresas e de Arquivadas só
    aparecem a quem alcança essas telas (as mesmas condições da própria tela de empresas)."""
    empresas = list(empresas_autorizadas(pessoa))
    por_id = {empresa.pk: empresa for empresa in empresas}
    fazendas = [(por_id[f.empresa_id], f) for f in fazendas_autorizadas(pessoa) if f.empresa_id in por_id]
    arquivadas = bool(empresas_autorizadas(pessoa, arquivadas=True) or fazendas_autorizadas(pessoa, arquivadas=True))
    return {'empresas': empresas, 'fazendas': fazendas, 'arquivadas': arquivadas}


def cargos_na_empresa(pessoa, empresa):
    """Nomes dos cargos da pessoa na `empresa`, do lugar mais amplo (empresa inteira) ao mais estreito (Q23)."""
    if empresa is None:
        return []
    ids = [v.concessao.pk for v in memoria_de(pessoa).vinculos if v.concessao.empresa_id == empresa.pk]
    if not ids:
        return []
    with com_permissao(pessoa, 'ver'):
        concessoes = Concessao.objects.filter(pk__in=ids).select_related('cargo')
        ordem = sorted(concessoes, key=lambda c: (c.sub_area_id is not None, c.fazenda_id is not None))
        return [c.cargo.nome for c in ordem]
