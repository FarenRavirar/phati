"""Página /auditoria/ (005 R6, R7; A1, A2, A4, A7): lista, filtros, paginação por cursor e acesso negado por URL direta."""

import re
from datetime import datetime, timedelta
from html import unescape

import pytest
from django.test import Client
from django.utils import timezone

from comum.auditoria import auditar
from comum.models import EventoAuditoria
from identidade.models import Pessoa
from permissao import auditoria_leitura
from permissao.models import Cargo, CargoPermissao, Permissao
from projeto import auditoria_paginas

pytestmark = pytest.mark.django_db

CAMINHO = '/auditoria/'
MENSAGEM_DO_FILTRO = 'Filtro inválido: confira as datas, a ação, as pessoas e a empresa escolhidas.'
SEM_EVENTOS = 'Nenhum evento neste período.'


@pytest.fixture
def plataforma_logada(conta):
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    return conta


def _evento(acao, pessoa, empresa, alvo=None, detalhes=None, quando=None):
    """Grava pela função de auditoria (a mesma da ação real) e, se pedido, fixa a hora para testar o período."""
    evento = auditar(acao, pessoa, alvo, empresa.pk if empresa is not None else None, detalhes)
    if quando is not None:
        EventoAuditoria.objects.filter(pk=evento.pk).update(hora_servidor=quando)
    return evento


def _consultadas():
    return EventoAuditoria.objects.filter(acao='auditoria_consultada').count()


def _linhas(resposta):
    """Texto de cada célula do `<tbody>`, sem as tags. A página tem `<option>` com os mesmos rótulos: por isso só a tabela conta."""
    tabela = re.search(r'<tbody>(.*?)</tbody>', resposta.content.decode(), re.S)
    if tabela is None:
        return []
    return [
        [unescape(re.sub(r'<[^>]+>', '', celula)).strip() for celula in re.findall(r'<td>(.*?)</td>', linha, re.S)]
        for linha in re.findall(r'<tr>(.*?)</tr>', tabela.group(1), re.S)
    ]


def _admin_de_x(cliente, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    return cliente


# --- caminho feliz ---


def test_lista_mostra_hora_acao_quem_alvo_empresa_e_resumo(cliente_logado, plataforma_logada, cenario):
    _evento('empresa_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.x)
    resposta = cliente_logado.get(CAMINHO)
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert '<caption>Eventos da auditoria</caption>' in html
    assert '<th scope="col">Hora</th>' in html
    assert '<th scope="col">Resumo</th>' in html
    assert re.fullmatch(r'\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}', _linhas(resposta)[0][0])
    assert _linhas(resposta) == [[_linhas(resposta)[0][0], 'Empresa criada', 'Fulana Sintetica', 'Empresa: Empresa X', 'Empresa X', '']]


def test_filtro_de_periodo_inclui_o_ultimo_dia_inteiro(cliente_logado, plataforma_logada, cenario):
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f1, quando=timezone.make_aware(datetime(2024, 5, 10, 12)))
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f1, quando=timezone.make_aware(datetime(2024, 6, 10, 12)))
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f2, quando=timezone.make_aware(datetime(2024, 6, 30, 23, 30)))
    linhas = _linhas(cliente_logado.get(CAMINHO, {'desde': '2024-06-01', 'ate': '2024-06-30'}))
    assert [linha[3] for linha in linhas] == ['Fazenda: F2', 'Fazenda: F1']  # o de 30/06 às 23:30 entra; o de maio não


def test_filtro_de_acao_so_mostra_a_acao_escolhida(cliente_logado, plataforma_logada, cenario):
    _evento('empresa_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.x)
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f1)
    linhas = _linhas(cliente_logado.get(CAMINHO, {'acao': 'fazenda_criada'}))
    assert [linha[1] for linha in linhas] == ['Fazenda criada']


