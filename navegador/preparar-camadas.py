# Dado sintético da tela de camadas (008 T4.2), rodado por `manage.py shell` antes do Playwright. Cria um envio vencido na
# primeira fazenda da empresa A e grava o id em `navegador/dados.json` (chave `camadas`). Não é código de produção.
import json
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

from catalogo.envios import criar_envio
from catalogo.models import EnvioCamada
from identidade.models import Pessoa
from territorio.models import Fazenda

ARQUIVO = Path('/repo/navegador/dados.json')
dados = json.loads(ARQUIVO.read_text(encoding='utf-8'))
fazenda = Fazenda.objects.get(pk=dados['fazendas_a'][0])
pessoa = Pessoa.objects.order_by('pk').first()
conteudo = json.dumps({'type': 'FeatureCollection', 'features': [
    {'type': 'Feature', 'properties': {'valor': 1}, 'geometry': {'type': 'Point', 'coordinates': [-48.3, -10.7]}},
]}).encode()
envio = criar_envio(pessoa, fazenda, conteudo)
EnvioCamada.objects.filter(pk=envio.pk).update(expira_em=timezone.now() - timedelta(minutes=1))
dados['camadas'] = {'envio_vencido': str(envio.publico_id)}
ARQUIVO.write_text(json.dumps(dados, indent=2), encoding='utf-8')
print('ok', dados['camadas'])
