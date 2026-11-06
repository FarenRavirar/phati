'use strict';
// Auxiliares dos testes de navegador, com páginas de mentira: nenhum navegador nem dados.json.
const test = require('node:test');
const assert = require('node:assert/strict');
const { LON0, LAT0, noMapa, tocar, turmaDe, semRolagemHorizontal, abrirMenu, cpfSintetico, ehExterna, observarRequisicoesExternas } = require('./apoio.js');

const dados = { turmas: { computador: { nome: 'p' }, celular: { nome: 'c' } } };
const projeto = (nome) => ({ project: { name: nome } });

test('cada projeto recebe a própria turma', () => {
  assert.equal(turmaDe(projeto('computador-1280x720'), dados).nome, 'p');
  assert.equal(turmaDe(projeto('celular-320x568'), dados).nome, 'c');
});

test('projeto sem turma levanta erro em vez de cair numa turma por padrão', () => {
  assert.throws(() => turmaDe(projeto('tablet-768x1024'), dados), /sem turma/);
});

test('semRolagemHorizontal reprova quando a página rola na horizontal', async () => {
  await semRolagemHorizontal({ evaluate: async () => true });
  await assert.rejects(semRolagemHorizontal({ evaluate: async () => false }), /rola na horizontal/);
});

function menuFalso(visivel, expandido) {
  const cliques = [];
  const botao = { isVisible: async () => visivel, getAttribute: async () => expandido, click: async () => cliques.push('menu') };
  return { cliques, pagina: { getByRole: () => botao } };
}

test('abrirMenu clica só quando o botão está visível e recolhido', async () => {
  for (const [visivel, expandido, cliques] of [[true, 'false', 1], [true, 'true', 0], [false, 'false', 0]]) {
    const { pagina, cliques: feitos } = menuFalso(visivel, expandido);
    await abrirMenu(pagina);
    assert.equal(feitos.length, cliques, `visível=${visivel} expandido=${expandido}`);
  }
});

test('cpfSintetico gera 11 dígitos com os verificadores corretos e distintos por base', () => {
  const verificador = (cpf, tamanho) => {
    const digitos = cpf.slice(0, tamanho).split('').map(Number);
    const soma = digitos.reduce((total, digito, indice) => total + digito * (tamanho + 1 - indice), 0);
    return ((soma * 10) % 11) % 10;
  };
  for (const base of [700000001, 700000002, 710000001]) {
    const cpf = cpfSintetico(base);
    assert.match(cpf, /^\d{11}$/);
    assert.equal(Number(cpf[9]), verificador(cpf, 9));
    assert.equal(Number(cpf[10]), verificador(cpf, 10));
  }
  assert.notEqual(cpfSintetico(700000001), cpfSintetico(700000002));
});

test('ehExterna: só o host do app é interno; data, blob e about não saem do navegador', () => {
  const base = 'http://127.0.0.1:8080';
  assert.equal(ehExterna('http://127.0.0.1:8080/static/projeto/mapa.js', base), false);
  assert.equal(ehExterna('blob:http://127.0.0.1:8080/abc', base), false);
  assert.equal(ehExterna('data:image/png;base64,AAAA', base), false);
  assert.equal(ehExterna('http://127.0.0.1:9090/x', base), true);
  assert.equal(ehExterna('https://tile.googleapis.com/v1/x', base), true);
  assert.equal(ehExterna('https://127.0.0.1.exemplo.test/', base), true);
});

test('noMapa monta a expressão com o mapa do elemento e o argumento em JSON; sem argumento vai null', async () => {
  const expressoes = [];
  const pagina = { evaluate: async (expressao) => expressoes.push(expressao) };
  await noMapa(pagina, (m) => m.loaded(), { a: 1 });
  await noMapa(pagina, (m) => m.loaded());
  assert.match(expressoes[0], /document\.querySelector\('\[data-mapa\]'\)\.mapa, \{"a":1\}\)$/);
  assert.match(expressoes[1], /\.mapa, null\)$/);
});

test('esperarOcioso espera o mapa carregado e parado; tocar clica no ponto projetado só depois disso', async () => {
  const passos = [];
  const pagina = {
    waitForFunction: async () => passos.push('ocioso'),
    locator: () => ({ scrollIntoViewIfNeeded: async () => passos.push('rolar') }),
    evaluate: async (_f, ponto) => { passos.push(`projetar ${ponto}`); return { x: 10, y: 20 }; },
    mouse: { click: async (x, y) => passos.push(`clicar ${x},${y}`) },
  };
  await tocar(pagina, [LON0, LAT0]);
  assert.deepEqual(passos, ['rolar', 'ocioso', `projetar ${LON0},${LAT0}`, 'clicar 10,20']);
});

test('tocar não clica quando a espera do mapa falha', async () => {
  const cliques = [];
  const pagina = {
    waitForFunction: async () => { throw new Error('tempo esgotado'); },
    locator: () => ({ scrollIntoViewIfNeeded: async () => {} }),
    mouse: { click: async () => cliques.push(1) },
  };
  await assert.rejects(tocar(pagina, [LON0, LAT0]), /tempo esgotado/);
  assert.deepEqual(cliques, []);
});

test('observarRequisicoesExternas registra só as externas e a lista devolvida enxerga as futuras', () => {
  let ouvinte;
  const pagina = { on: (evento, f) => { assert.equal(evento, 'request'); ouvinte = f; } };
  const externas = observarRequisicoesExternas(pagina, 'http://127.0.0.1:8080');
  const pedido = (url) => ({ url: () => url });
  ouvinte(pedido('http://127.0.0.1:8080/mapa'));
  assert.deepEqual(externas, []);
  ouvinte(pedido('https://externo.test/tile'));
  assert.deepEqual(externas, ['https://externo.test/tile']);
});
