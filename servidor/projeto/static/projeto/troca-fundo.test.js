// Troca de fundo (004b R9, R10, A8): exclusão mútua entre fundo próprio e online, ordem em relação às camadas do produto,
// volta por falha e escolha manual. Dublê de mapa com a mesma exigência do motor: fonte antes da camada, id sem repetição.
const test = require('node:test');
const assert = require('node:assert/strict');

function mapaDuble() {
  const fontes = new Map();
  const camadas = [];
  return {
    fontes,
    camadas,
    addSource(id, fonte) {
      if (fontes.has(id)) throw new Error(`fonte ${id} já existe`);
      fontes.set(id, fonte);
    },
    removeSource(id) {
      if (camadas.some((c) => c.source === id)) throw new Error(`fonte ${id} ainda tem camada`);
      fontes.delete(id);
    },
    getSource: (id) => fontes.get(id),
    addLayer(camada, antes) {
      if (camadas.some((c) => c.id === camada.id)) throw new Error(`camada ${camada.id} já existe`);
      if (camada.source && !fontes.has(camada.source)) throw new Error(`camada ${camada.id} sem fonte`);
      const posicao = antes === undefined ? camadas.length : camadas.findIndex((c) => c.id === antes);
      camadas.splice(posicao, 0, camada);
    },
    removeLayer(id) {
      const posicao = camadas.findIndex((c) => c.id === id);
      if (posicao < 0) throw new Error(`camada ${id} não existe`);
      camadas.splice(posicao, 1);
    },
    getLayer: (id) => camadas.find((c) => c.id === id),
    ids: () => camadas.map((c) => c.id),
  };
}

const neutro = { id: 'fundo-neutro', type: 'background' };
const proprio = () => ({
  fontes: { fundo: { type: 'vector' } },
  camadas: [{ id: 'fundo-terra', type: 'fill', source: 'fundo' }, { id: 'fundo-estrada', type: 'line', source: 'fundo' }],
});
const google = () => ({ fontes: { 'fundo-online': { type: 'raster' } }, camadas: [{ id: 'fundo-online', type: 'raster', source: 'fundo-online' }], parar: test.mock.fn() });

function iniciar(opcoes = {}) {
  const mapa = mapaDuble();
  mapa.addLayer(neutro);
  mapa.addLayer({ id: 'camada-a-preenchimento', type: 'fill' });
  mapa.addLayer({ id: 'camada-ortofoto', type: 'raster' });
  return { mapa, ...opcoes };
}
// O dublê confere a exclusão mútua depois de cada mutação, não só no fim do teste: estado intermediário com os dois fundos reprova.
function vigiar(mapa) {
  for (const metodo of ['addSource', 'removeSource', 'addLayer', 'removeLayer']) {
    const original = mapa[metodo];
    mapa[metodo] = (...args) => {
      const resultado = original.apply(mapa, args);
      nuncaJuntos(mapa);
      return resultado;
    };
  }
  return mapa;
}

const montar = async (extra = {}) => {
  const { criarTroca } = await import('./troca-fundo.js');
  const { mapa } = iniciar();
  vigiar(mapa);
  const antes = () => mapa.camadas.find((c) => c.id.startsWith('camada-'))?.id;
  return { mapa, troca: criarTroca(mapa, { proprio: proprio(), antes, ...extra }) };
};

// Invariante do R10, conferida a cada passo: camada do próprio e camada do online nunca coexistem.
function nuncaJuntos(mapa) {
  const ids = mapa.ids();
  assert.ok(!(ids.includes('fundo-terra') && ids.includes('fundo-online')), `os dois fundos juntos: ${ids}`);
  assert.ok(!(mapa.fontes.has('fundo') && mapa.fontes.has('fundo-online')), 'as duas fontes de fundo juntas');
}

test('o verificador de exclusão mútua reprova quando os dois fundos estão no mapa', () => {
  const mapa = mapaDuble();
  mapa.addSource('fundo', {});
  mapa.addSource('fundo-online', {});
  mapa.addLayer({ id: 'fundo-terra', source: 'fundo' });
  mapa.addLayer({ id: 'fundo-online', source: 'fundo-online' });
  assert.throws(() => nuncaJuntos(mapa), /os dois fundos juntos/);
});

test('abre no fundo próprio, abaixo de todas as camadas do produto e acima do neutro', async () => {
  const { mapa, troca } = await montar();
  troca.usarProprio();
  assert.deepEqual(mapa.ids(), ['fundo-neutro', 'fundo-terra', 'fundo-estrada', 'camada-a-preenchimento', 'camada-ortofoto']);
  assert.deepEqual(troca.estado(), { ativo: 'proprio', modo: 'automatico' });
});

test('ligar o Google tira o fundo próprio antes de pôr o online, que entra abaixo das camadas e da ortofoto', async () => {
  const { mapa, troca } = await montar();
  troca.usarProprio();
  troca.usarOnline(google());
  nuncaJuntos(mapa);
  assert.deepEqual(mapa.ids(), ['fundo-neutro', 'fundo-online', 'camada-a-preenchimento', 'camada-ortofoto']);
  assert.equal(mapa.fontes.has('fundo'), false);
  assert.deepEqual(troca.estado(), { ativo: 'online', modo: 'manual' });
});

