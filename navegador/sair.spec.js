'use strict';
// Sair (R7): POST com CSRF, encerra a sessão e volta ao login.
const { test, expect } = require('@playwright/test');
const { dados, entrar } = require('./apoio.js');

test('Sair encerra a sessão: voltar ao Início exige entrar de novo', async ({ page }) => {
  await entrar(page, dados.sem_acesso.cpf);
  await expect(page.getByRole('heading', { name: 'Início', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Sair' }).click();
  await expect(page).toHaveURL(/\/entrar/);
  await page.goto('/');
  await expect(page).toHaveURL(/\/entrar\?proximo=/);
});
