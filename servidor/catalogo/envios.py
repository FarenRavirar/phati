"""Envio em prévia (008 R12, R13, R15, T2.4): guarda o original, valida pela ingestão e cria a linha `EnvioCamada`.

Quem cria o envio precisa de `publicar_camada` na fazenda, checado por `pode()` no servidor. Recusa na ingestão ou
falha ao gravar a linha apaga o original: sem arquivo nem linha. A prévia guarda o nome interno e o hash; a
confirmação (Fase 3) relê o original guardado e confere o hash, sem reler o arquivo do usuário."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from catalogo import original
from catalogo.ingestao import LIMITES_PADRAO, MENSAGEM_TAMANHO, RecusaIngestao, ingerir_envio
from catalogo.models import EnvioCamada
from permissao.pode import com_permissao, pode

# shortcut: validade inicial da prévia, a confirmar com o mantenedor (prazo de produto, não medido).
VALIDADE_PREVIA = timedelta(hours=24)
ACAO = 'publicar_camada'


def criar_envio(pessoa, fazenda, dados, agora=None):
    """Cria a prévia. Recusa (ingestão, permissão ou banco) não deixa arquivo nem linha."""
    agora = agora or timezone.now()
    nome = None
    try:
        with com_permissao(pessoa, ACAO):  # a saída do contexto também pode falhar: a limpeza cobre o bloco inteiro
            if not pode(pessoa, ACAO, fazenda):
                raise PermissionDenied
            if len(dados) > LIMITES_PADRAO.tamanho_bytes:  # antes de gravar: mesma recusa de ingerir_envio
                raise RecusaIngestao([MENSAGEM_TAMANHO])
            nome, digest = original.gravar(dados)
            ingerir_envio(original.caminho_interno(nome))  # valida; o original fica se passar
            with transaction.atomic():
                envio = EnvioCamada.objects.create(
                    criado_por=pessoa, empresa=fazenda.empresa, fazenda=fazenda, arquivo_temporario=nome,
                    hash_original=digest, expira_em=agora + VALIDADE_PREVIA,
                )
    except BaseException:
        if nome is not None:
            original.remover(nome)
        raise
    return envio


def _remover_vencido(pk, agora):
    """Apaga a linha vencida e, depois do COMMIT, o original dela. Devolve False se a linha não foi removida.

    Mesmo protocolo da publicação: a linha é travada com `skip_locked`. Publicação em curso segura a trava, então a
    limpeza pula e o original fica (quem publica já o tem como `caminho_original`). Quem trava depois da limpeza não
    acha a linha e recebe EnvioNaoEncontrado, sem ler arquivo apagado. O arquivo só sai depois do COMMIT: nunca há
    versão sem original."""
    with transaction.atomic():
        envio = EnvioCamada.objects.select_for_update(skip_locked=True).filter(pk=pk, expira_em__lte=agora).first()
        if envio is None:  # travada por publicação, já removida ou não vencida
            return False
        try:
            original.caminho_interno(envio.arquivo_temporario)
        except original.OriginalInvalido:
            return False
        nome = envio.arquivo_temporario
        envio.delete()
        transaction.on_commit(lambda: original.remover(nome))
    return True


def limpar_expirados(pessoa, agora=None):
    """Apaga os envios vencidos e os originais deles, só dentro de CAMADAS_DIR. Devolve (removidos, ignorados).

    Vê só o que a RLS deixa à pessoa: para a limpeza da plataforma, o operador é o Administrador da plataforma.
    Ignorado = nome interno inválido (a linha fica) ou envio travado por publicação em curso (a limpeza pula)."""
    agora = agora or timezone.now()
    removidos = ignorados = 0
    with com_permissao(pessoa, ACAO):
        pks = list(EnvioCamada.objects.filter(expira_em__lte=agora).values_list('pk', flat=True))
        for pk in pks:
            if _remover_vencido(pk, agora):
                removidos += 1
            else:
                ignorados += 1
    return removidos, ignorados
