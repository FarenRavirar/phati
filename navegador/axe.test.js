'use strict';
// Trava do auditor: configuração do axe que habilita zero regras (ou poucas) reprovaria nada e passaria sempre.
const test = require('node:test');
const assert = require('node:assert/strict');
const axe = require('axe-core');
const { ETIQUETAS, REGRAS_DE_TECLADO_DESLIGADAS, MINIMO_DE_REGRAS } = require('./axe.js');

const habilitadas = () => axe.getRules(ETIQUETAS).map((regra) => regra.ruleId).filter((id) => !REGRAS_DE_TECLADO_DESLIGADAS.includes(id));

test('as regras habilitadas passam do piso e incluem target-size (WCAG 2.2 AA) e label', () => {
  const ids = habilitadas();
  assert.ok(ids.length >= MINIMO_DE_REGRAS, `só ${ids.length} regras habilitadas, piso ${MINIMO_DE_REGRAS}`);
  assert.ok(ids.includes('target-size'));
  assert.ok(ids.includes('label'));
});

test('toda regra de teclado desligada existe no axe e é da categoria de teclado', () => {
  const teclado = axe.getRules(['cat.keyboard']).map((regra) => regra.ruleId);
  for (const id of REGRAS_DE_TECLADO_DESLIGADAS) assert.ok(teclado.includes(id), `${id} não é regra de teclado do axe`);
});

test('etiqueta inexistente habilita zero regras, abaixo do piso (o que a trava barra)', () => {
  assert.equal(axe.getRules(['wcag99zz']).length, 0);
  assert.ok(0 < MINIMO_DE_REGRAS);
});
