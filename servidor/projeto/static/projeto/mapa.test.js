// Adaptador do mapa (004 R15, T1.7): lógica pura, sem MapLibre nem DOM. O MapLibre real roda em `navegador/mapa.spec.js`.
const test = require('node:test');
const assert = require('node:assert/strict');

test('importar o módulo no Node não carrega o MapLibre nem exige DOM', async () => {
  const mapa = await import('./mapa.js');
  assert.deepEqual(Object.keys(mapa).sort(), ['CENTRO_INICIAL', 'ZOOM_INICIAL', 'criarMapa', 'montarEstilo', 'mostrarErro']);
});

test('o estilo é o fundo abaixo de tudo, na versão 8 da especificação', async () => {
  const { montarEstilo } = await import('./mapa.js');
  const { fundo } = await import('./fundo-neutro.js');
  assert.deepEqual(montarEstilo(fundo()), { version: 8, sources: {}, layers: fundo().camadas });
});

test('aceita qualquer fundo com a forma {fontes, camadas}, não só o neutro', async () => {
  const { montarEstilo } = await import('./mapa.js');
  const outro = { fontes: { x: { type: 'raster', tiles: ['t'] } }, camadas: [{ id: 'x', type: 'raster', source: 'x' }] };
  const estilo = montarEstilo(outro);
  assert.deepEqual(Object.keys(estilo.sources), ['x']);
  assert.equal(estilo.layers[0].id, 'x');
});

test('fundo fora da forma é erro, não mapa em branco', async () => {
  const { montarEstilo } = await import('./mapa.js');
  for (const ruim of [undefined, null, {}, { fontes: {} }, { fontes: null, camadas: [] }, { fontes: {}, camadas: 'x' }]) {
    assert.throws(() => montarEstilo(ruim), /fora da forma/);
  }
});

test('criarMapa entrega ao motor o elemento, o estilo e o centro perto de (0°, 0°)', async () => {
  const { criarMapa, CENTRO_INICIAL, ZOOM_INICIAL } = await import('./mapa.js');
  const { fundo } = await import('./fundo-neutro.js');
  let recebido;
  class Falso { constructor(opcoes) { recebido = opcoes; } }
  const elemento = {};
  criarMapa({ Map: Falso }, elemento, fundo());
  assert.equal(recebido.container, elemento);
  assert.equal(recebido.style.version, 8);
  assert.deepEqual(recebido.center, CENTRO_INICIAL);
  assert.equal(recebido.zoom, ZOOM_INICIAL);
  assert.ok(Math.abs(CENTRO_INICIAL[0]) < 1 && Math.abs(CENTRO_INICIAL[1]) < 1);
});

test('mostrarErro marca o mapa e revela o aviso da região; sem aviso, só marca', async () => {
  const { mostrarErro } = await import('./mapa.js');
  const aviso = { hidden: true };
  const elemento = { dataset: {}, parentElement: { querySelector: (seletor) => (seletor === '[data-mapa-aviso]' ? aviso : null) } };
  mostrarErro(elemento);
  assert.equal(elemento.dataset.mapaErro, 'sim');
  assert.equal(aviso.hidden, false);
  const sozinho = { dataset: {}, parentElement: null };
  mostrarErro(sozinho);
  assert.equal(sozinho.dataset.mapaErro, 'sim');
});