def test_paginacao_por_cursor_mais_antigos_preserva_filtro_e_nao_grava(cliente_logado, plataforma_logada, cenario):
    for _ in range(31):
        _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f1)
    primeira = cliente_logado.get(CAMINHO, {'acao': 'fazenda_criada'})
    assert len(_linhas(primeira)) == 30
    link = re.search(r'<nav class="paginacao".*?href="([^"]+)"', primeira.content.decode(), re.S)
    assert link is not None
    href = unescape(link.group(1))
    assert href.startswith('?')
    assert 'acao=fazenda_criada' in href
    assert 'depois=' in href

    antes = _consultadas()
    segunda = cliente_logado.get(CAMINHO + href)
    assert len(_linhas(segunda)) == 1  # o trigésimo primeiro evento
    assert 'Mais antigos' not in segunda.content.decode()  # sem mais páginas, sem link
    assert _consultadas() == antes  # paginar não grava consulta (A7)


def test_estado_vazio_com_mensagem_e_sem_tabela(cliente_logado, plataforma_logada):
    resposta = cliente_logado.get(CAMINHO, {'desde': '2000-01-01', 'ate': '2000-01-31'})
    assert resposta.status_code == 200
    assert SEM_EVENTOS in resposta.content.decode()
    assert '<tbody>' not in resposta.content.decode()


def test_cada_primeira_pagina_grava_uma_consulta_e_a_paginacao_nao(cliente_logado, plataforma_logada):
    antes = _consultadas()
    cliente_logado.get(CAMINHO)
    assert _consultadas() == antes + 1
    cliente_logado.get(CAMINHO, {'depois': 1})
    assert _consultadas() == antes + 1


def test_administrador_de_empresa_nao_ve_eventos_de_outra_empresa(cliente_logado, conta, cenario, conceder_direto):
    _admin_de_x(cliente_logado, conta, cenario, conceder_direto)
    _evento('empresa_criada', conta.pessoa, cenario.y, alvo=cenario.y)
    _evento('empresa_criada', conta.pessoa, cenario.x, alvo=cenario.x)
    textos = [' '.join(linha) for linha in _linhas(cliente_logado.get(CAMINHO))]
    assert any('Empresa X' in texto for texto in textos)
    assert not any('Empresa Y' in texto for texto in textos)  # A1: o filtro de escopo é do código, não do banco


# --- caminho infeliz ---


def test_deslogado_vai_para_a_entrada():
    resposta = Client().get(CAMINHO)
    assert resposta.status_code == 302
    assert resposta['Location'].startswith('/entrar')


def test_sem_a_acao_da_404_por_url_direta(cliente_logado, conta, cenario, conceder_direto):
    for base in ('curador', 'tecnico', 'usuario'):
        concessao = conceder_direto(conta.pessoa, cenario.cargos_x[base], cenario.x)
        assert (base, cliente_logado.get(CAMINHO).status_code) == (base, 404)
        concessao.delete()
    concessao = conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.f1)
    assert ('admin de fazenda', cliente_logado.get(CAMINHO).status_code) == ('admin de fazenda', 404)
    concessao.delete()


def test_cargo_personalizado_com_todas_as_acoes_delegaveis_da_404(cliente_logado, conta, cenario, conceder_direto):
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Quase Tudo', base='tecnico')
    CargoPermissao.objects.bulk_create(CargoPermissao(cargo=cargo, permissao=p) for p in Permissao.objects.filter(delegavel=True))
    conceder_direto(conta.pessoa, cargo, cenario.x)
    assert cliente_logado.get(CAMINHO).status_code == 404


def test_negado_com_filtro_ruim_da_404_e_nao_grava(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.x)
    antes = _consultadas()
    resposta = cliente_logado.get(CAMINHO, {'desde': 'nao-e-data', 'acao': 'xyz', 'depois': 'abc'})
    assert resposta.status_code == 404
    assert _consultadas() == antes


@pytest.mark.parametrize('consulta', [
    {'desde': '2026-13-45'},
    {'ate': 'lixo'},
    {'acao': 'nao_existe'},
    {'acao': '<script>alert(1)</script>'},
    {'depois': 'abc'},
    {'depois': '-1'},
    {'pessoa_id': 'abc'},
    {'alvo_pessoa_id': '-3'},
    {'empresa_id': '0'},
])
def test_filtro_invalido_mostra_aviso_sem_500_e_sem_gravar(cliente_logado, plataforma_logada, consulta):
    antes = _consultadas()
    resposta = cliente_logado.get(CAMINHO, consulta)
    assert resposta.status_code == 200
    assert MENSAGEM_DO_FILTRO in resposta.content.decode()
    assert _consultadas() == antes


