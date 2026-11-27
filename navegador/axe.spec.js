'use strict';
// O auditor de verdade (`violacoes`, com as etiquetas e as regras desligadas reais) tem de reprovar defeito de
// acessibilidade: sem isto, uma configuração errada passaria todas as telas em silêncio (achado do Sourcery, PR #22).
const { test, expect } = require('@playwright/test');
const { violacoes } = require('./axe.js');

test('campo sem rótulo é reprovado pelo auditor (regra label)', async ({ page }) => {
  await page.goto('/entrar');
  await page.evaluate(() => {
    const campo = document.createElement('input');
    campo.type = 'text';
    document.querySelector('form').append(campo);
  });
  const regras = (await violacoes(page)).map((violacao) => violacao.regra);
  expect(regras).toContain('label');
});

test('alvo de toque pequeno é reprovado pelo auditor (regra target-size, WCAG 2.2)', async ({ page }) => {
  await page.goto('/entrar');
  const medidas = await page.evaluate(() => {
    // Um alvo pequeno isolado passa (exceção de espaçamento do WCAG 2.5.8); dois colados reprovam.
    // O CSS do produto dá tamanho mínimo a botão nu (24x27 medido), então o tamanho é forçado com !important.
    const alvos = [];
    for (const esquerda of [0, 12]) {
      const botao = document.createElement('button');
      botao.textContent = 'x';
      for (const [propriedade, valor] of [['width', '10px'], ['height', '10px'], ['min-width', '0'], ['min-height', '0'], ['padding', '0'], ['position', 'absolute'], ['top', '0'], ['left', `${esquerda}px`]]) {
        botao.style.setProperty(propriedade, valor, 'important');
      }
      document.body.append(botao);
      alvos.push(botao);
    }
    return alvos.map((botao) => {
      const { width, height } = botao.getBoundingClientRect();
      return { largura: width, altura: height };
    });
  });
  // Controle: sem o tamanho medido abaixo de 24 px o teste não testa nada.
  for (const { largura, altura } of medidas) {
    expect(largura).toBeLessThan(24);
    expect(altura).toBeLessThan(24);
  }
  const regras = (await violacoes(page)).map((violacao) => violacao.regra);
  expect(regras).toContain('target-size');
});

// Página sem servidor (setContent): o axe real roda sobre o HTML dado. Limpa: nenhuma violação.
test('página limpa não tem violação pelo auditor', async ({ page }) => {
  await page.setContent('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Página limpa</title></head><body><main><h1>Título</h1><p>Texto com contraste de sobra.</p></main></body></html>');
  expect(await violacoes(page)).toEqual([]);
});

// Contraste ruim: o detalhe do nó leva as cores e a razão do axe, para a mensagem do expect mostrar o motivo.
test('texto de contraste ruim é reprovado com cores e razão no detalhe', async ({ page }) => {
  await page.setContent('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Contraste</title></head><body><main><h1>Título</h1><p style="color:#777;background:#888">texto cinza sobre cinza</p></main></body></html>');
  const contraste = (await violacoes(page)).find((violacao) => violacao.regra === 'color-contrast');
  expect(contraste).toBeDefined();
  expect(contraste.detalhes).toHaveLength(1);
  expect(contraste.detalhes[0]).toMatchObject({ alvo: expect.any(String), fgColor: expect.any(String), bgColor: expect.any(String), contrastRatio: expect.any(Number), expectedContrastRatio: expect.any(String) });
  expect(contraste.detalhes[0].contrastRatio).toBeLessThan(4.5);
});
