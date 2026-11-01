"""Telas de gestão do território (003 R9 a R12): criar, renomear, níveis, arquivar e desarquivar.

Nenhuma regra de negócio aqui (R28): a view resolve o escopo da URL (fora do alcance, 404 igual ao de inexistente),
pergunta `pode()` (com alcance e sem a ação, 403) e chama a mesma função de serviço que a API chama. O texto de erro vem
da exceção do serviço. Arquivar e desarquivar têm tela de confirmação que diz o que o ato atinge; nada é apagado.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from permissao.pode import com_permissao, permissoes_efetivas, pode
from projeto.escopo import resolver_escopo
from projeto.paginas_autenticadas import exige_acao, exige_entrada, renderizar_na_casca
from territorio import cadastro, niveis
from territorio.listagem import empresas_autorizadas, fazendas_autorizadas, sub_areas_da_fazenda
from territorio.models import Empresa, Fazenda, SubArea

LEITURA_E_ESCRITA = require_http_methods(['GET', 'POST'])


def _pagina(acao):
    """Portão de sessão, métodos GET e POST e a ação do catálogo que a página declara (varredura de views, R22)."""

    def declarar(visao):
        return LEITURA_E_ESCRITA(exige_entrada(exige_acao(acao)(visao)))

    return declarar


def caminho_de(alvo):
    """Página própria do alvo: empresa e fazenda têm uma; a sub-área vive na página da fazenda dela."""
    if isinstance(alvo, Empresa):
        return reverse('empresa', kwargs={'empresa_id': alvo.pk})
    return reverse('fazenda', kwargs={'empresa_id': alvo.empresa_id, 'fazenda_id': alvo.fazenda_id if isinstance(alvo, SubArea) else alvo.pk})


def _argumentos(alvo):
    if isinstance(alvo, Empresa):
        return {'empresa_id': alvo.pk}
    if isinstance(alvo, Fazenda):
        return {'empresa_id': alvo.empresa_id, 'fazenda_id': alvo.pk}
    return {'empresa_id': alvo.empresa_id, 'fazenda_id': alvo.fazenda_id, 'sub_area_id': alvo.pk}


# (ação do catálogo, texto, nome da URL, objeto só vale abaixo do nível 3): o que cada página oferece, por tipo de alvo.
_ACOES_DA_PAGINA = {
    Empresa: (
        ('criar_fazenda', 'Cadastrar fazenda', 'fazenda_nova'),
        ('renomear', 'Renomear empresa', 'empresa_editar'),
        ('configurar_niveis_divisao', 'Nomes dos níveis da divisão', 'empresa_niveis'),
        ('arquivar', 'Arquivar empresa', 'empresa_arquivar'),
    ),
    Fazenda: (
        ('criar_sub_area', 'Cadastrar sub-área', 'sub_area_nova'),
        ('renomear', 'Renomear fazenda', 'fazenda_editar'),
        ('arquivar', 'Arquivar fazenda', 'fazenda_arquivar'),
    ),
    SubArea: (
        ('criar_sub_area', 'Cadastrar dentro desta', 'sub_area_nova'),
        ('arquivar', 'Arquivar sub-área', 'sub_area_arquivar'),
    ),
}
_DESARQUIVAR = {Empresa: 'empresa_desarquivar', Fazenda: 'fazenda_desarquivar', SubArea: 'sub_area_desarquivar'}


def acoes_do_alvo(alvo, efetivas):
    """Links de gestão da página do alvo, só os que a permissão efetiva permite (o servidor decide de novo ao clicar).
    Arquivado: só `desarquivar`, o resto seria negado por `pode()` (R11)."""
    tipo = type(alvo)
    argumentos = _argumentos(alvo)
    if alvo.arquivada_em is not None:
        return [{'rotulo': 'Desarquivar', 'destino': reverse(_DESARQUIVAR[tipo], kwargs=argumentos)}] if 'desarquivar' in efetivas else []
    acoes = []
    for acao, rotulo, nome in _ACOES_DA_PAGINA[tipo]:
        if acao not in efetivas or (acao == 'criar_sub_area' and tipo is SubArea and alvo.nivel >= cadastro.NIVEL_MAXIMO):
            continue
        # As telas de cadastro ("_nova") vivem na fazenda ou na empresa: não levam o id da sub-área, só o pai na consulta.
        destino = reverse(nome, kwargs={k: v for k, v in argumentos.items() if not (nome.endswith('_nova') and k == 'sub_area_id')})
        acoes.append({'rotulo': rotulo, 'destino': f'{destino}?pai={alvo.pk}' if nome == 'sub_area_nova' and tipo is SubArea else destino})
    return acoes


def _campo(nome, rotulo, valor='', erro=None, ajuda=None, **extra):
    return {'id': f'campo_{nome}', 'nome': nome, 'rotulo': rotulo, 'valor': valor, 'erro': erro, 'ajuda': ajuda, **extra}


def _texto(erro):
    return ' '.join(erro.messages)


def _formulario(requisicao, titulo, campos, botao, cancelar, *, subtitulo=None, erro=None, empresa=None, fazenda=None, acoes=(), escondidos=None, status=200):
    contexto = {
        'titulo': titulo, 'subtitulo': subtitulo, 'campos': campos, 'botao': botao, 'cancelar': cancelar,
        'erro': erro, 'acoes': list(acoes), 'escondidos': escondidos or {},
    }
    resposta = renderizar_na_casca(requisicao, 'formulario.html', contexto, empresa=empresa, fazenda=fazenda)
    resposta.status_code = status
    return resposta


def _exigir(requisicao, acao, alvo=None):
    if not pode(requisicao.user, acao, alvo):
        raise PermissionDenied


def _resolver(requisicao, empresa_id, fazenda_id=None, sub_area_id=None):
    """`(empresa, fazenda, alvo)`; o alvo é a sub-área, a fazenda ou a empresa mais específica da URL. Escopo arquivado
    resolve (a leitura segue valendo) e `pode()` nega a escrita."""
    empresa, fazenda = resolver_escopo(requisicao.user, empresa_id, fazenda_id)
    if sub_area_id is None:
        return empresa, fazenda, fazenda or empresa
    sub_area = next((s for s in sub_areas_da_fazenda(requisicao.user, fazenda, arquivadas=None) if s.pk == sub_area_id), None)
    if sub_area is None:
        raise Http404
    return empresa, fazenda, sub_area


# --- criar ---


@_pagina('criar_empresa')
def empresa_nova(requisicao):
    with com_permissao(requisicao.user, 'criar_empresa', 'ver'):
        _exigir(requisicao, 'criar_empresa')
        dados = requisicao.POST if requisicao.method == 'POST' else {}
        campos = [
            _campo('nome', 'Nome da empresa', dados.get('nome', ''), obrigatorio=True),
            _campo('nome_administrador', 'Nome do primeiro Administrador', dados.get('nome_administrador', ''), obrigatorio=True, autocomplete='name'),
            _campo('email_administrador', 'E-mail do Administrador', dados.get('email_administrador', ''), tipo='email', obrigatorio=True, autocomplete='email'),
            _campo('cpf_administrador', 'CPF do Administrador', dados.get('cpf_administrador', ''), obrigatorio=True, teclado='numeric'),
        ]
        cancelar = reverse('empresas')
        if requisicao.method == 'GET':
            return _formulario(requisicao, 'Nova empresa', campos, 'Criar empresa', cancelar)
        try:
            empresa, administrador, temporaria = cadastro.criar_empresa(
                requisicao.user, dados.get('nome', ''), dados.get('nome_administrador', ''),
                dados.get('email_administrador', ''), dados.get('cpf_administrador', ''),
            )
        except ValidationError as erro:
            return _formulario(requisicao, 'Nova empresa', campos, 'Criar empresa', cancelar, erro=_texto(erro), status=400)
        # A senha temporária aparece uma vez, no corpo desta resposta: nunca em redirecionamento nem em sessão.
        resposta = render(requisicao, 'empresa_criada.html', {
            'empresa': empresa, 'administrador': administrador, 'senha_temporaria': temporaria,
            'destino': caminho_de(empresa),
        })
        resposta['Cache-Control'] = 'no-store'
        return resposta


@_pagina('criar_fazenda')
def fazenda_nova(requisicao, empresa_id):
    empresa, _, _ = _resolver(requisicao, empresa_id)
    with com_permissao(requisicao.user, 'criar_fazenda', 'ver'):
        _exigir(requisicao, 'criar_fazenda', empresa)
        nome = requisicao.POST.get('nome', '') if requisicao.method == 'POST' else ''
        campos = [_campo('nome', 'Nome da fazenda', nome, obrigatorio=True)]
        cancelar = caminho_de(empresa)
        if requisicao.method == 'GET':
            return _formulario(requisicao, 'Nova fazenda', campos, 'Cadastrar fazenda', cancelar, empresa=empresa)
        try:
            fazenda = cadastro.criar_fazenda(requisicao.user, empresa, nome)
        except ValidationError as erro:
            campos[0]['erro'] = _texto(erro)
            return _formulario(requisicao, 'Nova fazenda', campos, 'Cadastrar fazenda', cancelar, empresa=empresa, status=400)
        return redirect(caminho_de(fazenda))


@_pagina('criar_sub_area')
def sub_area_nova(requisicao, empresa_id, fazenda_id):
    empresa, fazenda, _ = _resolver(requisicao, empresa_id, fazenda_id)
    with com_permissao(requisicao.user, 'criar_sub_area', 'ver'):
        pai_id = requisicao.POST.get('pai', '') if requisicao.method == 'POST' else requisicao.GET.get('pai', '')
        pai = None
        if pai_id:
            if not pai_id.isdigit():
                raise Http404
            pai = next((s for s in sub_areas_da_fazenda(requisicao.user, fazenda) if s.pk == int(pai_id)), None)
            if pai is None:
                raise Http404
        _exigir(requisicao, 'criar_sub_area', pai or fazenda)
        nivel = 1 if pai is None else pai.nivel + 1
        nome_do_nivel = niveis.nome_do_nivel(empresa, nivel) if nivel <= cadastro.NIVEL_MAXIMO else ''
        nome = requisicao.POST.get('nome', '') if requisicao.method == 'POST' else ''
        campos = [_campo('nome', f'Nome de {nome_do_nivel.lower()}', nome, obrigatorio=True)]
        titulo = 'Nova sub-área'
        subtitulo = f'{nome_do_nivel}' + (f', dentro de {pai.nome}' if pai else '')
        botao = f'Cadastrar {nome_do_nivel.lower()}'
        cancelar = caminho_de(fazenda)
        escondido = {'pai': pai.pk} if pai else {}
        if requisicao.method == 'GET':
            return _formulario(requisicao, titulo, campos, botao, cancelar, subtitulo=subtitulo, empresa=empresa, fazenda=fazenda, escondidos=escondido)
        try:
            cadastro.criar_sub_area(requisicao.user, fazenda, nome, pai)
        except ValidationError as erro:
            campos[0]['erro'] = _texto(erro)
            return _formulario(requisicao, titulo, campos, botao, cancelar, subtitulo=subtitulo, empresa=empresa, fazenda=fazenda, escondidos=escondido, status=400)
        return redirect(caminho_de(fazenda))


# --- renomear e níveis ---


@_pagina('renomear')
def renomear(requisicao, empresa_id, fazenda_id=None, sub_area_id=None):
    empresa, fazenda, alvo = _resolver(requisicao, empresa_id, fazenda_id, sub_area_id)
    with com_permissao(requisicao.user, 'renomear', 'criar_sub_area', 'arquivar', 'desarquivar', 'ver'):
        _exigir(requisicao, 'renomear', alvo)
        nome = requisicao.POST.get('nome', alvo.nome) if requisicao.method == 'POST' else alvo.nome
        campos = [_campo('nome', 'Nome', nome, obrigatorio=True)]
        funcao = {Empresa: cadastro.renomear_empresa, Fazenda: cadastro.renomear_fazenda, SubArea: cadastro.renomear_sub_area}[type(alvo)]
        acoes = acoes_do_alvo(alvo, permissoes_efetivas(requisicao.user, alvo))
        if requisicao.method == 'POST':
            try:
                funcao(requisicao.user, alvo, nome)
            except ValidationError as erro:
                campos[0]['erro'] = _texto(erro)
                return _formulario(requisicao, f'Renomear {alvo.nome}', campos, 'Salvar nome', caminho_de(alvo), empresa=empresa, fazenda=fazenda, acoes=acoes, status=400)
            return redirect(caminho_de(alvo))
        return _formulario(requisicao, f'Renomear {alvo.nome}', campos, 'Salvar nome', caminho_de(alvo), empresa=empresa, fazenda=fazenda, acoes=acoes)


@_pagina('configurar_niveis_divisao')
def niveis_da_empresa(requisicao, empresa_id):
    empresa, _, _ = _resolver(requisicao, empresa_id)
    with com_permissao(requisicao.user, 'configurar_niveis_divisao', 'ver'):
        _exigir(requisicao, 'configurar_niveis_divisao', empresa)
        atuais = niveis.nomes_configurados(empresa)
        enviados = requisicao.POST if requisicao.method == 'POST' else {}
        valores = {n: enviados.get(f'nivel_{n}', atuais.get(n, '')) for n in range(1, cadastro.NIVEL_MAXIMO + 1)}
        campos = [
            _campo(f'nivel_{n}', f'Nome do nível {n}', valores[n], ajuda='Em branco, a tela mostra "Nível %d".' % n)
            for n in valores
        ]
        cancelar = caminho_de(empresa)
        if requisicao.method == 'POST':
            falhou = False
            for campo, (n, valor) in zip(campos, valores.items()):
                if not valor.strip() or valor.strip() == atuais.get(n):
                    continue  # em branco não apaga: o nome some só ao trocar por outro (inferência a confirmar)
                try:
                    niveis.definir_nivel(requisicao.user, empresa, n, valor)
                except ValidationError as erro:
                    campo['erro'] = _texto(erro)
                    falhou = True
            if not falhou:
                return redirect(cancelar)
            return _formulario(requisicao, 'Nomes dos níveis da divisão', campos, 'Salvar nomes', cancelar, empresa=empresa, status=400)
        return _formulario(requisicao, 'Nomes dos níveis da divisão', campos, 'Salvar nomes', cancelar, empresa=empresa)


# --- arquivar e desarquivar ---


def _confirmacao(requisicao, empresa, fazenda, alvo, *, titulo, texto, efeitos, botao):
    contexto = {
        'titulo': titulo, 'texto': texto, 'efeitos': efeitos, 'botao': botao, 'cancelar': caminho_de(alvo),
    }
    return renderizar_na_casca(requisicao, 'confirmacao.html', contexto, empresa=empresa, fazenda=fazenda)


def _plural(n, singular, plural):
    return f'{n} {singular if n == 1 else plural}'


@_pagina('arquivar')
def arquivar(requisicao, empresa_id, fazenda_id=None, sub_area_id=None):
    empresa, fazenda, alvo = _resolver(requisicao, empresa_id, fazenda_id, sub_area_id)
    with com_permissao(requisicao.user, 'arquivar', 'ver'):
        _exigir(requisicao, 'arquivar', alvo)
        if requisicao.method == 'POST':
            cadastro.arquivar(requisicao.user, alvo)
            return redirect(caminho_de(alvo))
        fazendas, sub_areas, convites = cadastro.efeitos_do_arquivamento(alvo)
        efeitos = [
            f'{_plural(fazendas, "fazenda arquivada junto", "fazendas arquivadas junto")}.',
            f'{_plural(sub_areas, "sub-área arquivada junto", "sub-áreas arquivadas junto")}.',
            f'{_plural(convites, "convite pendente cancelado", "convites pendentes cancelados")}; ele não volta ao desarquivar.',
            'Nada é apagado. Acessos e dados ficam como estão, só em leitura.',
        ]
        return _confirmacao(
            requisicao, empresa, fazenda, alvo, titulo=f'Arquivar {alvo.nome}?', efeitos=efeitos, botao='Arquivar',
            texto='Arquivado, o item sai das listas de trabalho e não aceita mais alteração, mas segue consultável.',
        )


@_pagina('desarquivar')
def desarquivar(requisicao, empresa_id, fazenda_id=None, sub_area_id=None):
    empresa, fazenda, alvo = _resolver(requisicao, empresa_id, fazenda_id, sub_area_id)
    with com_permissao(requisicao.user, 'desarquivar', 'ver'):
        _exigir(requisicao, 'desarquivar', alvo)
        if requisicao.method == 'POST':
            try:
                cadastro.desarquivar(requisicao.user, alvo)
            except ValidationError as erro:
                return _recusa(requisicao, empresa, fazenda, alvo, erro)
            return redirect(caminho_de(alvo))
        return _confirmacao(
            requisicao, empresa, fazenda, alvo, titulo=f'Desarquivar {alvo.nome}?',
            texto='Volta às listas de trabalho junto com o que foi arquivado no mesmo ato.',
            efeitos=['Convites cancelados no arquivamento não voltam; o Administrador reenvia.'], botao='Desarquivar',
        )


def _recusa(requisicao, empresa, fazenda, alvo, erro):
    resposta = _confirmacao(
        requisicao, empresa, fazenda, alvo, titulo=f'Desarquivar {alvo.nome}?', texto=_texto(erro), efeitos=[], botao='Tentar de novo',
    )
    resposta.status_code = 400
    return resposta


# --- seção Arquivadas ---


@require_GET
@exige_entrada
@exige_acao('ver')
def arquivadas(requisicao):
    """Empresas e fazendas arquivadas que a pessoa alcançava (R11); desarquivar só aparece a quem pode."""
    itens = []
    for alvo in (*empresas_autorizadas(requisicao.user, arquivadas=True), *fazendas_autorizadas(requisicao.user, arquivadas=True)):
        acoes = acoes_do_alvo(alvo, permissoes_efetivas(requisicao.user, alvo))
        itens.append({'nome': alvo.nome, 'tipo': 'Empresa' if isinstance(alvo, Empresa) else 'Fazenda', 'caminho': caminho_de(alvo), 'acoes': acoes})
    return renderizar_na_casca(requisicao, 'arquivadas.html', {'itens': itens})
