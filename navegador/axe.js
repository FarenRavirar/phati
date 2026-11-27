'use strict';
// Auditoria de acessibilidade das telas: WCAG 2.2 AA, com `target-size` (tamanho do alvo de toque).
const AxeBuilder = require('@axe-core/playwright').default;

const ETIQUETAS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

// Regras de teclado desligadas por id: a D062 deixou a navegação só por teclado fora do escopo da 002 (o foco
// visível continua exigido e vem do teste de CSS). Lista medida em axe-core 4.14.0: as regras da categoria
// `cat.keyboard` que as ETIQUETAS habilitam. Religar quando um requisito de teclado entrar na spec.
const REGRAS_DE_TECLADO_DESLIGADAS = ['bypass', 'frame-focusable-content', 'nested-interactive', 'scrollable-region-focusable'];

// Piso de regras habilitadas (70 das ETIQUETAS menos as 4 de teclado, em axe-core 4.14.0): atualizar o axe e perder regra reprova.
const MINIMO_DE_REGRAS = 66;

// Alvo coberto pelo menu aberto: o menu é conteúdo que a própria pessoa abriu, e o WCAG 2.2 (SC 2.5.8) não exige o
// tamanho do alvo enquanto ele está coberto por esse conteúdo (https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum,
// consultado em 2026-11-27: "does not apply to targets while they are obscured by content displayed as a result of a user
// interaction"). Os itens do próprio menu continuam sujeitos e são auditados à parte, com target-size (empresas.spec.js).
const TAMANHO_DO_ALVO = 'target-size';

// Campos do `data` do axe que explicam a falha (contraste traz as cores e a razão); fontSize, messageKey etc. ficam de fora para o diff caber.
const CAMPOS_DE_DIAGNOSTICO = ['fgColor', 'bgColor', 'contrastRatio', 'expectedContrastRatio'];

// Dado do axe de um nó: o primeiro check (`any`, `all` ou `none`) que traz algum campo de diagnóstico.
function detalhesDoNo(no) {
  const dados = [...no.any, ...no.all, ...no.none].map((check) => check.data ?? {}).find((d) => CAMPOS_DE_DIAGNOSTICO.some((campo) => campo in d)) ?? {};
  return Object.fromEntries(CAMPOS_DE_DIAGNOSTICO.filter((campo) => campo in dados).map((campo) => [campo, dados[campo]]));
}

// Forma de cada violação: `alvos` mantém o contrato antigo; `detalhes` (um por nó, com o alvo) leva o dado do axe para a mensagem do expect.
function resumirViolacao(violacao) {
  return {
    regra: violacao.id,
    impacto: violacao.impact,
    alvos: violacao.nodes.map((no) => no.target.join(' ')),
    detalhes: violacao.nodes.map((no) => ({ alvo: no.target.join(' '), ...detalhesDoNo(no) })),
  };
}

// Espera o fim das animações finitas em curso (CSS ou Web Animations; transição CSS aparece como CSSTransition).
// Sem a espera, o axe lê a cor no meio do fade-in e reprova texto certo (CI, pessoas.spec.js:64, diálogo agrion).
// Infinita não termina e pausada não tem `finished` que dispare: ficam de fora, e a página é julgada como está.
// Repete até não sobrar animação finita, para cobrir a que começa logo depois da primeira rodada.
async function esperarAnimacoesFinitas(pagina) {
  await pagina.evaluate(async () => {
    const emCurso = () => document.getAnimations().filter((animacao) => ['running', 'pending'].includes(animacao.playState) && animacao.effect?.getComputedTiming().iterations !== Infinity);
    for (let animacoes = emCurso(); animacoes.length; animacoes = emCurso()) {
      await Promise.allSettled(animacoes.map((animacao) => animacao.finished));
    }
  });
}

// Devolve as violações da página aberta; lista vazia é aprovação. `desligar`: regras extras desligadas nesta chamada.
// `dentroDe`: seletor CSS; audita só esse trecho (com todas as regras, inclusive target-size).
async function violacoes(pagina, { desligar = [], dentroDe } = {}) {
  let auditoria = new AxeBuilder({ page: pagina })
    .withTags(ETIQUETAS)
    .disableRules([...REGRAS_DE_TECLADO_DESLIGADAS, ...desligar]);
  if (dentroDe) auditoria = auditoria.include(dentroDe);
  await esperarAnimacoesFinitas(pagina);
  const resultado = await auditoria.analyze();
  return resultado.violations.map(resumirViolacao);
}

module.exports = { violacoes, resumirViolacao, ETIQUETAS, REGRAS_DE_TECLADO_DESLIGADAS, MINIMO_DE_REGRAS, TAMANHO_DO_ALVO };
