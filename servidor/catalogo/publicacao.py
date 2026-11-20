"""Publicação de um envio em análise (008 T3.1, T3.1b; R4, R7, R9, R12, R13, R14, R15; D119).

`publicar_envio` roda numa transação só (`com_permissao`). Ordem: envio travado, permissão e expiração (depois da trava),
estudo travado, original relido com hash, ingestão de novo, metadados, sistema de referência, nós (travados), divisão,
camada e versão, atributos, feições, auditoria e, por último, a linha do envio sai. O original não é apagado: vira
`caminho_original` da versão (R15).

Trava (R13): `select_for_update` no envio (publicar o mesmo envio duas vezes; e a limpeza de vencidos pula o envio travado),
no estudo (dois envios da mesma camada, ou a criação de camada nova com o mesmo nome, não calculam o mesmo número) e nos
nós escolhidos ou lidos (arquivamento concorrente não passa). Ordem fixa: envio, estudo, nós por pk, para não haver impasse.
Doc: Django 6.1, `QuerySet.select_for_update()`; PostgreSQL 18, "Explicit Locking" (linha travada até o COMMIT).
Uma divisão por fazenda é garantida pelo índice único parcial (`camada_divisao_unica_por_fazenda`), que cobre a corrida
entre estudos diferentes da mesma fazenda que a trava do estudo não serializa.

Divisão (D119): a camada marcada com `coluna_no` é a divisão da fazenda; cada feição dela liga-se ao nó pelo nome da
coluna (`SubArea.nome`). A sugestão de nó de outras publicações usa a versão mais recente da divisão.
"""

import json
import tempfile
from collections import defaultdict
from pathlib import Path

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from catalogo import original
from catalogo.envios import ACAO
from catalogo.ingestao import ingerir_envio
from catalogo.metadados import atributos_da_previa, montar_previa
from catalogo.models import ESTADO_EM_ANALISE, AtributoVersao, Camada, EnvioCamada, Estudo, Feicao, VersaoCamada
from catalogo.no_sugerido import SugestaoNo, contornos_da_divisao, nos_da_fazenda, sugerir_no
from comum.auditoria import auditar
from projeto.ficha import CAMPOS, SEM_INFORMACAO
from permissao.pode import com_permissao, escopo_arquivado, esquecer, pode
from territorio.models import SubArea


class EnvioNaoEncontrado(Exception):
    """Inexistente, de outra empresa ou fazenda, ou sem `publicar_camada` ali: a mesma resposta (R11)."""


class RecusaPublicacao(Exception):
    """Recusa de regra da publicação. `erros` tem uma linha por problema, para a tela."""

    def __init__(self, erros):
        super().__init__('; '.join(erros))
        self.erros = list(erros)


def _envio_da_confirmacao(pessoa, envio_id):
    """Envio travado e visível a `pessoa`. Inexistente e sem permissão viram a mesma exceção (R11).

    A permissão é relida depois da trava: `com_permissao` já carregou a memória de permissão antes da espera, e uma
    revogação enquanto a publicação esperava não pode passar (CodeRabbit, PR #69)."""
    envio = EnvioCamada.objects.select_for_update().filter(pk=envio_id).first()
    esquecer(pessoa)
    if envio is None or not pode(pessoa, ACAO, envio.fazenda):
        raise EnvioNaoEncontrado()
    return envio


def _estudo_da_fazenda(envio, estudo_id):
    """Estudo existente e travado, da mesma fazenda do envio. Tema e estudo não são criados aqui (D119)."""
    estudo = Estudo.objects.select_for_update().filter(pk=estudo_id, fazenda_id=envio.fazenda_id).first()
    if estudo is None:
        raise RecusaPublicacao(['estudo não encontrado nesta fazenda'])
    return estudo


def _original_conferido(envio):
    try:
        return original.ler(envio.arquivo_temporario, envio.hash_original)
    except original.OriginalInvalido:
        raise RecusaPublicacao(['original não confere com o hash guardado no envio']) from None


