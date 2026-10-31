'use strict';
// Tela de entrada (R4, R8).
const { test, expect } = require('@playwright/test');
const { dados, turmaDe, entrar, semRolagemHorizontal, acessivel } = require('./apoio.js');

test('carrega, cabe na tela e passa no axe', async ({ page }) => {
  await page.goto('/entrar');
  await expect(page.getByRole('heading', { name: 'Entrar', level: 1 })).toBeVisible();
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('senha errada mostra o erro e não entra, igual para CPF inexistente e conta existente (R4)', async ({ page }, informacoesDoTeste) => {
  await entrar(page, dados.inexistente.cpf, 'senha-qualquer-errada');
  const mensagem = await page.getByRole('alert').innerText();
  await expect(page).toHaveURL(/\/entrar$/);
  // Conta existente, isolada só para errar a senha: a falha não bloqueia as pessoas dos outros testes.
  await entrar(page, turmaDe(informacoesDoTeste).errada.cpf, 'senha-qualquer-errada');
  await expect(page.getByRole('alert')).toHaveText(mensagem);
  await expect(page).toHaveURL(/\/entrar$/);
});

test('entra e cai no Início', async ({ page }) => {
  await entrar(page, dados.sem_acesso.cpf);
  await expect(page.getByRole('heading', { name: 'Início', level: 1 })).toBeVisible();
});

test('volta à página pedida depois do login (R8)', async ({ page }) => {
  await page.goto('/empresas/');
  await expect(page).toHaveURL(/\/entrar\?proximo=/);
  await page.getByLabel('CPF', { exact: true }).fill(dados.sem_acesso.cpf);
  await page.getByLabel('Senha', { exact: true }).fill(dados.senha);
  await page.getByRole('button', { name: 'Entrar' }).click();
  await expect(page).toHaveURL(/\/empresas\/$/);
});

test('destino externo é ignorado e a pessoa cai em / do próprio site', async ({ page }, informacoesDoTeste) => {
  await page.goto('/entrar?proximo=https://externo.exemplo/');
  await page.getByLabel('CPF', { exact: true }).fill(dados.sem_acesso.cpf);
  await page.getByLabel('Senha', { exact: true }).fill(dados.senha);
  await page.getByRole('button', { name: 'Entrar' }).click();
  await expect(page.getByRole('heading', { name: 'Início', level: 1 })).toBeVisible();
  // Origem e caminho exatos: qualquer outro host que terminasse em "/" não passa.
  expect(page.url()).toBe(new URL('/', informacoesDoTeste.project.use.baseURL).href);
});

test('aviso de sessão vencida aparece e passa no axe (R8)', async ({ page }) => {
  await page.goto('/entrar?expirou=1');
  await expect(page.getByText('Sua sessão expirou.')).toBeVisible();
  await acessivel(page);
});
