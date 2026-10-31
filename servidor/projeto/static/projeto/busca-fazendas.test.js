// Executa o busca-fazendas.js real contra um DOM mínimo (molde de menu.test.js): filtro, acento, grupo e estado vazio.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const CODIGO = fs.readFileSync(path.join(__dirname, 'busca-fazendas.js'), 'utf8');

function item(texto) {
  return { textContent: texto, hidden: false };
}

function grupo(...itens) {
  return { hidden: false, querySelectorAll: () => itens };
}

function abrir(grupos, { comRaiz = true } = {}) {
  const ouvintes = {};
  const campo = { value: '', addEventListener: (_, f) => { ouvintes.entrada = f; } };
  const vazio = { hidden: true };
  const consultas = { '[data-busca-campo]': campo, '[data-busca-vazia]': vazio };
  const raiz = {
    querySelector: (seletor) => consultas[seletor],
    querySelectorAll: () => grupos,
  };
  const documento = { querySelector: () => (comRaiz ? raiz : null) };
  vm.runInNewContext(CODIGO, { document: documento, Array });
  return { campo, vazio, ouvintes };
}

test('o termo esconde as fazendas que não casam e o grupo que ficou sem nenhuma', () => {
  const [a, b, c] = [item('Sede Norte'), item('Sede Sul'), item('Retiro')];
  const grupoUm = grupo(a, b);
  const grupoDois = grupo(c);
  const { campo, vazio, ouvintes } = abrir([grupoUm, grupoDois]);
  campo.value = 'norte';
  ouvintes.entrada();
  assert.deepEqual([a.hidden, b.hidden, c.hidden], [false, true, true]);
  assert.deepEqual([grupoUm.hidden, grupoDois.hidden], [false, true]);
  assert.equal(vazio.hidden, true);
});

test('ignora caixa e acento do nome e do termo', () => {
  const a = item('Fazenda São João');
  const { campo, ouvintes } = abrir([grupo(a)]);
  campo.value = 'SAO joao';
  ouvintes.entrada();
  assert.equal(a.hidden, false);
});

test('sem resultado mostra o aviso; campo vazio mostra tudo de novo', () => {
  const a = item('Sede');
  const g = grupo(a);
  const { campo, vazio, ouvintes } = abrir([g]);
  campo.value = 'zzz';
  ouvintes.entrada();
  assert.deepEqual([a.hidden, g.hidden, vazio.hidden], [true, true, false]);
  campo.value = '';
  ouvintes.entrada();
  assert.deepEqual([a.hidden, g.hidden, vazio.hidden], [false, false, true]);
});

test('sem a raiz da busca na página o script não faz nada', () => {
  const { ouvintes } = abrir([], { comRaiz: false });
  assert.equal(ouvintes.entrada, undefined);
});
