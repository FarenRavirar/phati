"""Dados do pacote para a página da fazenda (004b R7, R8, R11): o que a web precisa para montar o fundo próprio.

A web não lê o manifesto pela rota `pacote_manifesto`: ela pede `baixar_pacote_offline`, e quem só tem `ver` baixa os bytes do
fundo e da ortofoto (D097, item 1). Aqui a mesma versão vigente sai pelo servidor, com a mesma checagem dos arquivos: `ver` na
fazenda inteira. Quem só tem uma sub-área, sem pacote ou com manifesto quebrado recebe `None` e a página fica no fundo neutro,
sem nenhuma URL do pacote no HTML."""

from django.urls import reverse

from pacote import manifesto as contrato
from pacote.models import VersaoPacote
from permissao.pode import com_permissao, pode


def fundo_da_pagina(pessoa, fazenda):
    """`dict` com as URLs de `pacote_arquivo` (com `?versao=N` fixo) e os textos do fundo e da ortofoto, ou `None`.

    Chaves: `fundo`, `atribuicao`, `ortofoto` (URL ou `None`), `ortofoto_atribuicao`, `ortofoto_capturada_em` (texto ISO)."""
    if not pode(pessoa, 'ver', fazenda):
        return None
    with com_permissao(pessoa, 'ver'):
        versao = VersaoPacote.objects.filter(fazenda=fazenda, vigente=True).first()
    if versao is None:
        return None
    try:
        arquivos = {a.papel: a for a in contrato.validar(versao.manifesto).arquivos}
    except contrato.ManifestoInvalido:
        return None
    if 'fundo' not in arquivos:
        return None

    def url(arquivo):
        base = reverse('pacote_arquivo', kwargs={'empresa_id': fazenda.empresa_id, 'fazenda_id': fazenda.pk, 'nome': arquivo.nome})
        return f'{base}?versao={versao.numero}'

    ortofoto = arquivos.get('ortofoto')
    return {
        'fundo': url(arquivos['fundo']),
        'atribuicao': arquivos['fundo'].atribuicao,
        'ortofoto': url(ortofoto) if ortofoto else None,
        'ortofoto_atribuicao': ortofoto.atribuicao if ortofoto else '',
        'ortofoto_capturada_em': ortofoto.capturada_em.isoformat() if ortofoto and ortofoto.capturada_em else '',
    }
