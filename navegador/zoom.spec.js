'use strict';
// Zoom de 200% e 400% (WCAG 1.4.10): em 1280×720, o zoom reduz a janela a 640×360 e 320×180 pixels CSS.
// Só o projeto computador roda este arquivo (`testIgnore` do projeto celular em `playwright.config.js`: ele já mede 320 px).
// A página não pode rolar na horizontal nem perder a ação principal; o contraste vem do axe (regra color-contrast).
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel, abrirMenu } = require('./apoio.js');

const AMPLIACOES = [
  ['200%', { width: 640, height: 360 }],
  ['400%', { width: 320, height: 180 }],
];

for (const [rotulo, tela] of AMPLIACOES) {
  test(`login em ${rotulo}: sem rolagem horizontal, axe limpo e o botão Entrar entra`, async ({ page }) => {
    await page.setViewportSize(tela);
    await page.goto('/entrar');
    await expect(page.getByRole('button', { name: 'Entrar' })).toBeVisible();
    await semRolagemHorizontal(page);
    await acessivel(page);
    await page.getByLabel('CPF', { exact: true }).fill(dados.sem_acesso.cpf);
    await page.getByLabel('Senha', { exact: true }).fill(dados.senha);
    await page.getByRole('button', { name: 'Entrar' }).click();
    await expect(page.getByRole('heading', { name: 'Início', level: 1 })).toBeVisible();
  });

  test(`página da fazenda em ${rotulo}: sem rolagem horizontal e axe limpo`, async ({ page }) => {
    await page.setViewportSize(tela);
    await entrar(page, dados.administradora_a.cpf);
    await page.goto(`/empresa/${dados.empresa_a}/fazenda/${dados.fazendas_a[0]}/`);
    await expect(page.getByRole('heading', { name: 'Fazenda Inventada A1', level: 1 })).toBeVisible();
    await abrirMenu(page);
    await semRolagemHorizontal(page);
    await acessivel(page);
  });
}
