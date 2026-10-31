'use strict';
// Zoom de 200% e 400% (WCAG 1.4.10): em 1280×720, o zoom reduz a janela a 640×360 e 320×180 pixels CSS.
// A página não pode rolar na horizontal nem perder a ação principal; o contraste vem do axe (regra color-contrast).
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel, abrirMenu } = require('./apoio.js');

const ZOOMS = [
  ['200%', { width: 640, height: 360 }],
  ['400%', { width: 320, height: 180 }],
];
const MOTIVO = 'o projeto de celular já mede 320 px de largura';

for (const [rotulo, tela] of ZOOMS) {
  test(`login em ${rotulo}: sem rolagem horizontal, botão Entrar alcançável e axe limpo`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name.startsWith('celular'), MOTIVO);
    await page.setViewportSize(tela);
    await page.goto('/entrar');
    await expect(page.getByRole('button', { name: 'Entrar' })).toBeVisible();
    await semRolagemHorizontal(page);
    await acessivel(page);
  });

  test(`página da fazenda em ${rotulo}: sem rolagem horizontal e axe limpo`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name.startsWith('celular'), MOTIVO);
    await page.setViewportSize(tela);
    await entrar(page, dados.administradora_a.cpf);
    await page.goto(`/empresa/${dados.empresa_a}/fazenda/${dados.fazendas_a[0]}/`);
    await expect(page.getByRole('heading', { name: 'Fazenda Inventada A1', level: 1 })).toBeVisible();
    await abrirMenu(page);
    await semRolagemHorizontal(page);
    await acessivel(page);
  });
}
