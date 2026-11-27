'use strict';
// Trava do auditor: configuração do axe que habilita zero regras (ou poucas) reprovaria nada e passaria sempre.
const test = require('node:test');
const assert = require('node:assert/strict');
const axe = require('axe-core');
const { ETIQUETAS, REGRAS_DE_TECLADO_DESLIGADAS, MINIMO_DE_REGRAS, TAMANHO_DO_ALVO, resumirViolacao } = require('./axe.js');

const habilitadas = () => axe.getRules(ETIQUETAS).map((regra) => regra.ruleId).filter((id) => !REGRAS_DE_TECLADO_DESLIGADAS.includes(id));

test('as regras habilitadas passam do piso e incluem target-size (WCAG 2.2 AA) e label', () => {
  const ids = habilitadas();
  assert.ok(ids.length >= MINIMO_DE_REGRAS, `só ${ids.length} regras habilitadas, piso ${MINIMO_DE_REGRAS}`);
  assert.ok(ids.includes('target-size'));
  assert.ok(ids.includes('label'));
});

// A exceção do menu aberto só vale se o nome bate com uma regra real: nome errado deixaria target-size ligada e falharia em silêncio.
test('a regra de target-size excetuada no menu aberto existe e está habilitada, e nome errado não está', () => {
  assert.equal(TAMANHO_DO_ALVO, 'target-size');
  assert.ok(habilitadas().includes(TAMANHO_DO_ALVO));
  assert.ok(!habilitadas().includes('target-sizes'));
});

test('toda regra de teclado desligada existe no axe e é da categoria de teclado', () => {
  const teclado = axe.getRules(['cat.keyboard']).map((regra) => regra.ruleId);
  for (const id of REGRAS_DE_TECLADO_DESLIGADAS) assert.ok(teclado.includes(id), `${id} não é regra de teclado do axe`);
});

// Forma do resultado do axe (violations[].nodes[].any[].data), copiada da doc do axe-core 4.14: aqui o teste só alimenta a função.
const noDeContraste = {
  target: ['.texto'],
  any: [{ id: 'color-contrast', data: { fgColor: '#777777', bgColor: '#888888', contrastRatio: 1.09, fontSize: '12.0pt (16px)', fontWeight: 'normal', messageKey: null, expectedContrastRatio: '4.5:1' } }],
  all: [],
  none: [],
};

test('violação sem nó devolve detalhes vazios e mantém regra, impacto e alvos', () => {
  assert.deepEqual(resumirViolacao({ id: 'label', impact: 'critical', nodes: [] }), { regra: 'label', impacto: 'critical', alvos: [], detalhes: [] });
});

test('contraste ruim leva fgColor, bgColor, contrastRatio e expectedContrastRatio por nó, sem os outros campos do data', () => {
  const resumo = resumirViolacao({ id: 'color-contrast', impact: 'serious', nodes: [noDeContraste] });
  assert.deepEqual(resumo.detalhes, [{ alvo: '.texto', fgColor: '#777777', bgColor: '#888888', contrastRatio: 1.09, expectedContrastRatio: '4.5:1' }]);
  assert.deepEqual(resumo.alvos, ['.texto']);
});

test('nó sem data de diagnóstico sai só com o alvo, sem chave com valor indefinido', () => {
  const semDado = { target: ['button'], any: [{ id: 'button-name', data: null }], all: [], none: [] };
  const resumo = resumirViolacao({ id: 'button-name', impact: 'critical', nodes: [semDado] });
  assert.deepEqual(resumo.detalhes, [{ alvo: 'button' }]);
});

test('dado de diagnóstico do check `all` ou `none` também entra quando o `any` não o tem', () => {
  const noComDadoEmAll = { target: ['p'], any: [], all: [{ id: 'color-contrast', data: { fgColor: '#fff', bgColor: '#eee', contrastRatio: 1.1 } }], none: [] };
  const resumo = resumirViolacao({ id: 'color-contrast', impact: 'serious', nodes: [noComDadoEmAll] });
  assert.deepEqual(resumo.detalhes, [{ alvo: 'p', fgColor: '#fff', bgColor: '#eee', contrastRatio: 1.1 }]);
});