test('falha do online volta ao próprio por modo automático e para o online antes de tirá-lo', async () => {
  const { mapa, troca } = await montar();
  troca.usarProprio();
  const online = google();
  troca.usarOnline(online);
  troca.falhouOnline();
  nuncaJuntos(mapa);
  assert.equal(online.parar.mock.callCount(), 1);
  assert.deepEqual(mapa.ids(), ['fundo-neutro', 'fundo-terra', 'fundo-estrada', 'camada-a-preenchimento', 'camada-ortofoto']);
  assert.equal(mapa.fontes.has('fundo-online'), false);
  assert.deepEqual(troca.estado(), { ativo: 'proprio', modo: 'automatico' });
  assert.equal(troca.online(), null);
});

test('a escolha manual vai e volta nos dois sentidos, e o modo registra a escolha', async () => {
  const { mapa, troca } = await montar();
  troca.usarProprio();
  for (let volta = 0; volta < 3; volta += 1) {
    troca.usarOnline(google());
    nuncaJuntos(mapa);
    assert.deepEqual(troca.estado(), { ativo: 'online', modo: 'manual' });
    troca.usarProprio({ manual: true });
    nuncaJuntos(mapa);
    assert.deepEqual(troca.estado(), { ativo: 'proprio', modo: 'manual' });
  }
  assert.equal(mapa.camadas.length, 5);
});

test('as camadas do produto não são tocadas por nenhuma troca (id e ordem iguais)', async () => {
  const { mapa, troca } = await montar();
  const produto = () => mapa.ids().filter((id) => id.startsWith('camada-'));
  const antes = produto();
  troca.usarProprio();
  troca.usarOnline(google());
  troca.falhouOnline();
  troca.falhouProprio();
  assert.deepEqual(produto(), antes);
});

test('arquivo do pacote que não abre tira o próprio e deixa o neutro; nenhuma volta recoloca a fonte que falhou', async () => {
  const { mapa, troca } = await montar();
  troca.usarProprio();
  assert.equal(troca.temProprio(), true);
  troca.falhouProprio();
  assert.deepEqual(mapa.ids(), ['fundo-neutro', 'camada-a-preenchimento', 'camada-ortofoto']);
  assert.deepEqual(troca.estado(), { ativo: 'neutro', modo: 'automatico' });
  assert.equal(troca.temProprio(), false);
  troca.usarProprio();
  assert.equal(troca.estado().ativo, 'neutro');
  troca.usarOnline(google());
  troca.falhouOnline(); // o online também cai: fica o neutro, não o fundo que já falhou
  assert.equal(troca.estado().ativo, 'neutro');
  assert.deepEqual(mapa.ids(), ['fundo-neutro', 'camada-a-preenchimento', 'camada-ortofoto']);
  assert.equal(mapa.fontes.has('fundo'), false);
});

test('sem pacote não há fundo da fazenda para voltar', async () => {
  const { criarTroca } = await import('./troca-fundo.js');
  assert.equal(criarTroca(mapaDuble()).temProprio(), false);
});

test('falha do próprio com o online ativo não derruba o online, e a queda do online depois deixa o neutro', async () => {
  const { mapa, troca } = await montar();
  troca.usarProprio();
  troca.usarOnline(google());
  troca.falhouProprio();
  assert.equal(troca.estado().ativo, 'online');
  assert.ok(mapa.ids().includes('fundo-online'));
  assert.equal(troca.temProprio(), false);
  troca.falhouOnline();
  assert.deepEqual(troca.estado(), { ativo: 'neutro', modo: 'automatico' });
  assert.deepEqual(mapa.ids(), ['fundo-neutro', 'camada-a-preenchimento', 'camada-ortofoto']);
  assert.equal(mapa.fontes.has('fundo'), false);
});

test('sem pacote o mapa fica no neutro, o online liga e a falha dele devolve ao neutro', async () => {
  const { criarTroca } = await import('./troca-fundo.js');
  const { mapa } = iniciar();
  const troca = criarTroca(mapa, { antes: () => 'camada-a-preenchimento' });
  troca.usarProprio();
  assert.equal(troca.estado().ativo, 'neutro');
  troca.usarOnline(google());
  assert.equal(troca.estado().ativo, 'online');
  troca.falhouOnline();
  assert.deepEqual(troca.estado(), { ativo: 'neutro', modo: 'automatico' });
  assert.deepEqual(mapa.ids(), ['fundo-neutro', 'camada-a-preenchimento', 'camada-ortofoto']);
});

test('falhas repetidas e chamadas fora de hora não quebram nem duplicam camada', async () => {
  const { mapa, troca } = await montar();
  troca.falhouOnline(); // nada ativo
  troca.falhouProprio(); // próprio ainda não entrou
  troca.usarProprio();
  troca.usarProprio(); // idempotente
  troca.falhouProprio();
  troca.falhouProprio();
  assert.deepEqual(mapa.ids(), ['fundo-neutro', 'camada-a-preenchimento', 'camada-ortofoto']);
});

test('trocar o online por outro online para o primeiro', async () => {
  const { troca } = await montar();
  troca.usarProprio();
  const primeiro = google();
  troca.usarOnline(primeiro);
  troca.usarOnline(google());
  assert.equal(primeiro.parar.mock.callCount(), 1);
});