def _ingerir_original(envio):
    """Prévia do original guardado: relê com hash e ingere de novo (a ingestão não guarda estado)."""
    dados = _original_conferido(envio)
    with tempfile.TemporaryDirectory() as pasta:
        copia = Path(pasta) / 'envio.bin'
        copia.write_bytes(dados)
        return ingerir_envio(copia)


def _nos_escolhidos(envio, nos, feicoes):
    """Nó de cada feição (R7). `None` é a própria fazenda: vale com ou sem nós na fazenda, e a publicação não exige escolha
    (decisão do mantenedor). Nó escolhido precisa ser ativo e da fazenda; lista com tamanho errado é recusada.

    Os nós escolhidos são travados (ordem por pk) e revalidados aqui: arquivamento concorrente espera a publicação (R13)."""
    if len(nos) != len(feicoes):
        raise RecusaPublicacao(['escolha de nó não confere com a quantidade de feições'])
    ativos = set(nos_da_fazenda(envio.fazenda))
    escolhidos = set(nos) - {None}
    if not ativos:
        if escolhidos:
            raise RecusaPublicacao(['a fazenda não tem nós, mas uma feição recebeu nó'])
        return
    if not escolhidos <= ativos:
        raise RecusaPublicacao(['nó inexistente, arquivado ou de outra fazenda'])
    for no in SubArea.objects.select_for_update().filter(pk__in=escolhidos).order_by('pk'):
        if escopo_arquivado(no):
            raise RecusaPublicacao(['nó arquivado, ou com ancestral arquivado'])


def _nos_pelo_nome(envio, coluna, atributos, feicoes):
    """Nó de cada feição pelo nome na coluna da divisão (D119). Recusa coluna ausente, nome repetido na fazenda, nome sem
    correspondente ou valor vazio. A mensagem não repete o valor do arquivo (texto hostil, R21)."""
    if coluna not in atributos:
        raise RecusaPublicacao(['coluna do nó não existe no arquivo'])
    por_nome = defaultdict(list)
    nos_ativos = SubArea.objects.select_for_update().filter(
        fazenda_id=envio.fazenda_id, arquivada_em__isnull=True).order_by('pk').values_list('id', 'nome')
    for id_no, nome in nos_ativos:
        por_nome[nome].append(id_no)
    if any(len(ids) > 1 for ids in por_nome.values()):
        raise RecusaPublicacao(['nome de nó repetido na fazenda: a divisão não pode ser marcada'])
    ids = []
    for indice, feicao in enumerate(feicoes, start=1):
        valor = feicao.valores.get(coluna)
        candidatos = por_nome.get(valor.strip()) if isinstance(valor, str) else None
        if not candidatos:
            raise RecusaPublicacao([f'feição {indice}: nome do nó sem correspondente na fazenda'])
        ids.append(candidatos[0])
    return ids


def _alinhar_divisao(camada, coluna):
    """Marca a camada como divisão da fazenda, ou confere a marca que ela já tem (D119). Uma divisão por fazenda.

    Corrida: duas publicações de estudos diferentes da mesma fazenda podem passar pelo `exists()` antes de qualquer uma
    gravar. Quem grava por último bate no índice único parcial (Django: `UniqueConstraint(condition=...)` vira
    `CREATE UNIQUE INDEX`; PostgreSQL: índice parcial). O `IntegrityError` vira recusa, num ponto de salvamento."""
    if camada.coluna_no is None:
        if coluna is None:
            return
        if Camada.objects.filter(fazenda_id=camada.fazenda_id, coluna_no__isnull=False).exists():
            raise RecusaPublicacao(['já existe divisão desta fazenda'])
        camada.coluna_no = coluna
        try:
            with transaction.atomic():
                camada.save(update_fields=['coluna_no'])
        except IntegrityError:
            raise RecusaPublicacao(['já existe divisão desta fazenda']) from None
        return
    if coluna != camada.coluna_no:
        raise RecusaPublicacao(['camada é a divisão da fazenda: publique com a coluna do nó marcada'])