def test_datas_extremas_nao_derrubam_a_pagina(cliente_logado, plataforma_logada):
    resposta = cliente_logado.get(CAMINHO, {'desde': '0001-01-01', 'ate': '9999-12-31'})
    assert resposta.status_code == 200
    assert MENSAGEM_DO_FILTRO not in resposta.content.decode()


def test_cpf_nunca_aparece_na_tela(cliente_logado, plataforma_logada, cenario):
    _evento('cargo_alterado', plataforma_logada.pessoa, cenario.x, alvo=cenario.x,
            detalhes={'nome': 'Cargo Sintetico', 'permissoes': [], 'cpf': plataforma_logada.cpf})
    html = cliente_logado.get(CAMINHO).content.decode()
    assert 'Cargo Sintetico' in html
    assert plataforma_logada.cpf not in html  # A4: nem o da pessoa de quem agiu, nem o que estiver no detalhe


def test_nome_hostil_e_escapado_na_tela(cliente_logado, plataforma_logada, cenario, fabrica_pessoa):
    hostil = fabrica_pessoa('<b>x</b>')
    _evento('pessoa_criada', hostil, cenario.x, alvo=hostil)
    html = cliente_logado.get(CAMINHO).content.decode()
    assert '&lt;b&gt;x&lt;/b&gt;' in html
    assert '<b>x</b>' not in html


# --- filtros de pessoa, de empresa e escopo dos selects (005 R2, R3, R6) ---


def test_filtro_por_quem_agiu_mostra_so_os_eventos_dela(cliente_logado, plataforma_logada, cenario, fabrica_pessoa):
    ana = fabrica_pessoa('Ana Sintetica')
    beto = fabrica_pessoa('Beto Sintetico')
    _evento('empresa_criada', ana, cenario.x, alvo=cenario.x)
    _evento('fazenda_criada', beto, cenario.x, alvo=cenario.f1)
    linhas = _linhas(cliente_logado.get(CAMINHO, {'pessoa_id': ana.pk}))
    assert [linha[2] for linha in linhas] == ['Ana Sintetica']


def test_filtro_por_pessoa_afetada_mostra_o_evento_em_que_ela_e_alvo(cliente_logado, plataforma_logada, cenario, fabrica_pessoa):
    ana = fabrica_pessoa('Ana Sintetica')
    beto = fabrica_pessoa('Beto Sintetico')
    _evento('pessoa_criada', beto, cenario.x, alvo=ana)
    _evento('fazenda_criada', beto, cenario.x, alvo=cenario.f1)
    linhas = _linhas(cliente_logado.get(CAMINHO, {'alvo_pessoa_id': ana.pk}))
    assert [linha[3] for linha in linhas] == ['Ana Sintetica']


def test_filtro_por_empresa_do_escopo_limita_os_eventos(cliente_logado, plataforma_logada, cenario):
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f1)
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.y, alvo=cenario.fy)
    linhas = _linhas(cliente_logado.get(CAMINHO, {'empresa_id': cenario.y.pk}))
    assert [linha[3] for linha in linhas] == ['Fazenda: FY']


def test_select_de_pessoas_nao_lista_quem_e_so_de_outra_empresa(cliente_logado, conta, cenario, conceder_direto, fabrica_pessoa):
    _admin_de_x(cliente_logado, conta, cenario, conceder_direto)
    minha = fabrica_pessoa('Minha Sintetica')
    conceder_direto(minha, cenario.cargos_x['tecnico'], cenario.x)
    _evento('fazenda_criada', minha, cenario.x, alvo=cenario.f1)  # o select vem da atividade que quem olha vê
    alheia = fabrica_pessoa('Alheia Sintetica')
    conceder_direto(alheia, cenario.cargos_y['administrador'], cenario.y)
    _evento('fazenda_criada', alheia, cenario.y, alvo=cenario.fy)
    resposta = cliente_logado.get(CAMINHO)
    opcoes = dict(_pessoas_nos_selects(resposta))
    assert opcoes.get(str(minha.pk)) == 'Minha Sintetica'
    assert str(alheia.pk) not in opcoes
    assert 'Alheia Sintetica' not in resposta.content.decode()


