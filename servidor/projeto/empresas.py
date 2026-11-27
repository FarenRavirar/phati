"""Seletor de fazenda (R10) e a tela Fazendas (spec 012, R20, R30; Q17): fazendas de todas as empresas que a pessoa vê, com
busca, situação e páginas no servidor (sem JS). Empresa e fazenda fora do escopo não entram na resposta (R3, D063): a lista
vem das mesmas listagens que decidem o 404 do endereço.
A página da empresa (Q24) é a mesma tela, filtrada pela empresa; as ações de gestão dela ficam em "Mais ações" (R39)."""

from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.views.decorators.http import require_GET

from permissao.pode import permissoes_efetivas
from projeto.escopo import resolver_escopo
from projeto.paginas_autenticadas import exige_acao, exige_entrada, renderizar_na_casca
from projeto.territorio_paginas import acoes_do_alvo
from territorio.listagem import SITUACOES, empresas_com_nova_fazenda, listar_fazendas, pode_exportar_fazendas

# Rótulos do Segmentado de situação (telas.md §3), na ordem da tela.
ROTULOS_DA_SITUACAO = (('todas', 'Todas'), ('ativas', 'Ativas'), ('arquivadas', 'Arquivadas'))


def _consulta(busca, situacao, pagina=None):
    """Query da listagem: busca, situação e página. Valor padrão não entra, para o link ficar curto."""
    parametros = {}
    if busca:
        parametros['busca'] = busca
    if situacao != 'todas':
        parametros['situacao'] = situacao
    if pagina is not None:
        parametros['pagina'] = pagina
    return urlencode(parametros)


def _contexto_da_listagem(requisicao, empresa=None):
    """Contexto da tela de fazendas; com `empresa`, a mesma tela filtrada por ela (Q24)."""
    usuario = requisicao.user
    busca = requisicao.GET.get('busca', '')
    situacao = requisicao.GET.get('situacao', 'todas')
    situacao = situacao if situacao in SITUACOES else 'todas'
    listagem = listar_fazendas(usuario, busca, situacao, empresa_id=empresa.pk if empresa else None, pagina=requisicao.GET.get('pagina'))
    pagina = listagem.pagina
    exportar = _consulta(busca, situacao)
    if empresa is not None:
        exportar = urlencode({'empresa': empresa.pk}) + ('&' + exportar if exportar else '')
    return {
        'linhas': listagem.linhas,
        'total': listagem.total,
        'total_filtrado': listagem.total_filtrado,
        'rotulo_talhoes': listagem.rotulo_talhoes,
        'busca': busca,
        'situacao': situacao,
        'opcoes_situacao': [{'valor': valor, 'rotulo': rotulo, 'href': '?' + _consulta(busca, valor)} for valor, rotulo in ROTULOS_DA_SITUACAO],
        'url_anterior': '?' + _consulta(busca, situacao, pagina.previous_page_number()) if pagina.has_previous() else None,
        'url_proxima': '?' + _consulta(busca, situacao, pagina.next_page_number()) if pagina.has_next() else None,
        'pagina': pagina,
        'pode_exportar': pode_exportar_fazendas(usuario, empresa.pk if empresa else None),
        'url_exportar': reverse('fazendas_csv') + '?' + exportar,
    }


@require_GET
@exige_entrada
@exige_acao('ver')
def empresas(requisicao):
    novas = empresas_com_nova_fazenda(requisicao.user)
    if len(novas) == 1:
        destino_nova = reverse('fazenda_nova', kwargs={'empresa_id': novas[0].pk})
    else:
        destino_nova = reverse('fazenda_escolher_empresa') if novas else None
    contexto = _contexto_da_listagem(requisicao) | {
        'destino_nova': destino_nova, 'limpar': reverse('empresas'), 'titulo_da_tela': 'Fazendas',
        'subtitulo': 'Propriedades a que você tem acesso, em todas as empresas.', 'empresa_arquivada': False, 'acoes': [],
    }
    return renderizar_na_casca(requisicao, 'fazendas.html', contexto)


@require_GET
@exige_entrada
@exige_acao('criar_fazenda')
def escolher_empresa_nova_fazenda(requisicao):
    """Várias empresas com `criar_fazenda`: a pessoa escolhe a empresa e vai ao formulário dela (telas.md §3)."""
    novas = empresas_com_nova_fazenda(requisicao.user)
    if not novas:
        raise PermissionDenied
    itens = [{'rotulo': empresa.nome, 'destino': reverse('fazenda_nova', kwargs={'empresa_id': empresa.pk})} for empresa in novas]
    contexto = {
        'titulo': 'Nova fazenda', 'subtitulo': 'Escolha a empresa da nova fazenda.', 'voltar': reverse('empresas'),
        'busca': None, 'pagina': None, 'consulta': '', 'itens': itens, 'vazio': 'Nenhuma empresa aceita fazenda nova.',
    }
    return renderizar_na_casca(requisicao, 'escolher_lugar.html', contexto)


@require_GET
@exige_entrada
@exige_acao('ver')
def empresa(requisicao, empresa_id):
    escopo, _ = resolver_escopo(requisicao.user, empresa_id)
    acoes = acoes_do_alvo(escopo, permissoes_efetivas(requisicao.user, escopo), pessoa=requisicao.user)
    # Empresa arquivada continua consultável por inteiro (R11): as fazendas dela, arquivadas pelo mesmo ato, aparecem.
    contexto = _contexto_da_listagem(requisicao, escopo) | {
        'destino_nova': None, 'limpar': reverse('empresa', kwargs={'empresa_id': escopo.pk}), 'titulo_da_tela': escopo.nome,
        'subtitulo': None, 'empresa_arquivada': escopo.arquivada_em is not None, 'acoes': acoes,
    }
    return renderizar_na_casca(requisicao, 'fazendas.html', contexto, empresa=escopo)
