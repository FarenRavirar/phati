'use strict';
// Auxiliares dos testes de navegador, com páginas de mentira: nenhum navegador nem dados.json.
const test = require('node:test');
const assert = require('node:assert/strict');
const { turmaDe, semRolagemHorizontal, abrirMenu } = require('./apoio.js');

const dados = { turmas: { desktop: { nome: 'd' }, celular: { nome: 'c' } } };
const projeto = (nome) => ({ project: { name: nome } });

test('cada projeto recebe a própria turma', () => {
  assert.equal(turmaDe(projeto('desktop-1280x720'), dados).nome, 'd');
  assert.equal(turmaDe(projeto('celular-320x568'), dados).nome, 'c');
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
