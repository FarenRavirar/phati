'use strict';
// Auditoria de acessibilidade das telas: WCAG 2.2 AA, com `target-size` (tamanho do alvo de toque).
const AxeBuilder = require('@axe-core/playwright').default;

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

// Regras de teclado desligadas por id: a D062 deixou a navegação só por teclado fora do escopo da 002 (o foco
// visível continua exigido e vem do teste de CSS). Lista medida em axe-core 4.14.0: as regras da categoria
// `cat.keyboard` que as TAGS habilitam. Religar quando um requisito de teclado entrar na spec.
const REGRAS_DE_TECLADO_DESLIGADAS = ['bypass', 'frame-focusable-content', 'nested-interactive', 'scrollable-region-focusable'];

// Piso de regras habilitadas (70 das TAGS menos as 4 de teclado, em axe-core 4.14.0): atualizar o axe e perder regra reprova.
const MINIMO_DE_REGRAS = 66;

// Devolve as violações da página aberta; lista vazia é aprovação.
async function violacoes(pagina) {
  const resultado = await new AxeBuilder({ page: pagina })
    .withTags(TAGS)
    .disableRules(REGRAS_DE_TECLADO_DESLIGADAS)
    .analyze();
  return resultado.violations.map((v) => ({ regra: v.id, impacto: v.impact, alvos: v.nodes.map((n) => n.target.join(' ')) }));
}

module.exports = { violacoes, TAGS, REGRAS_DE_TECLADO_DESLIGADAS, MINIMO_DE_REGRAS };
