"""Telas de gestão de pessoas (003 R13 a R17): lista, convidar, convites enviados, revogar, redefinir senha e titularidade.

Nenhuma regra de negócio aqui (R28): a view resolve a empresa da URL (fora do alcance, 404 igual ao de inexistente), confere
o alcance de gestão, e quem decide o resto é a função de serviço que a API também chama (negado vira 403; regra violada, o
texto da `ValidationError` volta à tela). Convidar, revogar e redefinir chamam `convidar_por_cpf`, `revogar_concessao` e
`pedir_redefinicao_de_outra_pessoa`; a titularidade, `transferir_titularidade`. A senha temporária de um convite novo aparece
uma vez, no corpo da resposta, nunca em redirecionamento nem em sessão. Redefinir a senha de outra pessoa manda só o link por
e-mail: ninguém vê a senha de ninguém.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from identidade import redefinicao
from identidade.models import Pessoa
from permissao import convite as convites
from permissao import delegacao
from permissao.api import pessoas_do_escopo
from permissao.models import Cargo, CategoriaDado, Concessao, Convite, concessoes_ativas, concessoes_vigentes_ou_futuras
from permissao.pode import com_permissao, escopo_de, filtro_do_escopo, permissoes_efetivas, unir_escopos
from projeto.escopo import resolver_escopo
from projeto.painel import ACOES_DE_PESSOAS
from projeto.paginas_autenticadas import campo, confirmacao, exigir, formulario, pagina, renderizar_na_casca, texto_do_erro
from territorio.listagem import fazendas_autorizadas
from territorio.models import SubArea

ITENS_POR_PAGINA = 25
TAMANHO_DO_EMAIL = 254  # o `max_length` padrão de `EmailField`, o de `Pessoa.email`
TITULO_CONVIDAR = 'Convidar pessoa'
TITULO_TITULARIDADE = 'Transferir a titularidade'
ESCOLHA_VAZIA = {'valor': '', 'rotulo': 'Escolha uma opção'}
# O que a tela diz depois de uma ação: só estas chaves viram texto (o parâmetro `feito` do endereço nunca é impresso).
AVISOS = {
    'cancelado': 'Convite cancelado.', 'reenviado': 'Convite reenviado.', 'revogado': 'Acesso revogado.',
    'titularidade': 'Titularidade transferida.', 'concedido': 'Acesso concedido.', 'criado': 'Cargo criado.', 'alterado': 'Cargo alterado.',
}
SEM_ALCANCE = 'Você não pode conceder este cargo neste lugar.'


def _empresa(requisicao, empresa_id):
    return resolver_escopo(requisicao.user, empresa_id)[0]


def _com_alcance(requisicao, empresa, *acoes):
    """Quem não tem nenhuma das `acoes` em algum lugar desta empresa recebe 403 (alcance sem a ação). A decisão por alvo
    continua na função de serviço, a mesma da API."""
    escopos = unir_escopos(requisicao.user, *acoes)
    if not (escopos.plataforma or empresa.pk in escopos.empresas | escopos.empresas_das_fazendas):
        raise PermissionDenied
    return escopos


def _contexto(requisicao):
    """Abre a RLS para as ações de pessoas: a lista, as concessões e os cargos só existem dentro dele."""
    return com_permissao(requisicao.user, *ACOES_DE_PESSOAS, 'ver')


def _da_empresa(quem, empresa):
    """Pessoas do alcance de `quem` com acesso ativo ou futuro à empresa, ou que nasceram nela; `pessoa` não tem RLS, este
    filtro é a proteção. O acesso que ainda vai começar entra, para dar para revogá-lo antes (Greptile, PR #30)."""
    vigentes = concessoes_vigentes_ou_futuras().filter(empresa_id=empresa.pk)
    alcance = unir_escopos(quem, *ACOES_DE_PESSOAS)
    if not alcance.plataforma:
        # Só o vínculo que quem olha alcança põe a pessoa na lista desta empresa: administrar a empresa de origem dela não
        # basta para revelar que ela tem acesso numa sub-área irmã daqui (Codex, PR #30).
        vigentes = vigentes.filter(filtro_do_escopo(alcance))
    return pessoas_do_escopo(quem, ACOES_DE_PESSOAS, futuras=True).filter(Q(pk__in=vigentes.values('pessoa_id')) | Q(empresa_origem_id=empresa.pk))


def _pessoa_da_empresa(requisicao, empresa, pessoa_id):
    pessoa = _da_empresa(requisicao.user, empresa).filter(pk=pessoa_id).first()
    if pessoa is None:
        raise Http404
    return pessoa


def _nomes_de_sub_areas(linhas):
    """`{id: nome}` das sub-áreas citadas por concessões ou convites: uma consulta por tela."""
    ids = {linha.sub_area_id for linha in linhas if linha.sub_area_id is not None}
    return dict(SubArea.objects.filter(pk__in=ids).values_list('pk', 'nome')) if ids else {}


def _onde(linha, nomes_de_fazenda, nomes_de_sub_area):
    if linha.fazenda_id is None:
        return 'Empresa inteira'
    fazenda = nomes_de_fazenda.get(linha.fazenda_id, 'Fazenda')
    return fazenda if linha.sub_area_id is None else f'{fazenda} › {nomes_de_sub_area.get(linha.sub_area_id, "Sub-área")}'


def _caminho(nome, empresa, **resto):
    return reverse(nome, kwargs={'empresa_id': empresa.pk, **resto})


def _aviso_do_endereco(requisicao):
    return AVISOS.get(requisicao.GET.get('feito', ''))


# --- lista ---


@pagina('convidar_pessoa')
def pessoas(requisicao, empresa_id):
    empresa = _empresa(requisicao, empresa_id)
    with _contexto(requisicao):
        _com_alcance(requisicao, empresa, *ACOES_DE_PESSOAS)
        efetivas = permissoes_efetivas(requisicao.user, empresa)
        lugares = _escopos_do_convite(requisicao, empresa)
        pode_convidar = bool(lugares) or bool(_fazendas_com_sub_areas(requisicao, empresa))  # em algum lugar da empresa, não só nela inteira
        pagina_de_pessoas = Paginator(_da_empresa(requisicao.user, empresa), ITENS_POR_PAGINA).get_page(requisicao.GET.get('pagina'))
        por_pessoa = defaultdict(list)
        nomes = {f.pk: f.nome for f in fazendas_autorizadas(requisicao.user, empresa_id=empresa.pk, arquivadas=None)}
        agora = timezone.now()
        vigentes = concessoes_vigentes_ou_futuras().filter(empresa_id=empresa.pk, pessoa_id__in=[p.pk for p in pagina_de_pessoas])
        # A pessoa pode ter acesso em lugares que quem olha não alcança: cargo, lugar e prazo de lá não aparecem (Codex e Qodo, PR #30).
        alcance = unir_escopos(requisicao.user, *ACOES_DE_PESSOAS)
        if not alcance.plataforma:
            vigentes = vigentes.filter(filtro_do_escopo(alcance))
        concessoes = list(vigentes.select_related('cargo', 'fazenda', 'sub_area').order_by('pk'))
        nomes_de_sub_area = _nomes_de_sub_areas(concessoes)
        for concessao in concessoes:
            por_pessoa[concessao.pessoa_id].append({
                'cargo': concessao.cargo.nome, 'onde': _onde(concessao, nomes, nomes_de_sub_area),
                'comeca': concessao.inicio if concessao.inicio > agora else None,
                # O `fim` gravado é exclusivo (o formulário soma um dia): a tela diz o último dia de acesso (Sourcery, PR #30).
                'fim': concessao.fim - timedelta(microseconds=1) if concessao.fim else None,
                'revogar': _caminho('pessoa_revogar', empresa, pessoa_id=concessao.pessoa_id, concessao_id=concessao.pk) if delegacao.pode_revogar(requisicao.user, concessao) else None,
            })
        redefinir = 'redefinir_senha' in efetivas
        # Conceder segue o alcance de convidar (como a rota da API e a tela `conceder`); a lista também junta revogar e redefinir.
        concediveis = set(pessoas_do_escopo(requisicao.user, ('convidar_pessoa',), futuras=True).filter(pk__in=[p.pk for p in pagina_de_pessoas]).values_list('pk', flat=True)) if lugares else set()
        itens = [
            {
                'nome': p.nome, 'email': p.email, 'deve_trocar_senha': p.deve_trocar_senha, 'concessoes': por_pessoa[p.pk],
                'redefinir': _caminho('pessoa_redefinir_senha', empresa, pessoa_id=p.pk) if redefinir else None,
                'conceder': _caminho('pessoa_conceder', empresa, pessoa_id=p.pk) if p.pk in concediveis else None,
            }
            for p in pagina_de_pessoas
        ]
        acoes = []
        if pode_convidar:
            acoes += [
                {'rotulo': TITULO_CONVIDAR, 'destino': _caminho('pessoas_convidar', empresa)},
                {'rotulo': 'Convites enviados', 'destino': _caminho('pessoas_convites', empresa)},
            ]
        if delegacao.pode_transferir_titularidade(requisicao.user, empresa):
            acoes.append({'rotulo': TITULO_TITULARIDADE, 'destino': _caminho('titularidade', empresa)})
    contexto = {
        'itens': itens, 'pagina': pagina_de_pessoas, 'acoes': acoes, 'aviso': _aviso_do_endereco(requisicao),
        'vazio_rotulo': TITULO_CONVIDAR if pode_convidar else None, 'vazio_destino': _caminho('pessoas_convidar', empresa),
    }
    return renderizar_na_casca(requisicao, 'pessoas.html', contexto, empresa=empresa)


# --- convidar ---


def _data(texto):
    """`AAAA-MM-DD` do campo de data; vazio é ausente. Data impossível levanta `ValueError`."""
    return timezone.make_aware(datetime.strptime(texto, '%Y-%m-%d')) if texto else None


def _escopos_do_convite(requisicao, empresa) -> dict[str, tuple[str, object]]:
    """`{valor do campo: (rótulo, lugar)}` onde a pessoa pode convidar: a empresa inteira e as fazendas do alcance dela. A
    sub-área não entra aqui: são muitas, e a escolha delas tem tela própria (`convidar_sub_area`). Quem tem a ação no
    alcance só perde o lugar arquivado: a listagem já tira a fazenda arquivada, e arquivar a empresa arquiva as fazendas
    dela na mesma transação, então basta olhar a empresa, sem consulta por lugar (CodeRabbit, PR #30)."""
    escopos = unir_escopos(requisicao.user, 'convidar_pessoa')
    da_empresa_toda = escopos.plataforma or empresa.pk in escopos.empresas
    candidatos = {'empresa': ('Empresa inteira', empresa)} if da_empresa_toda and empresa.arquivada_em is None else {}
    for fazenda in fazendas_autorizadas(requisicao.user, empresa_id=empresa.pk):
        if da_empresa_toda or fazenda.pk in escopos.fazendas:
            candidatos[f'fazenda-{fazenda.pk}'] = (fazenda.nome, fazenda)
    return candidatos


def _consulta_de_sub_areas(requisicao, fazenda):
    """Sub-áreas da `fazenda` onde a pessoa pode convidar, como consulta: nada é carregado até alguém pedir a página
    (Qodo, Sourcery e Greptile, PR #30). Alcança quem tem a fazenda inteira, a própria sub-área ou uma ascendente (o
    `caminho` guarda os ancestrais). Convidar para o lugar mais estreito que serve é o menor privilégio (Azure RBAC,
    Google Cloud IAM, GitHub). As fazendas chegam daqui já sem as arquivadas (`fazendas_autorizadas`), e a consulta já
    tira a sub-área arquivada."""
    escopos = unir_escopos(requisicao.user, 'convidar_pessoa')
    da_fazenda = escopos.plataforma or fazenda.empresa_id in escopos.empresas or fazenda.pk in escopos.fazendas
    consulta = SubArea.objects.filter(fazenda_id=fazenda.pk, arquivada_em__isnull=True)
    if not da_fazenda:
        filtro = Q(pk__in=escopos.sub_areas)
        for raiz in escopos.sub_areas:
            filtro |= Q(caminho__contains=f'/{raiz}/')
        consulta = consulta.filter(filtro)
    return consulta.order_by('nivel', 'nome', 'pk')


def _trilhas(requisicao, fazenda, sub_areas):
    """`{id: 'Fazenda › Pai › Sub-área'}` das sub-áreas dadas, com uma consulta só para os nomes dos ancestrais. Ancestral
    fora do alcance de quem olha não aparece, como na listagem de território."""
    ancestrais = {int(i) for sub in sub_areas for i in sub.caminho.split('/') if i}
    nomes = dict(_consulta_de_sub_areas(requisicao, fazenda).filter(pk__in=ancestrais).values_list('pk', 'nome')) if ancestrais else {}
    return {
        sub.pk: ' › '.join([fazenda.nome, *(nomes[int(i)] for i in sub.caminho.split('/') if i and int(i) in nomes), sub.nome])
        for sub in sub_areas
    }


def _fazendas_com_sub_areas(requisicao, empresa):
    return [f for f in fazendas_autorizadas(requisicao.user, empresa_id=empresa.pk) if _consulta_de_sub_areas(requisicao, f).exists()]


def _pode_convidar(requisicao, empresa):
    return bool(_escopos_do_convite(requisicao, empresa)) or bool(_fazendas_com_sub_areas(requisicao, empresa))


def _sub_area_pedida(requisicao, empresa, chave):
    """`(trilha, sub-área)` se `chave` (`sub-area-<id>`) é de uma sub-área desta empresa onde a pessoa pode convidar; senão None."""
    chave = chave or ''
    numero = chave.removeprefix('sub-area-')
    if not chave.startswith('sub-area-') or not (numero.isascii() and numero.isdigit()):
        return None
    sub_area = SubArea.objects.filter(pk=int(numero), empresa_id=empresa.pk).first()
    if sub_area is None:
        return None
    fazenda = next(iter(fazendas_autorizadas(requisicao.user, pk=sub_area.fazenda_id, empresa_id=empresa.pk)), None)
    achada = _consulta_de_sub_areas(requisicao, fazenda).filter(pk=sub_area.pk).first() if fazenda else None
    return (_trilhas(requisicao, fazenda, [achada])[achada.pk], achada) if achada else None


def _campos_do_convite(dados, cargos, escopos, categorias, erros):
    return [
        campo('nome', 'Nome', dados.get('nome', ''), erros.get('nome'), obrigatorio=True, autocomplete='name'),
        campo('email', 'E-mail', dados.get('email', ''), erros.get('email'), tipo='email', obrigatorio=True, autocomplete='email'),
        campo('cpf', 'CPF', dados.get('cpf', ''), erros.get('cpf'), obrigatorio=True, teclado='numeric'),
        *_campos_de_acesso(dados, cargos, escopos, categorias, erros),
    ]


def _campos_de_acesso(dados, cargos, escopos, categorias, erros):
    """Cargo, lugar, categorias e período: o que o convite e a concessão pedem igual."""
    marcadas = set(dados.getlist('categorias')) if hasattr(dados, 'getlist') else set()
    return [
        campo('cargo', 'Cargo', dados.get('cargo', ''), erros.get('cargo'), tipo='select', obrigatorio=True,
              opcoes=[ESCOLHA_VAZIA, *({'valor': c.pk, 'rotulo': c.nome} for c in cargos)]),
        campo('escopo', 'Onde vale', dados.get('escopo', ''), erros.get('escopo'), tipo='select', obrigatorio=True,
              opcoes=[ESCOLHA_VAZIA, *({'valor': valor, 'rotulo': rotulo} for valor, (rotulo, _) in escopos.items())]),
        *([campo('categorias', 'Categorias de dado', tipo='caixas', erro=erros.get('categorias'),
                 ajuda='Só vale para Técnico e Usuário. Sem marcar, a pessoa não vê nenhuma categoria.',
                 opcoes=[{'valor': c.pk, 'rotulo': c.nome, 'marcada': str(c.pk) in marcadas} for c in categorias])] if categorias else []),
        campo('inicio', 'Início do acesso', dados.get('inicio', ''), erros.get('inicio'), tipo='date', ajuda='Em branco, começa agora.'),
        campo('fim', 'Último dia do acesso', dados.get('fim', ''), erros.get('fim'), tipo='date', ajuda='Em branco, sem prazo. O acesso vale até o fim deste dia.'),
    ]


def _erro_do_email(email):
    try:
        validate_email(email)
    except ValidationError:
        return 'Informe um e-mail válido.'
    if len(email) > TAMANHO_DO_EMAIL:  # o banco recusaria na gravação da pessoa nova (Qodo, PR #30)
        return f'Informe um e-mail de até {TAMANHO_DO_EMAIL} caracteres.'
    return None


def _ler_periodo(dados):
    """`(erros, início, fim)` do período: o fim vale até o fim do dia escolhido, então soma um dia."""
    erros, inicio, fim = {}, None, None
    try:
        inicio = _data(dados.get('inicio', ''))
    except ValueError:
        erros['inicio'] = 'Use uma data válida.'
    try:
        fim = _data(dados.get('fim', ''))
        fim = fim + timedelta(days=1) if fim else None
    except (ValueError, OverflowError):  # 9999-12-31 mais um dia estoura o calendário (Qodo, PR #30)
        erros['fim'] = 'Use uma data válida.'
    if not erros and fim is not None and fim <= (inicio or timezone.now()):
        erros['fim'] = 'O fim precisa ser depois do início.'
    return erros, inicio, fim


def _ler_convite(dados, cargos, escopos, categorias):
    """Converte e valida só o formato (R28); a regra de quem pode conceder o quê é da função de serviço."""
    erros = {}
    if not dados.get('nome', '').strip() or len(dados.get('nome', '')) > 200:
        erros['nome'] = 'Informe um nome de 1 a 200 caracteres.'
    if erro_do_email := _erro_do_email(dados.get('email', '')):
        erros['email'] = erro_do_email
    if not dados.get('cpf', '').strip():
        erros['cpf'] = 'Informe o CPF.'
    erros_do_acesso, *resto = _ler_acesso(dados, cargos, escopos, categorias)
    return {**erros, **erros_do_acesso}, *resto


def _ler_acesso(dados, cargos, escopos, categorias):
    """`(erros, cargo, lugar, categorias marcadas, início, fim)` dos campos de `_campos_de_acesso`."""
    erros = {}
    cargo = next((c for c in cargos if str(c.pk) == dados.get('cargo')), None)
    lugar = escopos.get(dados.get('escopo', ''))
    if cargo is None:
        erros['cargo'] = 'Escolha um cargo da lista.'
    if lugar is None:
        erros['escopo'] = 'Escolha onde o acesso vale.'
    escolhidas = set(dados.getlist('categorias'))
    marcadas = [c for c in categorias if str(c.pk) in escolhidas]
    if len(marcadas) != len(escolhidas):
        erros['categorias'] = 'Categoria inexistente nesta empresa.'
    erros_do_periodo, inicio, fim = _ler_periodo(dados)
    erros.update(erros_do_periodo)
    return erros, cargo, lugar[1] if lugar else None, marcadas, inicio, fim


@pagina('convidar_pessoa')
def convidar(requisicao, empresa_id):
    empresa = _empresa(requisicao, empresa_id)
    with _contexto(requisicao):
        _com_alcance(requisicao, empresa, 'convidar_pessoa')
        escopos = _escopos_do_convite(requisicao, empresa)
        pedida = _sub_area_pedida(requisicao, empresa, (requisicao.POST if requisicao.method == 'POST' else requisicao.GET).get('escopo'))
        if pedida is not None:  # veio da tela de escolher sub-área, ou é o que a pessoa já tinha escolhido
            escopos[f'sub-area-{pedida[1].pk}'] = pedida
        if not escopos and not _pode_convidar(requisicao, empresa):
            raise PermissionDenied
        cargos = list(Cargo.objects.filter(empresa_id=empresa.pk).order_by('nome'))
        categorias = list(CategoriaDado.objects.filter(empresa_id=empresa.pk).order_by('nome'))
        cancelar = _caminho('pessoas', empresa)

        def tela(dados, erros, erro=None, codigo_http=200):
            return formulario(requisicao, TITULO_CONVIDAR, _campos_do_convite(dados, cargos, escopos, categorias, erros), 'Enviar convite',
                              cancelar, subtitulo=empresa.nome, erro=erro, empresa=empresa, codigo_http=codigo_http,
                              acoes=[{'rotulo': 'Escolher uma sub-área', 'destino': _caminho('convidar_sub_area', empresa)}])

        if requisicao.method == 'GET':
            return tela({'escopo': f'sub-area-{pedida[1].pk}'} if pedida else {}, {})
        dados = requisicao.POST
        erros, cargo, lugar, marcadas, inicio, fim = _ler_convite(dados, cargos, escopos, categorias)
        if erros:
            return tela(dados, erros, codigo_http=400)
        try:
            pessoa, temporaria = convites.convidar_por_cpf(
                requisicao.user, dados['nome'].strip(), dados['email'], dados['cpf'], cargo, lugar, marcadas, inicio, fim,
            )
        except ValidationError as erro:
            return tela(dados, {}, texto_do_erro(erro), 400)
        except PermissionDenied:
            return tela(dados, {}, SEM_ALCANCE, 403)
    resposta = renderizar_na_casca(requisicao, 'convite_criado.html', {
        'senha_temporaria': temporaria if pessoa is not None else None, 'destino': cancelar,
    }, empresa=empresa)
    resposta['Cache-Control'] = 'no-store'
    return resposta


# --- conceder cargo a quem já está na empresa ---


def _historico_de_acessos(requisicao, empresa, pessoa):
    """Concessões da pessoa nesta empresa que quem olha alcança, as ativas e as revogadas, da mais nova à mais antiga."""
    concessoes = Concessao.objects.filter(empresa_id=empresa.pk, pessoa_id=pessoa.pk)
    alcance = unir_escopos(requisicao.user, *ACOES_DE_PESSOAS)
    if not alcance.plataforma:
        concessoes = concessoes.filter(filtro_do_escopo(alcance))
    concessoes = list(concessoes.select_related('cargo', 'fazenda', 'sub_area').order_by('-pk'))
    nomes = {f.pk: f.nome for f in fazendas_autorizadas(requisicao.user, empresa_id=empresa.pk, arquivadas=None)}
    nomes_de_sub_area = _nomes_de_sub_areas(concessoes)
    agora = timezone.now()
    linhas = []
    for c in concessoes:
        # Datas no fuso local, como o filtro `date` do molde da lista de pessoas: em UTC o último dia aparece um dia depois.
        if c.revogada_em is not None:
            situacao = f'revogada em {timezone.localtime(c.revogada_em):%d/%m/%Y}'
        elif c.fim is not None and c.fim <= agora:
            situacao = 'encerrada'
        elif c.inicio > agora:
            situacao = f'começa em {timezone.localtime(c.inicio):%d/%m/%Y}'
        else:
            situacao = 'ativa'
        prazo = f' · até {timezone.localtime(c.fim - timedelta(microseconds=1)):%d/%m/%Y}' if c.fim else ''  # o `fim` gravado é exclusivo
        linhas.append(f'{c.cargo.nome} · {_onde(c, nomes, nomes_de_sub_area)}{prazo} · {situacao}')
    return {'titulo': f'Acessos de {pessoa.nome} nesta empresa', 'linhas': linhas, 'vazio': 'Nenhum acesso registrado.'}


@pagina('convidar_pessoa')
def conceder(requisicao, empresa_id, pessoa_id):
    empresa = _empresa(requisicao, empresa_id)
    with _contexto(requisicao):
        _com_alcance(requisicao, empresa, 'convidar_pessoa')
        pessoa = _pessoa_da_empresa(requisicao, empresa, pessoa_id)
        # A lista junta o alcance de convidar, revogar e redefinir; conceder segue o de convidar, como a rota da API (Qodo, PR #31).
        if not pessoas_do_escopo(requisicao.user, ('convidar_pessoa',), futuras=True).filter(pk=pessoa.pk).exists():
            raise Http404
        escopos = _escopos_do_convite(requisicao, empresa)
        if not escopos:
            raise PermissionDenied
        cargos = list(Cargo.objects.filter(empresa_id=empresa.pk).order_by('nome'))
        categorias = list(CategoriaDado.objects.filter(empresa_id=empresa.pk).order_by('nome'))
        cancelar = _caminho('pessoas', empresa)

        def tela(dados, erros, erro=None, codigo_http=200):
            return formulario(requisicao, f'Conceder cargo a {pessoa.nome}', _campos_de_acesso(dados, cargos, escopos, categorias, erros),
                              'Conceder', cancelar, subtitulo=empresa.nome, erro=erro, empresa=empresa, codigo_http=codigo_http,
                              historico=_historico_de_acessos(requisicao, empresa, pessoa))

        if requisicao.method == 'GET':
            return tela({}, {})
        dados = requisicao.POST
        erros, cargo, lugar, marcadas, inicio, fim = _ler_acesso(dados, cargos, escopos, categorias)
        if erros:
            return tela(dados, erros, codigo_http=400)
        try:
            delegacao.conceder(requisicao.user, pessoa, cargo, lugar, marcadas, inicio, fim)
        except ValidationError as erro:
            return tela(dados, {}, texto_do_erro(erro), 400)
        except PermissionDenied:
            return tela(dados, {}, SEM_ALCANCE, 403)
    return redirect(cancelar + '?feito=concedido')


# --- escolher a sub-área do convite ---

POR_PAGINA_DO_SELETOR = 50


def _etapa_das_fazendas(requisicao, empresa, volta):
    fazendas = _fazendas_com_sub_areas(requisicao, empresa)
    if not fazendas and not _escopos_do_convite(requisicao, empresa):
        raise PermissionDenied
    return {
        'titulo': 'Escolher a fazenda', 'subtitulo': empresa.nome, 'busca': None, 'voltar': volta,
        'itens': [{'rotulo': f.nome, 'destino': _caminho('convidar_sub_area_fazenda', empresa, fazenda_id=f.pk)} for f in fazendas],
        'vazio': 'Nenhuma fazenda com sub-área onde você possa convidar.', 'pagina': None,
    }


def _etapa_das_sub_areas(requisicao, empresa, fazenda_id, volta):
    fazenda = next(iter(fazendas_autorizadas(requisicao.user, pk=fazenda_id, empresa_id=empresa.pk)), None)
    if fazenda is None:
        raise Http404
    consulta = requisicao.GET.get('q', '').strip()[:100]
    base = _consulta_de_sub_areas(requisicao, fazenda)
    if not base.exists() and not _escopos_do_convite(requisicao, empresa):
        raise PermissionDenied
    filtradas = base.filter(nome__icontains=consulta) if consulta else base
    # Filtro e página no banco: só as 50 sub-áreas da página saem dele, e a trilha pede uma consulta a mais para os pais.
    pagina_de_itens = Paginator(filtradas, POR_PAGINA_DO_SELETOR).get_page(requisicao.GET.get('pagina'))
    da_pagina = list(pagina_de_itens)
    trilhas = _trilhas(requisicao, fazenda, da_pagina)
    return {
        'titulo': 'Escolher a sub-área', 'subtitulo': f'{empresa.nome} › {fazenda.nome}', 'voltar': _caminho('convidar_sub_area', empresa),
        'busca': {'q': consulta}, 'pagina': pagina_de_itens, 'consulta': urlencode({'q': consulta}) if consulta else '',
        'itens': [{'rotulo': trilhas[sub.pk], 'destino': f'{volta}?{urlencode({"escopo": f"sub-area-{sub.pk}"})}'} for sub in da_pagina],
        'vazio': 'Nenhuma sub-área com esse texto.' if consulta else 'Esta fazenda não tem sub-áreas.',
    }


@pagina('convidar_pessoa')
def convidar_sub_area(requisicao, empresa_id, fazenda_id=None):
    """Duas etapas sem JavaScript: primeiro a fazenda, depois a sub-área dela, com filtro por texto (`?q=`) e páginas. Cada
    sub-área é um link para o formulário do convite já com o lugar escolhido; quem decide se vale é o serviço, no envio."""
    empresa = _empresa(requisicao, empresa_id)
    with _contexto(requisicao):
        _com_alcance(requisicao, empresa, 'convidar_pessoa')
        volta = _caminho('pessoas_convidar', empresa)
        if fazenda_id is None:
            contexto = _etapa_das_fazendas(requisicao, empresa, volta)
        else:
            contexto = _etapa_das_sub_areas(requisicao, empresa, fazenda_id, volta)
    return renderizar_na_casca(requisicao, 'escolher_lugar.html', contexto, empresa=empresa)


# --- convites enviados ---


def _tela_de_convites(requisicao, empresa, erro=None, codigo_http=200):
    with _contexto(requisicao):
        _com_alcance(requisicao, empresa, 'convidar_pessoa')
        nomes = {f.pk: f.nome for f in fazendas_autorizadas(requisicao.user, empresa_id=empresa.pk, arquivadas=None)}
        pagina_de_convites = Paginator(convites.convites_enviados(requisicao.user, empresa.pk), ITENS_POR_PAGINA).get_page(requisicao.GET.get('pagina'))
        enviados = list(pagina_de_convites)
        nomes_de_sub_area = _nomes_de_sub_areas(enviados)
        itens = [
            {
                'cargo_nome': c.cargo_nome, 'onde': _onde(c, nomes, nomes_de_sub_area), 'criado_em': c.criado_em, 'expira_em': c.expira_em,
                'vencido': c.expira_em <= timezone.now(),
                'reenviar': _caminho('convite_reenviar', empresa, convite_id=c.pk),
                'cancelar': _caminho('convite_cancelar', empresa, convite_id=c.pk),
            }
            for c in enviados
        ]
        pode_convidar = _pode_convidar(requisicao, empresa)
    contexto = {
        'itens': itens, 'pagina': pagina_de_convites, 'erro': erro, 'aviso': None if erro else _aviso_do_endereco(requisicao),
        'acoes': [{'rotulo': 'Voltar às pessoas', 'destino': _caminho('pessoas', empresa)}],
        'vazio_rotulo': TITULO_CONVIDAR if pode_convidar else None, 'vazio_destino': _caminho('pessoas_convidar', empresa),
    }
    resposta = renderizar_na_casca(requisicao, 'convites_enviados.html', contexto, empresa=empresa)
    resposta.status_code = codigo_http
    return resposta


@pagina('convidar_pessoa')
def convites_enviados(requisicao, empresa_id):
    return _tela_de_convites(requisicao, _empresa(requisicao, empresa_id))


def _agir_no_convite(requisicao, empresa_id, convite_id, funcao, feito):
    empresa = _empresa(requisicao, empresa_id)
    if requisicao.method == 'GET':
        with _contexto(requisicao):
            _com_alcance(requisicao, empresa, 'convidar_pessoa')
        return redirect(_caminho('pessoas_convites', empresa))
    with _contexto(requisicao):
        _com_alcance(requisicao, empresa, 'convidar_pessoa')
        # Só quem convidou mexe no convite; outro id, 404. Mesma checagem da rota: `convidar_pessoa` no lugar do convite.
        alvo = Convite.objects.filter(pk=convite_id, convidado_por=requisicao.user, empresa_id=empresa.pk).first()
        if alvo is None:
            raise Http404
        exigir(requisicao, 'convidar_pessoa', escopo_de(alvo))
        try:
            funcao(requisicao.user, convite_id)
        except ObjectDoesNotExist as erro:
            raise Http404 from erro
        except ValidationError as erro:
            return _tela_de_convites(requisicao, empresa, texto_do_erro(erro), 400)
    return redirect(_caminho('pessoas_convites', empresa) + f'?feito={feito}')


@pagina('convidar_pessoa')
def cancelar_convite(requisicao, empresa_id, convite_id):
    return _agir_no_convite(requisicao, empresa_id, convite_id, convites.cancelar, 'cancelado')


@pagina('convidar_pessoa')
def reenviar_convite(requisicao, empresa_id, convite_id):
    return _agir_no_convite(requisicao, empresa_id, convite_id, convites.reenviar, 'reenviado')


# --- revogar ---


@pagina('revogar_acesso')
def revogar(requisicao, empresa_id, pessoa_id, concessao_id):
    empresa = _empresa(requisicao, empresa_id)
    with _contexto(requisicao):
        _com_alcance(requisicao, empresa, 'revogar_acesso')
        pessoa = _pessoa_da_empresa(requisicao, empresa, pessoa_id)
        concessao = Concessao.objects.select_related('cargo').filter(pk=concessao_id, pessoa_id=pessoa.pk, empresa_id=empresa.pk).first()
        if concessao is None:
            raise Http404
        exigir(requisicao, 'revogar_acesso', escopo_de(concessao))
        cancelar = _caminho('pessoas', empresa)
        erro = None
        if requisicao.method == 'POST':
            try:
                delegacao.revogar_concessao(requisicao.user, concessao)
            except ValidationError as recusa:
                erro = texto_do_erro(recusa)
            else:
                return redirect(cancelar + '?feito=revogado')
        return confirmacao(
            requisicao, cancelar, empresa=empresa, titulo=f'Revogar {concessao.cargo.nome} de {pessoa.nome}?',
            texto='O acesso termina na próxima requisição da pessoa.',
            efeitos=[
                'A concessão não é apagada: a linha fica registrada com a data da revogação e quem revogou.',
                'Os outros acessos da pessoa não mudam.',
                'Para dar o acesso de novo, é preciso conceder outra vez.',
            ],
            botao='Revogar acesso', erro=erro, codigo_http=400 if erro else 200,
        )


# --- redefinir senha ---


@pagina('redefinir_senha')
def redefinir_senha(requisicao, empresa_id, pessoa_id):
    empresa = _empresa(requisicao, empresa_id)
    with _contexto(requisicao):
        exigir(requisicao, 'redefinir_senha', empresa)
        pessoa = _pessoa_da_empresa(requisicao, empresa, pessoa_id)
        # Cargo personalizado com `redefinir_senha` que não é Administrador passa em `exigir`, mas o serviço o recusaria no
        # POST: a confirmação não aparece para quem não pode concluir (Sourcery, PR #30).
        if not redefinicao.pode_iniciar_redefinicao(requisicao.user, pessoa):
            raise PermissionDenied
        cancelar = _caminho('pessoas', empresa)
        if requisicao.method == 'POST':
            try:
                redefinicao.pedir_redefinicao_de_outra_pessoa(requisicao.user, pessoa)
            except ObjectDoesNotExist as erro:
                raise Http404 from erro
            resposta = renderizar_na_casca(requisicao, 'redefinicao_pedida.html', {'destino': cancelar}, empresa=empresa)
            resposta['Cache-Control'] = 'no-store'
            return resposta
        return confirmacao(
            requisicao, cancelar, empresa=empresa, titulo=f'Redefinir a senha de {pessoa.nome}?',
            texto='A pessoa recebe por e-mail um link para escolher uma senha nova.',
            efeitos=[
                'O link vale 10 minutos e funciona uma vez.',
                'A senha atual continua valendo até a pessoa escolher outra.',
                'Você não vê a senha nova.',
            ],
            botao='Enviar link',
        )


# --- titularidade ---


def _candidatos_a_titular(empresa):
    """Quem aparece na lista: Administrador ativo da empresa inteira, sem prazo, que ainda não é o titular. É só a lista;
    `transferir_titularidade` confere de novo sob trava e recusa o resto."""
    ids = concessoes_ativas().filter(
        empresa_id=empresa.pk, fazenda__isnull=True, fim__isnull=True, cargo__base='administrador',
    ).values('pessoa_id')
    return list(Pessoa.objects.filter(pk__in=ids).exclude(pk=empresa.titular_id).order_by('nome', 'pk'))


@pagina('ver')
def titularidade(requisicao, empresa_id):
    empresa = _empresa(requisicao, empresa_id)
    with com_permissao(requisicao.user, 'ver'):
        if not delegacao.pode_transferir_titularidade(requisicao.user, empresa):
            raise PermissionDenied
        candidatos = _candidatos_a_titular(empresa)
        cancelar = _caminho('pessoas', empresa)
        dados = requisicao.POST if requisicao.method == 'POST' else {}
        escolhido = next((p for p in candidatos if str(p.pk) == dados.get('novo_titular')), None)
        justificativa = dados.get('justificativa', '').strip()

        def etapa_1(erros=None, codigo_http=200):
            erros = erros or {}
            campos = [
                campo('novo_titular', 'Novo titular', dados.get('novo_titular', ''), erros.get('novo_titular'), tipo='select', obrigatorio=True,
                      ajuda='Só aparece quem é Administrador da empresa inteira, sem prazo.',
                      opcoes=[ESCOLHA_VAZIA, *({'valor': p.pk, 'rotulo': f'{p.nome} ({p.email})'} for p in candidatos)]),
                campo('justificativa', 'Justificativa', justificativa, erros.get('justificativa'), obrigatorio=True,
                      ajuda='Fica registrada na auditoria, com o seu nome e a data.'),
            ]
            return formulario(requisicao, TITULO_TITULARIDADE, campos, 'Continuar', cancelar, empresa=empresa, escondidos={'etapa': '1'},
                              subtitulo='Etapa 1 de 2: escolha quem recebe o título de titular. Nada muda ainda.', codigo_http=codigo_http)

        def etapa_2(erro=None, erro_do_campo=None, codigo_http=200):
            campos = [campo('confirmacao', f'Para confirmar, digite o nome da empresa: {empresa.nome}', '', erro_do_campo, obrigatorio=True)]
            return formulario(
                requisicao, TITULO_TITULARIDADE, campos, 'Transferir titularidade', cancelar, empresa=empresa, erro=erro, codigo_http=codigo_http,
                escondidos={'etapa': '2', 'novo_titular': escolhido.pk if escolhido else '', 'justificativa': justificativa},
                subtitulo=f'Etapa 2 de 2: {escolhido.nome if escolhido else ""} passa a ser o titular de {empresa.nome}; quem é titular hoje vira Administrador comum.',
            )

        if requisicao.method == 'GET':
            return etapa_1()
        erros = {}
        if escolhido is None:
            erros['novo_titular'] = 'Escolha uma pessoa da lista.'
        if not justificativa:
            erros['justificativa'] = 'Informe a justificativa da transferência.'
        if erros or dados.get('etapa') not in ('1', '2'):
            return etapa_1(erros, 400)
        if dados['etapa'] == '1':
            return etapa_2()
        if dados.get('confirmacao', '').strip() != empresa.nome:
            return etapa_2(erro_do_campo='O nome digitado não é o da empresa.', codigo_http=400)
        try:
            delegacao.transferir_titularidade(requisicao.user, empresa, escolhido, justificativa)
        except ValidationError as erro:
            return etapa_2(erro=texto_do_erro(erro), codigo_http=400)
    return redirect(cancelar + '?feito=titularidade')
