"""Telas de cargos (003 R18): lista da empresa, criar e editar, com a matriz de permissões em português.

Nenhuma regra de negócio aqui (R28): a view resolve a empresa da URL (fora do alcance, 404 igual ao de inexistente), confere o
alcance e entrega a gravação a `gerenciar_cargo`, a mesma função da API e do painel. Negado vira 403; regra violada, o texto da
`ValidationError` volta à tela; edição sobre versão velha volta com 409 e o cargo recarregado. A base e a empresa do cargo
não mudam depois de criado (gatilho do banco, D075): na edição aparecem como texto, não como campo.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.http import Http404
from django.shortcuts import redirect

from permissao import cargo as servico
from permissao.cargos_base import NOMES
from permissao.models import Cargo, Permissao
from permissao.pode import ACOES_DA_PLATAFORMA, com_permissao, unir_escopos
from permissao.uso import registrar_uso
from projeto.paginas_autenticadas import campo, formulario, pagina, renderizar_na_casca, texto_do_erro
from projeto.pessoas_paginas import ESCOLHA_VAZIA, _aviso_do_endereco, _caminho, _empresa

TITULO_CRIAR = 'Criar cargo'
SEM_ALCANCE = 'Você não pode criar nem alterar este cargo: ele tem nível ou permissões acima das suas.'
# A matriz de permissões em grupos por área, na ordem em que a tela os mostra (mercado: o Azure agrupa por provedor de recurso, o
# GitHub por área e a AWS por nível de acesso, e marca o de gestão de acesso como o mais sensível). "Pessoas e cargos" vai por
# último, com aviso, porque quem as tem controla o acesso de outras pessoas. Ação do catálogo que ainda não entrou aqui aparece
# em "Outras permissões", nunca some da tela; o teste do arquivo falha até ela ganhar grupo.
GRUPOS_DE_PERMISSOES = (
    ('Consulta', ('ver', 'baixar_pacote_offline'), None),
    ('Trabalho de campo', ('criar_registro_campo', 'propor_alteracao_atributo', 'revisar_trabalho_de_outro'), None),
    ('Documentos', ('baixar_documento', 'subir_documento', 'definir_validade_documento'), None),
    ('Validação e aprovação', ('validar_registro', 'validar_atributo', 'conferir_revisao_enviada', 'enviar_revisao_camada',
                               'aprovar_atributo', 'aprovar_geometria', 'tornar_revisao_vigente', 'publicar_camada'), None),
    ('Território', ('criar_fazenda', 'criar_sub_area', 'renomear', 'arquivar', 'desarquivar', 'configurar_niveis_divisao'), None),
    ('Configurações', ('configurar_prazos_escalada', 'configurar_categorias_campos', 'ajustar_expiracao_pacote'), None),
    ('Pessoas e cargos', ('convidar_pessoa', 'revogar_acesso', 'redefinir_senha', 'gerenciar_cargo'),
     'Quem tem estas permissões controla o acesso de outras pessoas.'),
)
AJUDA_DA_MATRIZ = 'Você só marca o que o seu próprio acesso permite.'
# Código da `ValidationError` do serviço → campo da tela que mostra o texto (o resto vai para o aviso do topo).
CAMPO_DO_ERRO = {'nome_invalido': 'nome', 'nome_duplicado': 'nome', 'permissao_invalida': 'permissoes', 'base_invalida': 'base'}


def _contexto(requisicao):
    return com_permissao(requisicao.user, 'gerenciar_cargo', 'ver')


def _com_alcance(requisicao, empresa):
    """Cargo é da empresa: `gerenciar_cargo` só vale com a empresa inteira. Quem o tem só numa fazenda ou sub-área recebe 403
    em vez de um formulário que o serviço recusaria no envio (Qodo, PR #31)."""
    escopos = unir_escopos(requisicao.user, 'gerenciar_cargo')
    if not (escopos.plataforma or empresa.pk in escopos.empresas):
        raise PermissionDenied


@pagina('gerenciar_cargo')
def cargos(requisicao, empresa_id):
    empresa = _empresa(requisicao, empresa_id)
    with _contexto(requisicao):
        _com_alcance(requisicao, empresa)
        lista = Cargo.objects.filter(empresa_id=empresa.pk).annotate(total=Count('permissoes')).order_by('nome').values('pk', 'nome', 'base', 'total')
        itens = [
            {'nome': c['nome'], 'base': NOMES[c['base']], 'empresa': empresa.nome, 'total': c['total'],
             'editar': None if c['base'] in servico.BASES_FIXAS else _caminho('cargo_editar', empresa, cargo_id=c['pk'])}
            for c in lista
        ]
    contexto = {'itens': itens, 'aviso': _aviso_do_endereco(requisicao), 'acoes': [{'rotulo': TITULO_CRIAR, 'destino': _caminho('cargo_novo', empresa)}]}
    return renderizar_na_casca(requisicao, 'cargos.html', contexto, empresa=empresa)


def _permissoes_do_catalogo():
    """Todas as ações que cabem num cargo, pela descrição em português; as da plataforma nunca entram em cargo."""
    return list(Permissao.objects.exclude(codigo__in=ACOES_DA_PLATAFORMA).order_by('descricao'))


def _grupos_da_matriz(catalogo):
    """`[(título, [permissões], aviso)]` na ordem de `GRUPOS_DE_PERMISSOES`; o que não tem grupo vai para "Outras permissões"."""
    por_codigo = {p.pk: p for p in catalogo}
    grupos = [(titulo, [por_codigo[c] for c in codigos if c in por_codigo], aviso) for titulo, codigos, aviso in GRUPOS_DE_PERMISSOES]
    classificadas = {c for _, codigos, _ in GRUPOS_DE_PERMISSOES for c in codigos}
    sobra = [p for p in catalogo if p.pk not in classificadas]
    # "Pessoas e cargos" (o aviso de quem controla acesso) fica sempre por último; o que não tem grupo entra logo antes.
    return [g for g in [*grupos[:-1], ('Outras permissões', sobra, None), grupos[-1]] if g[1]]


def _campos(dados, erros, catalogo, base_fixa=None):
    marcadas = set(dados.getlist('permissoes')) if hasattr(dados, 'getlist') else set(dados.get('permissoes', ()))
    # Um conjunto de caixas por grupo, todas com o nome `permissoes`; o erro do conjunto fica no primeiro (`campo_permissoes`).
    grupos = [
        campo('permissoes', titulo, tipo='caixas', id='campo_permissoes' if i == 0 else f'campo_permissoes_{i}',
              erro=erros.get('permissoes') if i == 0 else None, ajuda=aviso,
              opcoes=[{'valor': p.pk, 'rotulo': p.descricao, 'marcada': p.pk in marcadas} for p in permissoes])
        for i, (titulo, permissoes, aviso) in enumerate(_grupos_da_matriz(catalogo))
    ]
    return [
        campo('nome', 'Nome do cargo', dados.get('nome', ''), erros.get('nome'), obrigatorio=True),
        *([] if base_fixa else [campo('base', 'Nível do cargo', dados.get('base', ''), erros.get('base'), tipo='select', obrigatorio=True,
                                      ajuda='Não muda depois de criado.',
                                      opcoes=[ESCOLHA_VAZIA, *({'valor': base, 'rotulo': nome} for base, nome in NOMES.items() if base not in servico.BASES_FIXAS)])]),
        *grupos,
    ]


def _gravar(requisicao, empresa, dados, cargo, base):
    """Chama o serviço. Devolve `(erros por campo, aviso do topo, código HTTP)`; sem problema, `({}, None, 200)`."""
    versao = dados.get('versao', '')
    try:
        servico.gerenciar_cargo(
            requisicao.user, empresa, dados.get('nome', ''), dados.getlist('permissoes'), base=base, cargo=cargo,
            versao=int(versao) if versao.isascii() and versao.isdigit() else None,
        )
    except ValidationError as erro:
        campo_do_erro = CAMPO_DO_ERRO.get(erro.code or '')
        if campo_do_erro:
            return {campo_do_erro: texto_do_erro(erro)}, None, 400
        return {}, texto_do_erro(erro), 409 if erro.code == 'cargo_alterado_por_outra_pessoa' else 400
    except PermissionDenied:
        return {}, SEM_ALCANCE, 403
    return {}, None, 200


@pagina('gerenciar_cargo')
def cargo_novo(requisicao, empresa_id):
    empresa = _empresa(requisicao, empresa_id)
    with _contexto(requisicao):
        _com_alcance(requisicao, empresa)
        catalogo = _permissoes_do_catalogo()
        cancelar = _caminho('cargos', empresa)

        def tela(dados, erros, erro=None, codigo_http=200):
            return formulario(requisicao, TITULO_CRIAR, _campos(dados, erros, catalogo), TITULO_CRIAR, cancelar,
                              subtitulo=f'{empresa.nome}. {AJUDA_DA_MATRIZ}', erro=erro, empresa=empresa, codigo_http=codigo_http)

        if requisicao.method == 'GET':
            return tela({}, {})
        dados = requisicao.POST
        if dados.get('base') not in NOMES or dados['base'] in servico.BASES_FIXAS:  # só o formato; a regra de quem cria qual nível é do serviço
            return tela(dados, {'base': 'Escolha o nível do cargo.'}, codigo_http=400)
        erros, erro, codigo = _gravar(requisicao, empresa, dados, None, dados['base'])
        if codigo != 200:
            return tela(dados, erros, erro, codigo)
    registrar_uso(requisicao.user, 'gerenciar_cargo')
    return redirect(cancelar + '?feito=criado')


@pagina('gerenciar_cargo')
def cargo_editar(requisicao, empresa_id, cargo_id):
    empresa = _empresa(requisicao, empresa_id)
    with _contexto(requisicao):
        _com_alcance(requisicao, empresa)
        cargo = Cargo.objects.filter(pk=cargo_id, empresa_id=empresa.pk).first()
        if cargo is None:
            raise Http404
        if cargo.base in servico.BASES_FIXAS:  # só leitura (mantenedor, 2026-11-02); o serviço também recusa
            raise PermissionDenied
        catalogo = _permissoes_do_catalogo()
        cancelar = _caminho('cargos', empresa)

        def tela(dados, erros, erro=None, codigo_http=200, versao=None):
            # Erro de validação devolve a versão que a pessoa leu: a do banco pode ser de outra edição, e reenviar com ela
            # sobrescreveria a mudança sem o 409 (Codex, Greptile e Qodo, PR #31). Só recarregar dados e versão juntos.
            return formulario(requisicao, f'Editar {cargo.nome}', _campos(dados, erros, catalogo, base_fixa=cargo.base), 'Salvar cargo',
                              cancelar, subtitulo=f'{empresa.nome} · nível {NOMES[cargo.base]}, que não muda. {AJUDA_DA_MATRIZ}', erro=erro, empresa=empresa,
                              escondidos={'versao': cargo.versao if versao is None else versao}, codigo_http=codigo_http)

        def dados_atuais():
            return {'nome': cargo.nome, 'permissoes': {p.codigo for p in cargo.permissoes.all()}}

        if requisicao.method == 'GET':
            return tela(dados_atuais(), {})
        erros, erro, codigo = _gravar(requisicao, empresa, requisicao.POST, cargo, None)
        if codigo == 409:  # o cargo mudou: recarrega o que está gravado, com a versão nova, para editar de novo
            cargo.refresh_from_db()
            return tela(dados_atuais(), {}, erro, codigo)
        if codigo != 200:
            return tela(requisicao.POST, erros, erro, codigo, versao=requisicao.POST.get('versao', ''))
    registrar_uso(requisicao.user, 'gerenciar_cargo')
    return redirect(cancelar + '?feito=alterado')
