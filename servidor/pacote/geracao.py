"""Geração do pacote offline de uma fazenda (004b R2, R5, R20): o único caminho que grava uma versão.

Fluxo: valida a pessoa e a caixa → monta os arquivos num diretório temporário (`pmtiles extract`, `rio pmtiles`, `pmtiles
verify`) → numa transação que trava a fazenda calcula o número, grava o manifesto, troca o ponteiro vigente, renomeia o
diretório e audita. Qualquer falha antes da troca apaga o temporário e deixa a versão vigente intacta."""

import getpass
import json
import math
import shutil
import subprocess
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from comum.auditoria import auditar
from pacote import manifesto as contrato
from pacote.models import VersaoPacote
from permissao.pode import com_permissao, pode
from territorio.models import Fazenda

ATRIBUICAO_FUNDO = '© OpenStreetMap contributors'
LICENCA_FUNDO = 'ODbL 1.0'
ZOOM_MAXIMO_FUNDO_PADRAO = 15
ZOOM_MINIMO_ORTOFOTO_PADRAO = 14
ZOOM_MAXIMO_ORTOFOTO_PADRAO = 19  # medido na T0.6: ~1,9 MB por km² em z19 e ~9 MB em z20 (ortofoto sintética)
PRAZO_DA_FERRAMENTA = 3600  # segundos; sem prazo, uma ferramenta travada prenderia o comando para sempre


class ErroDeGeracao(RuntimeError):
    """Ferramenta externa falhou ou o resultado não confere; a versão vigente segue intacta."""


def validar_caixa(caixa) -> tuple[float, float, float, float]:
    """`oeste, sul, leste, norte` em WGS 84, finitos, oeste < leste e sul < norte (R2)."""
    try:
        oeste, sul, leste, norte = (float(valor) for valor in caixa)
    except (TypeError, ValueError):
        raise ValidationError('A caixa precisa de 4 números: oeste, sul, leste, norte.') from None
    if not all(math.isfinite(v) for v in (oeste, sul, leste, norte)):
        raise ValidationError('A caixa tem número inválido.')
    if not (-180 <= oeste < leste <= 180 and -90 <= sul < norte <= 90):
        raise ValidationError('A caixa fica fora do mundo ou tem lado invertido.')
    return oeste, sul, leste, norte


def _executar(argumentos: list[str]) -> str:
    try:
        resultado = subprocess.run(argumentos, capture_output=True, text=True, timeout=PRAZO_DA_FERRAMENTA, check=False)
    except (OSError, subprocess.TimeoutExpired) as erro:
        raise ErroDeGeracao(f'{argumentos[0]} não rodou: {erro}') from erro
    if resultado.returncode != 0:
        raise ErroDeGeracao(f'{argumentos[0]} saiu com {resultado.returncode}: {resultado.stderr.strip()[-500:]}')
    return resultado.stdout


def _cabecalho(arquivo: Path) -> dict:
    """Verifica o arquivo (`pmtiles verify`) e devolve o cabeçalho (`minzoom`, `maxzoom`, `tile_type`)."""
    _executar([settings.PMTILES_BIN, 'verify', str(arquivo)])
    return json.loads(_executar([settings.PMTILES_BIN, 'show', str(arquivo), '--header-json']))


def _arquivo_existente(caminho, descricao: str) -> Path:
    arquivo = Path(caminho).resolve()
    if not arquivo.is_file():
        raise ValidationError(f'{descricao} não existe: {caminho}')
    return arquivo


def _item(arquivo: Path, papel: str, cabecalho: dict, atribuicao: str, licenca: str, capturada_em=None) -> dict:
    return {
        'nome': arquivo.name, 'papel': papel, 'bytes': arquivo.stat().st_size, 'sha256': contrato.sha256_do_arquivo(arquivo),
        'zoom_minimo': cabecalho['minzoom'], 'zoom_maximo': cabecalho['maxzoom'],
        'atribuicao': atribuicao, 'licenca': licenca, 'capturada_em': capturada_em,
    }