def _sugestoes(envio, feicoes, contornos):
    """Sugestão completa de cada feição (motivo e área por nó), recalculada aqui e não confiada ao cliente (R7).
    Sem divisão, toda feição fica sem sugestão."""
    if not contornos:
        return [SugestaoNo(None, 'sem_divisao', {}) for _ in feicoes]
    ativos = set(nos_da_fazenda(envio.fazenda))
    nos = [(id_no, geometria) for id_no, geometria in contornos.items() if id_no in ativos]
    return [sugerir_no(feicao.geometria, nos) for feicao in feicoes]


def _sugeridos(envio, feicoes, contornos):
    """Nó sugerido (id) de cada feição: a parte da publicação que não precisa do motivo."""
    return [sugestao.sub_area_id for sugestao in _sugestoes(envio, feicoes, contornos)]


def _proximo_numero(camada):
    """Número seguinte da camada. Chamado só com o estudo travado: sem a trava, dois envios pegam o mesmo máximo."""
    maximo = VersaoCamada.objects.filter(camada=camada).aggregate(maximo=Max('numero'))['maximo']
    return (maximo or 0) + 1


def _camada_da_publicacao(estudo, camada_id, nome):
    if camada_id is None:
        if Camada.objects.filter(estudo=estudo, nome=nome).exists():
            raise RecusaPublicacao(['já existe camada com este nome neste estudo'])
        return Camada.objects.create(estudo=estudo, empresa_id=estudo.empresa_id, fazenda_id=estudo.fazenda_id, nome=nome)
    camada = Camada.objects.filter(pk=camada_id, estudo=estudo).first()
    if camada is None:
        raise RecusaPublicacao(['camada não encontrada neste estudo'])
    if camada.nome != nome:
        raise RecusaPublicacao(['nome do arquivo diferente do nome da camada'])
    return camada


def _conferir_previa(estudo, previa, completa, ocultos, sistema_confirmado):
    """Regras da prévia contra o estudo e a entrada. Devolve os nomes de atributo do arquivo."""
    if completa.metadados.obrigatorios['tema'] != estudo.tema.nome:
        raise RecusaPublicacao(['tema do arquivo diferente do tema do estudo'])
    if previa.transformacao != 'nenhuma' and not sistema_confirmado:
        raise RecusaPublicacao([f'sistema de referência {previa.sistema} exige confirmação antes de publicar'])
    atributos = {a.nome for a in completa.atributos}
    if set(ocultos) - atributos:
        raise RecusaPublicacao(['atributo a ocultar não existe no arquivo'])
    return atributos


def _nos_da_publicacao(envio, previa, atributos, nos, coluna_no):
    """Nó de cada feição: pelo nome na coluna da divisão (D119), ou o escolhido pelo Administrador (R7)."""
    if coluna_no is None:
        _nos_escolhidos(envio, nos, previa.feicoes)
        return nos
    if previa.tipo != 'poligono':  # contorno de área (D119): divisão de ponto ou linha não tem onde ser sugerida
        raise RecusaPublicacao([f'a divisão da fazenda precisa de polígonos, não de {previa.tipo}'])
    nos_da_coluna = _nos_pelo_nome(envio, coluna_no, atributos, previa.feicoes)
    if nos and list(nos) != nos_da_coluna:
        raise RecusaPublicacao(['nó escolhido diverge do nome na coluna marcada'])
    return nos_da_coluna


