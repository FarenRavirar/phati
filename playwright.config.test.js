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
    'computador-1280x720': { width: 1280, height: 720 },
    'celular-320x568': { width: 320, height: 568 },
  });
});

test('o endereço padrão é o do nginx do compose e a variável de ambiente o troca', () => {
  assert.equal(carregar().use.baseURL, 'http://127.0.0.1:8080');
  assert.equal(carregar('http://exemplo.test:9000').use.baseURL, 'http://exemplo.test:9000');
});

test('os dois projetos lançam o Chromium com WebGL2 por software (spec 004 R16)', () => {
  const projetos = carregar().projects;
  assert.equal(projetos.length, 2);
  for (const projeto of projetos) {
    assert.deepEqual(projeto.use.launchOptions.args, ['--use-gl=angle', '--use-angle=swiftshader-webgl', '--enable-unsafe-swiftshader'], projeto.name);
    assert.ok(!projeto.use.launchOptions.args.includes('--disable-3d-apis'), projeto.name);
  }
});

test('o zoom roda só no projeto computador, sem skip', () => {
  const [computador, celular] = carregar().projects;
  const ignora = (projeto, arquivo) => [].concat(projeto.testIgnore ?? []).some((r) => r.test(arquivo));
  assert.equal(ignora(computador, 'zoom.spec.js'), false);
  assert.ok(ignora(celular, 'zoom.spec.js'));
  assert.equal(ignora(celular, 'entrar.spec.js'), false);
});

test('a prova do Google roda à parte: fora da rodada comum, e sozinha com PHATI_PROVA_GOOGLE=1', () => {
  const anterior = process.env.PHATI_PROVA_GOOGLE;
  try {
    delete process.env.PHATI_PROVA_GOOGLE;
    const comum = carregar();
    assert.equal(comum.testMatch, '*.spec.js');
    // Cada projeto tem o próprio `testIgnore` (o de projeto substitui o da raiz): os dois têm de excluir a prova do Google.
    for (const projeto of comum.projects) {
      const ignorados = [].concat(projeto.testIgnore);
      assert.ok(ignorados.some((r) => r.test('navegador/fundo-google.spec.js')), projeto.name);
      assert.ok(!ignorados.some((r) => r.test('navegador/mapa.spec.js')), projeto.name);
    }
    process.env.PHATI_PROVA_GOOGLE = '1';
    const so = carregar();
    assert.equal(so.testMatch, 'fundo-google.spec.js');
    for (const projeto of so.projects) {
      assert.ok(![].concat(projeto.testIgnore ?? []).some((r) => r.test('navegador/fundo-google.spec.js')), projeto.name);
    }
    process.env.PHATI_PROVA_GOOGLE = 'true'; // só o valor 1 liga
    assert.equal(carregar().testMatch, '*.spec.js');
  } finally {
    if (anterior === undefined) delete process.env.PHATI_PROVA_GOOGLE;
    else process.env.PHATI_PROVA_GOOGLE = anterior;
  }
});

test('a prova do mapa desligado roda à parte: fora da rodada comum, e sozinha com PHATI_PROVA_MAPA_DESLIGADO=1', () => {
  const anterior = process.env.PHATI_PROVA_MAPA_DESLIGADO;
  try {
    delete process.env.PHATI_PROVA_MAPA_DESLIGADO;
    const comum = carregar();
    assert.equal(comum.testMatch, '*.spec.js');
    for (const projeto of comum.projects) {
      assert.ok([].concat(projeto.testIgnore).some((r) => r.test('navegador/mapa-desligado.spec.js')), projeto.name);
    }
    process.env.PHATI_PROVA_MAPA_DESLIGADO = '1';
    const so = carregar();
    assert.equal(so.testMatch, 'mapa-desligado.spec.js');
    for (const projeto of so.projects) {
      assert.ok(![].concat(projeto.testIgnore ?? []).some((r) => r.test('navegador/mapa-desligado.spec.js')), projeto.name);
    }
    process.env.PHATI_PROVA_MAPA_DESLIGADO = 'true'; // só o valor 1 liga
    assert.equal(carregar().testMatch, '*.spec.js');
  } finally {
    if (anterior === undefined) delete process.env.PHATI_PROVA_MAPA_DESLIGADO;
    else process.env.PHATI_PROVA_MAPA_DESLIGADO = anterior;
  }
});
