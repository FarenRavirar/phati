'use strict';
// Redefinição de senha pelo link (R6): o segredo vem no fragmento e sai da barra de endereço.
const { test, expect } = require('@playwright/test');
const { semRolagemHorizontal, acessivel } = require('./apoio.js');

test('sem segredo mostra o link inválido e passa no axe', async ({ page }) => {
  await page.goto('/redefinir-senha');
  await expect(page.getByRole('alert')).toContainText('Este link não vale mais.');
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('com segredo mostra o formulário, tira o fragmento da barra e recusa senhas diferentes', async ({ page }) => {
  await page.goto('/redefinir-senha#segredo=valor-inventado');
  await expect(page.getByRole('button', { name: 'Salvar senha' })).toBeVisible();
  expect(new URL(page.url()).hash).toBe('');
  await acessivel(page);
  await page.getByLabel('Senha nova', { exact: true }).fill('Senha-Inventada-Um-2027');
  await page.getByLabel('Repita a senha', { exact: true }).fill('Senha-Inventada-Dois-2027');
  await page.getByRole('button', { name: 'Salvar senha' }).click();
  await expect(page.getByRole('alert')).toHaveText('As senhas não são iguais.');
});
