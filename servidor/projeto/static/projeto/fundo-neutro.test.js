// Fundo neutro (004 R15, T1.7): a forma que o `mapa.js` aceita e que o fundo Google também terá; sem rede.
const test = require('node:test');
const assert = require('node:assert/strict');

test('o fundo é só uma camada de cor, sem fonte e sem endereço de rede', async () => {
  const { fundo, COR_DO_FUNDO } = await import('./fundo-neutro.js');
  const { fontes, camadas } = fundo();
  assert.deepEqual(fontes, {});
  assert.deepEqual(camadas, [{ id: 'fundo-neutro', type: 'background', paint: { 'background-color': COR_DO_FUNDO } }]);
  assert.ok(!JSON.stringify(fundo()).includes('http'));
});

test('cada chamada devolve objetos novos: quem monta o estilo pode alterar sem afetar a próxima', async () => {
  const { fundo } = await import('./fundo-neutro.js');
  assert.notEqual(fundo().camadas, fundo().camadas);
});
