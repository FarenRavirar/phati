"""Envio em prévia (008 R12, R13, R15, T2.4): guarda o original, valida pela ingestão e cria a linha `EnvioCamada`.

Quem cria o envio precisa de `publicar_camada` na fazenda, checado por `pode()` no servidor. Recusa na ingestão ou
falha ao gravar a linha apaga o original: sem arquivo nem linha. A prévia guarda o nome interno e o hash; a
confirmação (Fase 3) relê o original guardado e confere o hash, sem reler o arquivo do usuário."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from catalogo import original
from catalogo.ingestao import ingerir_envio
from catalogo.models import EnvioCamada
from permissao.pode import com_permissao, pode

# shortcut: validade inicial da prévia, a confirmar com o mantenedor (prazo de produto, não medido).
VALIDADE_PREVIA = timedelta(hours=24)
ACAO = 'publicar_camada'


def criar_envio(pessoa, fazenda, dados, agora=None):
    """Cria a prévia. Recusa (ingestão, permissão ou banco) não deixa arquivo nem linha."""
    agora = agora or timezone.now()
    with com_permissao(pessoa, ACAO):
        if not pode(pessoa, ACAO, fazenda):
            raise PermissionDenied
        nome, digest = original.gravar(dados)
        try:
            ingerir_envio(original.caminho_interno(nome))  # valida; o original fica se passar
            with transaction.atomic():
                envio = EnvioCamada.objects.create(
                    criado_por=pessoa, empresa=fazenda.empresa, fazenda=fazenda, arquivo_temporario=nome,
                    hash_original=digest, expira_em=agora + VALIDADE_PREVIA,
                )
        except BaseException:
            original.remover(nome)
            raise
    return envio


def limpar_expirados(pessoa, agora=None):
    """Apaga os envios vencidos e os originais deles, só dentro de CAMADAS_DIR. Devolve (removidos, ignorados).

    Vê só o que a RLS deixa à pessoa: para a limpeza da plataforma, o operador é o Administrador da plataforma.
    Nome interno inválido não apaga nada: a linha fica e conta como ignorada."""
    agora = agora or timezone.now()
    removidos = ignorados = 0
    with com_permissao(pessoa, ACAO):
        for envio in list(EnvioCamada.objects.filter(expira_em__lte=agora)):
            try:
                original.remover(envio.arquivo_temporario)
            except original.OriginalInvalido:
                ignorados += 1
                continue
            envio.delete()
            removidos += 1
    return removidos, ignorados