def test_campo_de_empresa_so_aparece_com_mais_de_uma_empresa(cliente_logado, conta, cenario, conceder_direto):
    _admin_de_x(cliente_logado, conta, cenario, conceder_direto)
    assert 'name="empresa_id"' not in cliente_logado.get(CAMINHO).content.decode()
    conceder_direto(conta.pessoa, cenario.cargos_y['administrador'], cenario.y)
    assert 'name="empresa_id"' in cliente_logado.get(CAMINHO).content.decode()


def test_empresa_so_com_fazenda_concedida_nao_entra_no_filtro(cliente_logado, conta, cenario, conceder_direto):
    # Só `ver_auditoria` conta: quem tem fazenda em Y, mas não a ação na empresa, não ganha a empresa no filtro.
    _admin_de_x(cliente_logado, conta, cenario, conceder_direto)
    conceder_direto(conta.pessoa, cenario.cargos_y['tecnico'], cenario.fy)
    assert 'name="empresa_id"' not in cliente_logado.get(CAMINHO).content.decode()


def test_plataforma_ve_o_filtro_de_empresa_com_todas_as_empresas(plataforma_logada, cliente_logado, cenario):
    html = cliente_logado.get(CAMINHO).content.decode()
    assert 'name="empresa_id"' in html
    assert 'Empresa X' in html
    assert 'Empresa Y' in html


def test_id_de_pessoa_alheia_por_url_nao_vaza_evento_nem_nome(cliente_logado, conta, cenario, conceder_direto, fabrica_pessoa):
    _admin_de_x(cliente_logado, conta, cenario, conceder_direto)
    alheia = fabrica_pessoa('Alheia Sintetica')
    conceder_direto(alheia, cenario.cargos_y['tecnico'], cenario.y)
    _evento('fazenda_criada', alheia, cenario.y, alvo=cenario.fy)
    resposta = cliente_logado.get(CAMINHO, {'pessoa_id': alheia.pk, 'alvo_pessoa_id': alheia.pk})
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert _linhas(resposta) == []
    assert SEM_EVENTOS in html
    assert 'Alheia Sintetica' not in html
    assert 'Fazenda: FY' not in html
    assert 'Empresa Y' not in html


def test_id_de_empresa_alheia_por_url_da_404_e_nao_grava(cliente_logado, conta, cenario, conceder_direto):
    _admin_de_x(cliente_logado, conta, cenario, conceder_direto)
    antes = _consultadas()
    assert cliente_logado.get(CAMINHO, {'empresa_id': cenario.y.pk}).status_code == 404
    assert _consultadas() == antes


def test_id_da_propria_empresa_passa_e_grava_a_consulta(cliente_logado, conta, cenario, conceder_direto):
    _admin_de_x(cliente_logado, conta, cenario, conceder_direto)
    antes = _consultadas()
    assert cliente_logado.get(CAMINHO, {'empresa_id': cenario.x.pk}).status_code == 200
    assert _consultadas() == antes + 1


def test_paginacao_preserva_os_filtros_de_pessoa_e_empresa(cliente_logado, plataforma_logada, cenario, fabrica_pessoa):
    ana = fabrica_pessoa('Ana Sintetica')
    for _ in range(31):
        _evento('fazenda_criada', ana, cenario.x, alvo=cenario.f1)
    primeira = cliente_logado.get(CAMINHO, {'pessoa_id': ana.pk, 'empresa_id': cenario.x.pk})
    link = re.search(r'<nav class="paginacao".*?href="([^"]+)"', primeira.content.decode(), re.S)
    assert link is not None
    href = unescape(link.group(1))
    assert f'pessoa_id={ana.pk}' in href
    assert f'empresa_id={cenario.x.pk}' in href
    segunda = cliente_logado.get(CAMINHO + href)
    assert len(_linhas(segunda)) == 1


# --- janela de 90 dias, paginação na borda e origem da requisição (005 R2, R7; A7) ---


