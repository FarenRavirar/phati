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