def _gravar_versao(pessoa, envio, camada, previa, completa, ocultos, nos):
    """Versão "em análise" com atributos e feições. Chamado com o estudo travado (o número depende disso)."""
    m = completa.metadados
    numero = _proximo_numero(camada)
    versao = VersaoCamada.objects.create(
        camada=camada, empresa_id=envio.empresa_id, fazenda_id=envio.fazenda_id, numero=numero,
        estado=ESTADO_EM_ANALISE, sistema_original=f'{previa.sistema}; {previa.origem_sistema}',
        origem=m.obrigatorios['origem'], hash_original=envio.hash_original,
        caminho_original=envio.arquivo_temporario, enviada_por=pessoa, **m.opcionais,
    )
    AtributoVersao.objects.bulk_create([
        AtributoVersao(versao=versao, empresa_id=envio.empresa_id, fazenda_id=envio.fazenda_id,
                       nome=a.nome, visivel=a.nome not in ocultos)
        for a in completa.atributos
    ])
    Feicao.objects.bulk_create([
        Feicao(versao=versao, empresa_id=envio.empresa_id, fazenda_id=envio.fazenda_id,
               geometria=f.geometria, valores=f.valores, sub_area_id=no)
        for f, no in zip(previa.feicoes, nos)
    ])
    return versao


def _auditar(pessoa, envio, versao, camada, previa, ocultos, nos, sugeridos):
    numero = versao.numero
    auditar('camada_publicada', pessoa, versao, envio.empresa_id, {'nome_camada': camada.nome, 'versao': numero})
    if previa.transformacao != 'nenhuma':
        auditar('sistema_confirmado', pessoa, versao, envio.empresa_id,
                {'camada': camada.pk, 'versao': numero, 'sistema': previa.sistema})
    for nome in sorted(set(ocultos)):
        auditar('atributo_ocultado', pessoa, versao, envio.empresa_id,
                {'nome_atributo': nome, 'versao': numero, 'camada': camada.pk})
    trocados = sum(1 for escolhido, sugerido in zip(nos, sugeridos) if sugerido is not None and escolhido != sugerido)
    if trocados:  # R14 pede o evento de troca de nó, não um por feição: uma linha por publicação, com a contagem
        auditar('no_trocado', pessoa, versao, envio.empresa_id, {'camada': camada.pk, 'versao': numero, 'quantidade': trocados})


def publicar_envio(pessoa, envio_id, *, estudo_id, metadados, camada_id=None, ocultos=(), nos=(), coluna_no=None,
                   sistema_confirmado=False, agora=None):
    """Publica o envio como versão "em análise" (R2). Qualquer recusa ou falha deixa o banco como estava (R13).

    `nos`: um id de nó (ou None) por feição, na ordem da prévia (sem `coluna_no`). `coluna_no`: marca a camada como divisão
    da fazenda e liga cada feição ao nó pelo nome dessa coluna; `nos`, se vier, tem de bater com o que o nome dá.
    `ocultos`: nomes de coluna a ocultar (R9). `sistema_confirmado`: obrigatório fora de SIRGAS 2000 (R4).
    Sugestão de nó: pelos contornos da divisão marcada da fazenda (D119); sem divisão, não há sugestão.
    `agora` (opcional) é tomado depois da trava: a espera pela trava conta para a expiração (R12).
    """
    with com_permissao(pessoa, ACAO):
        envio = _envio_da_confirmacao(pessoa, envio_id)
        agora = agora or timezone.now()
        if envio.expira_em <= agora:
            raise RecusaPublicacao(['envio expirado: envie o arquivo de novo'])
        estudo = _estudo_da_fazenda(envio, estudo_id)
        previa = _ingerir_original(envio)
        completa = montar_previa(previa, metadados)
        atributos = _conferir_previa(estudo, previa, completa, ocultos, sistema_confirmado)
        nos = _nos_da_publicacao(envio, previa, atributos, nos, coluna_no)
        contornos = {} if coluna_no is not None else contornos_da_divisao(envio.fazenda)
        sugeridos = _sugeridos(envio, previa.feicoes, contornos)
        camada = _camada_da_publicacao(estudo, camada_id, completa.metadados.obrigatorios['nome'])
        _alinhar_divisao(camada, coluna_no)
        versao = _gravar_versao(pessoa, envio, camada, previa, completa, ocultos, nos)
        _auditar(pessoa, envio, versao, camada, previa, ocultos, nos, sugeridos)
        envio.delete()  # o original fica: é `caminho_original` da versão (R15); só a linha do envio sai
    return versao


