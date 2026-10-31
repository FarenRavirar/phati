// Executa o menu.js real contra um DOM mínimo (mesmo molde de scripts/redefinir-senha-pagina.test.js): recolher e expandir.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const CODIGO = fs.readFileSync(path.join(__dirname, 'menu.js'), 'utf8');

function abrir({ estreito, comElementos = true }) {
  const ouvintes = {};
  const midia = { matches: estreito, addEventListener: (_, f) => { ouvintes.mudanca = f; } };
  const botao = { hidden: true, atributos: {}, setAttribute(k, v) { this.atributos[k] = v; }, addEventListener: (_, f) => { ouvintes.clique = f; } };
  const menu = { hidden: false };
  const elementos = { 'menu-alternar': botao, 'menu-lateral': menu };
  const documento = { getElementById: (id) => (comElementos ? elementos[id] : null) };
  const janela = { matchMedia: () => midia };
  vm.runInNewContext(CODIGO, { document: documento, window: janela, String });
  return { botao, menu, midia, ouvintes };
}

test('largura estreita: menu começa recolhido, botão aparece e o clique expande e recolhe', () => {
  const { botao, menu, ouvintes } = abrir({ estreito: true });
  assert.equal(menu.hidden, true);
  assert.equal(botao.hidden, false);
  assert.equal(botao.atributos['aria-expanded'], 'false');
  ouvintes.clique();
  assert.equal(menu.hidden, false);
  assert.equal(botao.atributos['aria-expanded'], 'true');
  ouvintes.clique();
  assert.equal(menu.hidden, true);
});

test('largura ampla: menu sempre visível e botão escondido', () => {
  const { botao, menu, ouvintes } = abrir({ estreito: false });
  assert.equal(menu.hidden, false);
  assert.equal(botao.hidden, true);
  ouvintes.clique();
  assert.equal(menu.hidden, false);
});

test('ao alargar a janela com o menu recolhido, ele reaparece', () => {
  const { menu, midia, ouvintes } = abrir({ estreito: true });
  assert.equal(menu.hidden, true);
  midia.matches = false;
  ouvintes.mudanca();
  assert.equal(menu.hidden, false);
});

test('página sem o menu não quebra', () => {
  assert.doesNotThrow(() => abrir({ estreito: true, comElementos: false }));
});