class _Relogio:
    """Relógio de teste no lugar de `django.utils.timezone` num módulo só: `now` devolve o instante dado, o resto é o do Django."""

    def __init__(self, agora):
        self._agora = agora

    def now(self):
        return self._agora

    def __getattr__(self, nome):
        return getattr(timezone, nome)


def _ultima_consulta():
    return EventoAuditoria.objects.filter(acao='auditoria_consultada').latest('pk')


def _pessoas_nos_selects(resposta):
    """(valor, rótulo) de cada opção com id de pessoa nos selects "Quem agiu" e "Pessoa afetada"."""
    return re.findall(r'<option value="(\d+)"[^>]*>([^<]*)</option>', resposta.content.decode())


def test_so_ate_antigo_devolve_eventos_de_mais_de_90_dias(cliente_logado, plataforma_logada, cenario):
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f1, quando=timezone.now() - timedelta(days=200))
    ate = (timezone.now() - timedelta(days=30)).date().isoformat()
    assert [linha[3] for linha in _linhas(cliente_logado.get(CAMINHO, {'ate': ate}))] == ['Fazenda: F1']


def test_sem_datas_a_lista_segue_nos_ultimos_90_dias(cliente_logado, plataforma_logada, cenario):
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f1, quando=timezone.now() - timedelta(days=200))
    assert SEM_EVENTOS in cliente_logado.get(CAMINHO).content.decode()


def test_evento_na_borda_nao_some_entre_as_paginas(cliente_logado, plataforma_logada, cenario, monkeypatch):
    """Sem a janela fixada no link, a página 2 recalcularia a partir de agora e perderia o evento que caiu na borda."""
    agora = timezone.now()
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f1, quando=agora - timedelta(days=90) + timedelta(hours=1))
    for _ in range(30):
        _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f2)
    primeira = cliente_logado.get(CAMINHO, {'acao': 'fazenda_criada'})
    link = re.search(r'<nav class="paginacao".*?href="([^"]+)"', primeira.content.decode(), re.S)
    assert link is not None
    href = unescape(link.group(1))
    assert 'desde=' in href
    # Só o relógio da auditoria anda 2 h: trocar o `timezone` global derrubaria a sessão (302 para /entrar, medido).
    relogio = _Relogio(agora + timedelta(hours=2))
    monkeypatch.setattr(auditoria_leitura, 'timezone', relogio)
    monkeypatch.setattr(auditoria_paginas, 'timezone', relogio)
    segunda = cliente_logado.get(CAMINHO + href)
    assert (segunda.status_code, segunda.get('Location')) == (200, None)
    assert [linha[3] for linha in _linhas(segunda)] == ['Fazenda: F1']


def test_mais_antigos_nao_traz_o_que_ja_estava_fora_da_janela(cliente_logado, plataforma_logada, cenario):
    """Greptile P2 (PR #63): a página seguinte começa no mesmo ponto da primeira; o que já estava fora do corte não reaparece."""
    inicio = auditoria_leitura.inicio_do_dia(auditoria_leitura.data_da_janela_padrao(timezone.now()))
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f1, quando=inicio - timedelta(minutes=1))
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f2, quando=inicio + timedelta(minutes=1))
    for _ in range(30):
        _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f1)
    primeira = cliente_logado.get(CAMINHO, {'acao': 'fazenda_criada'})
    link = re.search(r'<nav class="paginacao".*?href="([^"]+)"', primeira.content.decode(), re.S)
    assert link is not None
    segunda = cliente_logado.get(CAMINHO + unescape(link.group(1)))
    assert [linha[3] for linha in _linhas(segunda)] == ['Fazenda: F2']  # o de antes do corte (F1, -1 min) fica de fora


def test_get_de_outro_site_ignora_o_filtro_e_grava_consulta_sem_filtros(cliente_logado, plataforma_logada, cenario):
    _evento('empresa_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.x)
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f1)
    resposta = cliente_logado.get(CAMINHO, {'acao': 'fazenda_criada'}, headers={'Sec-Fetch-Site': 'cross-site'})
    assert resposta.status_code == 200
    assert {linha[1] for linha in _linhas(resposta)} == {'Empresa criada', 'Fazenda criada'}
    assert _ultima_consulta().detalhes == {}