def gerar_pacote(
    quem, fazenda: Fazenda, caixa, *, fundo_origem, ortofoto=None, ortofoto_capturada_em: date | None = None,
    zoom_maximo_fundo: int = ZOOM_MAXIMO_FUNDO_PADRAO, zoom_minimo_ortofoto: int = ZOOM_MINIMO_ORTOFOTO_PADRAO,
    zoom_maximo_ortofoto: int = ZOOM_MAXIMO_ORTOFOTO_PADRAO, atribuicao_ortofoto: str = 'Ortofoto da própria empresa',
    origem: str = 'comando', camadas=(),
) -> VersaoPacote:
    """Gera a próxima versão do pacote de `fazenda` e a torna vigente. Só o Administrador da plataforma (R2).

    `fundo_origem`: PMTiles vetorial aberto (arquivo local, "clustered"). `ortofoto`: GeoTIFF/COG opcional, convertido até
    `zoom_maximo_ortofoto`, o teto que fica no manifesto (R5). Levanta `PermissionDenied`, `ValidationError` (entrada) ou
    `ErroDeGeracao` (ferramenta); em todos a versão vigente fica como estava e nenhum diretório temporário sobra."""
    if not (getattr(quem, 'administrador_plataforma', False) and pode(quem, 'ver', fazenda)):
        raise PermissionDenied
    oeste, sul, leste, norte = validar_caixa(caixa)
    zooms = (zoom_maximo_fundo, zoom_minimo_ortofoto, zoom_maximo_ortofoto)
    # `bool` é `int` em Python e `2.5` passa na faixa: os zooms vão como texto para o comando externo, então só inteiro de verdade.
    if not all(type(z) is int for z in zooms) or not (0 <= zoom_maximo_fundo <= 24 and 0 <= zoom_minimo_ortofoto <= zoom_maximo_ortofoto <= 24):
        raise ValidationError('Zoom fora de 0 a 24, não inteiro, ou mínimo maior que o máximo.')
    fundo = _arquivo_existente(fundo_origem, 'O fundo de origem')
    foto = _arquivo_existente(ortofoto, 'A ortofoto') if ortofoto else None

    raiz = Path(settings.PACOTES_DIR) / str(fazenda.pk)
    temporario = raiz / f'.tmp-{uuid.uuid4().hex}'
    temporario.mkdir(parents=True)
    try:
        itens = []
        destino = temporario / 'fundo.pmtiles'
        _executar([
            settings.PMTILES_BIN, 'extract', str(fundo), str(destino),
            f'--bbox={oeste},{sul},{leste},{norte}', f'--maxzoom={zoom_maximo_fundo}',
        ])
        itens.append(_item(destino, 'fundo', _cabecalho(destino), ATRIBUICAO_FUNDO, LICENCA_FUNDO))
        if foto is not None:
            destino = temporario / 'ortofoto.pmtiles'
            _executar([
                settings.RIO_BIN, 'pmtiles', str(foto), str(destino), '--format', 'JPEG',
                '--zoom-levels', f'{zoom_minimo_ortofoto}..{zoom_maximo_ortofoto}',
            ])
            cabecalho = _cabecalho(destino)
            if cabecalho['maxzoom'] > zoom_maximo_ortofoto:
                raise ErroDeGeracao('a ortofoto passou do teto de zoom')
            itens.append(_item(destino, 'ortofoto', cabecalho, atribuicao_ortofoto, 'Uso restrito à empresa', ortofoto_capturada_em))
        return _publicar(quem, fazenda, temporario, raiz, itens, zoom_maximo_ortofoto, origem, list(camadas))
    except BaseException:
        shutil.rmtree(temporario, ignore_errors=True)  # a vigente nunca é tocada antes da troca
        raise


def _publicar(quem, fazenda, temporario: Path, raiz: Path, itens: list, teto: int, origem: str, camadas: list) -> VersaoPacote:
    with com_permissao(quem), transaction.atomic():
        # Trava a fazenda: duas gerações simultâneas se enfileiram aqui e recebem números diferentes (R20).
        Fazenda.objects.select_for_update().get(pk=fazenda.pk)
        ultimo = VersaoPacote.objects.filter(fazenda=fazenda).order_by('-numero').values_list('numero', flat=True).first()
        numero = (ultimo or 0) + 1
        manifesto = contrato.validar({
            'formato_versao': contrato.FORMATO_VERSAO, 'fazenda_id': fazenda.pk, 'versao': numero,
            'gerado_em': datetime.now(timezone.utc), 'zoom_maximo_ortofoto': teto, 'arquivos': itens, 'camadas': camadas,
        })
        conteudo = json.loads(manifesto.model_dump_json())
        (temporario / contrato.NOME_DO_MANIFESTO).write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding='utf-8')
        VersaoPacote.objects.filter(fazenda=fazenda, vigente=True).update(vigente=False)  # antes de inserir: no máximo uma vigente
        versao = VersaoPacote.objects.create(
            empresa_id=fazenda.empresa_id, fazenda=fazenda, numero=numero, manifesto=conteudo, vigente=True,
        )
        auditar('pacote_gerado', quem, fazenda, fazenda.empresa_id, {'versao': numero, 'origem': origem, 'usuario_so': getpass.getuser()})
        # A troca de diretório é o último passo: falha antes dela desfaz a transação inteira. Diretório com este número que o
        # banco não conhece é sobra de um commit que não chegou a valer (a fazenda está travada, então ninguém o usa).
        destino = raiz / f'v{numero}'
        shutil.rmtree(destino, ignore_errors=True)
        temporario.rename(destino)
        return versao