def ler_previa(envio):
    """Prévia de um envio já guardado (R12): relê o original com hash, ingere de novo e sugere nós. Sem valor de atributo:
    só colunas, sistema, transformação, avisos, contagem e o nó sugerido de cada feição. Envio vencido é recusado (mesma regra de
    `publicar_envio`: `expira_em <= agora`)."""
    if _vencido(envio):
        raise RecusaPublicacao(['envio vencido'])
    previa = _ingerir_original(envio)
    sugestoes = _sugestoes(envio, previa.feicoes, contornos_da_divisao(envio.fazenda))
    ativos = SubArea.objects.filter(fazenda=envio.fazenda, arquivada_em__isnull=True).order_by('pk')
    nomes = {no.pk: no.nome for no in ativos}
    # Revisão (R7/R12): feição que cruza dois ou mais nós, empata nas duas maiores áreas, ou fica fora de todos os nós. Fora
    # de todos fica na própria fazenda (nó None), sem escolha obrigatória. O motivo e as áreas vêm do `sugerir_no`, não do JS.
    revisao = [
        {'indice': indice, 'motivo': sugestao.motivo, 'sugerido': sugestao.sub_area_id,
         'areas': [{'no': no, 'nome': nomes.get(no, ''), 'area': area} for no, area in sugestao.areas.items()]}
        for indice, sugestao in enumerate(sugestoes, start=1)
        if len(sugestao.areas) >= 2 or sugestao.motivo in ('empate', 'sem_intersecao')
    ] if nomes else []
    return {
        'formato': previa.formato, 'tipo': previa.tipo, 'sistema': previa.sistema,
        'origem_sistema': previa.origem_sistema, 'transformacao': previa.transformacao,
        'avisos': list(previa.avisos), 'contagem': previa.contagem, 'colunas': list(previa.campos),
        'nos_sugeridos': [sugestao.sub_area_id for sugestao in sugestoes],
        'nos_da_fazenda': [{'no': no, 'nome': nome} for no, nome in nomes.items()],
        'revisao': revisao,
    }


COR_DA_PREVIA = '--cor-camada-provisoria-1'  # nome da variável CSS (camadas.css), não cor: o mapa.js resolve `cor` por getPropertyValue
FICHA_DA_PREVIA = {**dict.fromkeys(CAMPOS, SEM_INFORMACAO), 'camada': 'Prévia do envio (em análise)'}


def _vencido(envio):
    return envio.expira_em <= timezone.now()


def ler_geometria(envio, limite):
    """Geometria do envio para o mapa de teste (008 R12): até `limite` feições em 4326, com o total e a flag de truncado.
    Sem atributo. Envio vencido é o mesmo `EnvioNaoEncontrado` de publicar (a API responde 404)."""
    if _vencido(envio):
        raise EnvioNaoEncontrado()
    feicoes = _ingerir_original(envio).feicoes
    return {
        'type': 'FeatureCollection',  # GeoJSON: a chave é `type`, como o `validarColecao` do mapa.js espera
        'features': [
            # Contrato do `mapa.js` (`validarColecao`): `camada_id` e `cor` strings, e todo campo da ficha string. O envio não tem
            # fonte, data, situação nem origem: vai "Sem informação" (ausente, nunca zero), como na ficha das camadas publicadas.
            {'type': 'Feature', 'properties': {**FICHA_DA_PREVIA, 'indice': indice, 'camada_id': str(envio.publico_id), 'cor': COR_DA_PREVIA},
             'geometry': json.loads(feicao.geometria.transform(4326, clone=True).json)}
            for indice, feicao in enumerate(feicoes[:limite], start=1)
        ],
        'total': len(feicoes), 'limite': limite, 'truncado': len(feicoes) > limite,
    }