def test_get_do_mesmo_site_ou_sem_cabecalho_grava_os_filtros(cliente_logado, plataforma_logada, cenario):
    _evento('empresa_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.x)
    _evento('fazenda_criada', plataforma_logada.pessoa, cenario.x, alvo=cenario.f1)
    for cabecalho in ({'Sec-Fetch-Site': 'same-origin'}, {}):
        linhas = _linhas(cliente_logado.get(CAMINHO, {'acao': 'fazenda_criada'}, headers=cabecalho))
        assert [linha[1] for linha in linhas] == ['Fazenda criada']
        assert _ultima_consulta().detalhes == {'acao': 'fazenda_criada'}


def test_resposta_declara_que_depende_do_site_de_origem(cliente_logado, plataforma_logada):
    assert 'Sec-Fetch-Site' in cliente_logado.get(CAMINHO)['Vary']


def test_select_traz_ex_colaborador_com_historico_mesmo_sem_concessao(cliente_logado, conta, cenario, conceder_direto, cpf_novo):
    _admin_de_x(cliente_logado, conta, cenario, conceder_direto)
    cpf = cpf_novo()
    ex = Pessoa.objects.criar(nome='Ex Colaboradora Sintetica', email='ex@exemplo.test', cpf=cpf)  # sem concessão: só o evento a torna escolhível
    _evento('fazenda_criada', ex, cenario.x, alvo=cenario.f1)
    resposta = cliente_logado.get(CAMINHO)
    assert (str(ex.pk), 'Ex Colaboradora Sintetica') in _pessoas_nos_selects(resposta)
    assert cpf not in resposta.content.decode()


def test_select_nao_traz_quem_so_esta_no_diretorio(cliente_logado, conta, cenario, conceder_direto, fabrica_pessoa):
    _admin_de_x(cliente_logado, conta, cenario, conceder_direto)
    so_diretorio = fabrica_pessoa('Diretorio Sintetico')
    conceder_direto(so_diretorio, cenario.cargos_x['tecnico'], cenario.x)
    assert 'Diretorio Sintetico' not in cliente_logado.get(CAMINHO).content.decode()


def test_homonimos_no_select_ganham_origem_so_quando_quem_olha_a_ve(cliente_logado, conta, cenario, conceder_direto, fabrica_pessoa):
    _admin_de_x(cliente_logado, conta, cenario, conceder_direto)
    de_x = fabrica_pessoa('Ana Sintetica', empresa_origem=cenario.x)
    de_y = fabrica_pessoa('Ana Sintetica', empresa_origem=cenario.y)
    _evento('fazenda_criada', de_x, cenario.x, alvo=cenario.f1)
    _evento('fazenda_criada', de_y, cenario.x, alvo=cenario.f2)
    opcoes = dict(_pessoas_nos_selects(cliente_logado.get(CAMINHO)))
    assert opcoes[str(de_x.pk)] == 'Ana Sintetica (Empresa X)'
    assert opcoes[str(de_y.pk)] == f'Ana Sintetica (#{de_y.pk})'  # a empresa Y não é visível a quem olha


def test_id_alheio_forjado_no_filtro_nao_vira_opcao_do_select(cliente_logado, conta, cenario, conceder_direto, fabrica_pessoa):
    """O filtro grava `detalhes.pessoa_id` no `auditoria_consultada`; esse registro não pode tornar a pessoa escolhível."""
    _admin_de_x(cliente_logado, conta, cenario, conceder_direto)
    alheia = fabrica_pessoa('Alheia Forjada')
    _evento('fazenda_criada', alheia, cenario.y, alvo=cenario.fy)
    assert cliente_logado.get(CAMINHO, {'pessoa_id': alheia.pk}).status_code == 200
    assert cliente_logado.get(CAMINHO, {'alvo_pessoa_id': alheia.pk}).status_code == 200
    resposta = cliente_logado.get(CAMINHO)
    assert str(alheia.pk) not in dict(_pessoas_nos_selects(resposta))
    assert 'Alheia Forjada' not in resposta.content.decode()
