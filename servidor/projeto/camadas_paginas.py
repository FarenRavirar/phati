"""Telas de camadas do Administrador (008 T4.1; R12, R18, R21): envio, prévia e publicação, na casca da 003.

Nenhuma regra de domínio aqui. As telas montam o molde e entregam a `camadas.js` as URLs da API do catálogo
(`catalogo/api.py`), que decide envio, prévia e publicação com a mesma regra das rotas. A checagem de acesso da página é
uma só, `_fazenda_que_publica`: sem `publicar_camada` na fazenda da URL (inclusive em fazenda arquivada, que a regra nega),
404, igual ao de fazenda inexistente, por URL direta inclusive (A5).

A geometria sobre o mapa-base (R12) entra só com `mapa_ativo()`, pelo endpoint `catalogo_geometria`. A troca de nó por
feição (R7) não tem endpoint: a prévia mostra o resumo, os avisos, as colunas e a contagem de nós sugeridos; a publicação usa
a sugestão ou a divisão por coluna.
"""

from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from catalogo.models import Camada, EnvioCamada, Estudo
from permissao.pode import com_permissao
from projeto.mapa import com_politica_do_mapa, mapa_ativo
from projeto.paginas_autenticadas import campo, exige_acao, exige_entrada, exigir, renderizar_na_casca
from territorio.models import Fazenda

ACAO = 'publicar_camada'
# Id do envio no molde das URLs: `camadas.js` troca pelo id real. Igual ao de `camadas.js` (ENVIO_MODELO).
ENVIO_MODELO = '00000000-0000-0000-0000-000000000000'


def _fazenda_que_publica(requisicao, empresa_id, fazenda_id):
    """Única checagem de acesso das telas: fazenda da URL, na empresa da URL, em que a pessoa pode `publicar_camada`. A regra
    é a de `exigir` (a mesma `pode` das rotas); inexistente, de outra empresa e sem permissão dão o mesmo 404 (R11)."""
    fazenda = Fazenda.objects.filter(pk=fazenda_id, empresa_id=empresa_id).first()
    if fazenda is None:
        raise Http404
    exigir(requisicao, ACAO, fazenda, nao_encontrado=True)
    return fazenda


def _envio_da_fazenda(fazenda, envio_id):
    """Envio da fazenda da URL. Envio de outra fazenda ou inexistente: 404, o mesmo da permissão negada."""
    envio = EnvioCamada.objects.filter(publico_id=envio_id, fazenda=fazenda).first()
    if envio is None:
        raise Http404
    return envio


def _urls(empresa_id, fazenda_id, envio_id=ENVIO_MODELO):
    """Links das telas e endpoints da API, por `reverse`: nenhuma URL escrita à mão."""
    return {
        'api_criar': reverse('api_v1:catalogo_criar_envio', kwargs={'fazenda_id': fazenda_id}),
        'api_previa': reverse('api_v1:catalogo_previa', kwargs={'envio_id': envio_id}),
        'api_publicar': reverse('api_v1:catalogo_publicar', kwargs={'envio_id': envio_id}),
        'geometria': reverse('api_v1:catalogo_geometria', kwargs={'envio_id': envio_id}),
        'novo': reverse('camadas_novo', kwargs={'empresa_id': empresa_id, 'fazenda_id': fazenda_id}),
        'previa': reverse('camadas_previa', kwargs={'empresa_id': empresa_id, 'fazenda_id': fazenda_id, 'envio_id': envio_id}),
        'confirmacao': reverse('camadas_confirmacao', kwargs={'empresa_id': empresa_id, 'fazenda_id': fazenda_id, 'envio_id': envio_id}),
    }


def _pagina(requisicao, modelo, fazenda, contexto):
    # envio, prévia e publicação levam a etapa "Enviar camada" na trilha (telas.md §0)
    return renderizar_na_casca(requisicao, modelo, contexto, empresa=fazenda.empresa, fazenda=fazenda, etapa='Enviar camada')


@require_GET
@exige_entrada
@exige_acao(ACAO)
def envio(requisicao, empresa_id, fazenda_id):
    """Passo 1: escolher o arquivo. `camadas.js` envia à API e segue para a prévia com o id do envio."""
    with com_permissao(requisicao.user, ACAO):
        fazenda = _fazenda_que_publica(requisicao, empresa_id, fazenda_id)
        return _pagina(requisicao, 'camadas_envio.html', fazenda, {'urls': _urls(empresa_id, fazenda.pk)})


@require_GET
@exige_entrada
@exige_acao(ACAO)
def previa(requisicao, empresa_id, fazenda_id, envio_id):
    """Passo 2: a prévia vem da API (`catalogo_previa`). Envio vencido vira aviso, sem formulário de publicação.
    Vencimento: a mesma regra de `publicacao.publicar_envio` (`expira_em <= agora`)."""
    with com_permissao(requisicao.user, ACAO):
        fazenda = _fazenda_que_publica(requisicao, empresa_id, fazenda_id)
        envio = _envio_da_fazenda(fazenda, envio_id)
        contexto = {'urls': _urls(empresa_id, fazenda.pk, envio.publico_id), 'vencido': envio.expira_em <= timezone.now(),
                    'mapa': mapa_ativo()}
        # A política do mapa (R3) só vai à prévia, e só com a flag ligada (`com_politica_do_mapa` confere a flag).
        return com_politica_do_mapa(_pagina(requisicao, 'camadas_previa.html', fazenda, contexto))


@require_GET
@exige_entrada
@exige_acao(ACAO)
def confirmacao(requisicao, empresa_id, fazenda_id, envio_id):
    """Passo 3: estudo, camada, metadados obrigatórios (R8), colunas a ocultar (R9) e divisão por coluna (D119). Quem publica
    é `catalogo_publicar`, com a permissão e os nós refeitos sob trava (R13)."""
    with com_permissao(requisicao.user, ACAO):
        fazenda = _fazenda_que_publica(requisicao, empresa_id, fazenda_id)
        envio = _envio_da_fazenda(fazenda, envio_id)
        estudos = list(Estudo.objects.filter(fazenda=fazenda).order_by('nome', 'pk'))
        camadas = Camada.objects.filter(fazenda=fazenda).order_by('nome', 'pk')
        campos = [
            campo('estudo_id', 'Estudo', tipo='select', obrigatorio=True,
                  opcoes=[{'valor': e.pk, 'rotulo': e.nome} for e in estudos]),
            campo('camada_id', 'Camada', tipo='select',
                  opcoes=[{'valor': '', 'rotulo': 'Nova camada'}, *({'valor': str(c.publico_id), 'rotulo': c.nome} for c in camadas)]),
            campo('nome', 'Nome da camada', obrigatorio=True),
            campo('tema', 'Tema', obrigatorio=True),
            campo('origem', 'Origem', obrigatorio=True),
            # As colunas do arquivo entram depois, por `camadas.js`, da prévia; aqui só a opção "sem divisão".
            campo('coluna_no', 'Divisão da fazenda por coluna', tipo='select', opcoes=[{'valor': '', 'rotulo': 'Sem divisão por coluna'}]),
        ]
        contexto = {'urls': _urls(empresa_id, fazenda.pk, envio.publico_id), 'vencido': envio.expira_em <= timezone.now(),
                    'sem_estudo': not estudos, 'campos': campos}
        return _pagina(requisicao, 'camadas_confirmacao.html', fazenda, contexto)
