'use strict';
// Config do Playwright (spec 002, R19): os dois tamanhos de tela exigidos pelo AGENTS.md e o zoom só no desktop.
const test = require('node:test');
const assert = require('node:assert/strict');

function carregar(url) {
  const anterior = process.env.PHATI_URL_NAVEGADOR;
  if (url === undefined) delete process.env.PHATI_URL_NAVEGADOR;
  else process.env.PHATI_URL_NAVEGADOR = url;
  delete require.cache[require.resolve('./playwright.config.js')];
  try {
    return require('./playwright.config.js');
  } finally {
    if (anterior === undefined) delete process.env.PHATI_URL_NAVEGADOR;
    else process.env.PHATI_URL_NAVEGADOR = anterior;
  }
}

test('os dois projetos têm os tamanhos de tela do AGENTS.md', () => {
  const tamanhos = Object.fromEntries(carregar().projects.map((p) => [p.name, p.use.viewport]));
  assert.deepEqual(tamanhos, {
    'desktop-1280x720': { width: 1280, height: 720 },
    'celular-320x568': { width: 320, height: 568 },
  });
});

test('o endereço padrão é o do nginx do compose e a variável de ambiente o troca', () => {
  assert.equal(carregar().use.baseURL, 'http://127.0.0.1:8080');
  assert.equal(carregar('http://exemplo.test:9000').use.baseURL, 'http://exemplo.test:9000');
});

test('o zoom roda só no projeto desktop, sem skip', () => {
  const [desktop, celular] = carregar().projects;
  assert.equal(desktop.testIgnore, undefined);
  assert.ok(celular.testIgnore.test('zoom.spec.js'));
  assert.equal(celular.testIgnore.test('entrar.spec.js'), false);
});
