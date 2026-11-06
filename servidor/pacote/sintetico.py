"""Pacote de referência instalado numa fazenda sintética (004b R6, T2.1a): serve o ambiente de teste de navegador e os testes.

Copia `referencia/` para `PACOTES_DIR/<fazenda>/v1` e grava a versão 1 vigente, sem rodar `pmtiles` nem `rio`. É dado inventado
e minúsculo (R19); nunca roda fora de teste: quem chama (`popular_sintetico`) já recusa ambiente real."""

import json
import shutil
from pathlib import Path

from django.conf import settings
from django.db import transaction

from pacote.models import VersaoPacote

REFERENCIA = Path(__file__).resolve().parent / 'referencia'


def instalar_referencia(fazenda) -> VersaoPacote:
    """Instala o pacote de referência como versão 1 vigente de `fazenda`. Recusa fazenda que já tem versão (nada é sobrescrito)."""
    destino = Path(settings.PACOTES_DIR) / str(fazenda.pk) / 'v1'
    with transaction.atomic():
        if VersaoPacote.objects.filter(fazenda=fazenda).exists():
            raise ValueError('fazenda_ja_tem_pacote')
        manifesto = json.loads((REFERENCIA / 'manifesto.json').read_text(encoding='utf-8'))
        manifesto['fazenda_id'] = fazenda.pk  # a linha do banco e o manifesto dela falam da mesma fazenda
        versao = VersaoPacote.objects.create(empresa_id=fazenda.empresa_id, fazenda=fazenda, numero=1, manifesto=manifesto, vigente=True)
        shutil.copytree(REFERENCIA, destino)  # depois do banco: se a cópia falhar, a transação desfaz a linha
        (destino / 'manifesto.json').write_text(json.dumps(manifesto, indent=2, ensure_ascii=False), encoding='utf-8')  # o do disco também
    return versao
