'use strict';
// Início (R9): convites com Aceitar e Recusar, fazendas e o estado vazio. A usuária é da turma do projeto.
const { test, expect } = require('@playwright/test');
const { dados, turmaDe, entrar, semRolagemHorizontal, acessivel } = require('./apoio.js');

test('sem convite nem fazenda mostra "Sem pendências."', async ({ page }) => {
  await entrar(page, dados.sem_acesso.cpf);
  await expect(page.getByText('Sem pendências.')).toBeVisible();
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('convites e fazendas aparecem; aceitar libera a fazenda e recusar não', async ({ page }, informacoesDoTeste) => {
  await entrar(page, turmaDe(informacoesDoTeste).usuaria.cpf);
  await expect(page.getByRole('heading', { name: 'Convites' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Fazenda Inventada A1' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Fazenda Inventada B1' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Aceitar' })).toHaveCount(2);
  await semRolagemHorizontal(page);
  await acessivel(page);

  const convites = page.locator('.convite');
  const deB = convites.filter({ hasText: 'Empresa Inventada B' });
  const deA2 = convites.filter({ hasText: 'Empresa Inventada A' });
  await deB.getByRole('button', { name: 'Aceitar' }).click();
  await expect(page.getByRole('link', { name: 'Fazenda Inventada B1' })).toBeVisible();

  await deA2.getByRole('button', { name: 'Recusar' }).click();
  await expect(page.getByRole('heading', { name: 'Convites' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Fazenda Inventada A2' })).toHaveCount(0);
});
