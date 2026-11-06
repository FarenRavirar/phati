'use strict';
// Monitor de uso do Google (spec 004b R13, R14, A10) e páginas de termos (R15, A11) na casca real. O servidor do job sobe
// sem credencial do Cloud Monitoring, então a contagem aparece como "não medido": ausente nunca vira zero.
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel } = require('./apoio.js');

const MONITOR = '/monitor-google';

test('a plataforma vê as duas janelas com total, renovação e origem; sem contagem diz "não medido"', async ({ page }) => {
  await entrar(page, dados.plataforma.cpf);
  await page.goto(MONITOR);
  await expect(page.getByRole('heading', { name: 'Uso do Google', level: 1 })).toBeVisible();
  const linhas = page.locator('table.tabela tbody tr');
  await expect(linhas).toHaveCount(2);
  await expect(linhas.nth(0)).toContainText('Diária (cota do projeto)');
  await expect(linhas.nth(0)).toContainText('15.000');
  await expect(linhas.nth(1)).toContainText('Mensal (franquia grátis)');
  await expect(linhas.nth(1)).toContainText('100.000');
  for (const linha of [linhas.nth(0), linhas.nth(1)]) {
    await expect(linha).toContainText('horário do Pacífico');
    await expect(linha.locator('td').nth(1), 'usados').toHaveText('não medido');
    await expect(linha.locator('td').nth(4), 'porcentagem').toHaveText('não medido');
    await expect(linha.locator('td').nth(5), 'origem').toHaveText('não medido');
  }
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('administrador de empresa, sem acesso e deslogado não abrem o monitor por URL direta', async ({ page }) => {
  expect((await page.goto(MONITOR)).url(), 'deslogado vai ao login').toContain('/entrar');
  await entrar(page, dados.administradora_a.cpf);
  expect((await page.goto(MONITOR)).status()).toBe(404);
  await page.context().clearCookies();
  await entrar(page, dados.sem_acesso.cpf);
  expect((await page.goto(MONITOR)).status()).toBe(404);
});

test('sem o texto do mantenedor, termos e privacidade dão 404 e o rodapé não os linka', async ({ page }) => {
  for (const caminho of ['/termos', '/privacidade']) expect((await page.goto(caminho)).status(), caminho).toBe(404);
  await page.goto('/entrar');
  await expect(page.getByRole('link', { name: 'Termos de uso' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Política de privacidade' })).toHaveCount(0);
});
