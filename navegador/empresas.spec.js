'use strict';
// Seletor de fazenda (R10): agrupado por empresa, busca no cliente, nada fora do escopo.
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel, abrirMenu } = require('./apoio.js');

test.beforeEach(async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/empresas/');
});

test('lista só as fazendas da empresa autorizada, marca o menu e passa no axe', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'Empresa Inventada A', level: 2 })).toBeVisible();
  await expect(page.locator('[data-fazenda]')).toHaveCount(3);
  await expect(page.getByText('Empresa Inventada B')).toHaveCount(0);
  await expect(page.getByText('Fazenda Inventada B1')).toHaveCount(0);
  await abrirMenu(page);
  await expect(page.getByRole('link', { name: 'Fazendas', exact: true })).toHaveAttribute('aria-current', 'page');
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('a busca filtra por nome e avisa quando nada casa', async ({ page }) => {
  const busca = page.getByLabel('Buscar fazenda');
  await busca.fill('A2');
  await expect(page.locator('[data-fazenda]:visible')).toHaveCount(1);
  await expect(page.getByRole('link', { name: 'Fazenda Inventada A2' })).toBeVisible();
  await busca.fill('zzz');
  await expect(page.getByText('Nenhuma fazenda encontrada.')).toBeVisible();
  await busca.fill('');
  await expect(page.locator('[data-fazenda]:visible')).toHaveCount(3);
});

test('uma fazenda leva à página dela', async ({ page }) => {
  await page.getByRole('link', { name: 'Fazenda Inventada A1' }).click();
  await expect(page).toHaveURL(new RegExp(`/empresa/${dados.empresa_a}/fazenda/${dados.fazendas_a[0]}/$`));
});
