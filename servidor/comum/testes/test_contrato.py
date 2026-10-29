"""O contrato OpenAPI commitado é o que a API gera (T5.1; R17).

Para regenerar depois de mudar uma rota:
python manage.py export_openapi_schema --api projeto.api.api --output contrato/openapi.json --indent 2 --sorted
"""

import json
from pathlib import Path

from django.conf import settings
from ninja.responses import NinjaJSONEncoder

from projeto.api import api

CONTRATO = Path(settings.DIRETORIO_BASE) / 'contrato' / 'openapi.json'


def test_contrato_commitado_e_igual_ao_gerado():
    gerado = json.loads(json.dumps(api.get_openapi_schema(), cls=NinjaJSONEncoder))
    assert json.loads(CONTRATO.read_text(encoding='utf-8')) == gerado


def test_contrato_nao_expoe_o_valor_de_nenhum_segredo():
    texto = CONTRATO.read_text(encoding='utf-8')
    assert 'senha_temporaria' in texto  # o campo existe (R4); valor nenhum vive no contrato
    assert settings.SECRET_KEY not in texto
