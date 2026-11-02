'use strict';
// Auxiliares dos testes de navegador, com páginas de mentira: nenhum navegador nem dados.json.
const test = require('node:test');
const assert = require('node:assert/strict');
const { turmaDe, semRolagemHorizontal, abrirMenu, cpfSintetico } = require('./apoio.js');

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
