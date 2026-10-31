'use strict';
// Troca de senha obrigatória (R5). A pessoa de troca é da turma do projeto e muda de estado uma vez só.
const { test, expect } = require('@playwright/test');
const { dados, turmaDe, entrar, semRolagemHorizontal, acessivel } = require('./apoio.js');

const CREDENCIAL_NOVA = 'Outra-Senha-Valida-2027';

test('senha temporária leva à troca, recusa a senha curta e aceita a válida', async ({ page }, testInfo) => {
  const { troca } = turmaDe(testInfo);
  await entrar(page, troca.cpf, troca.senha_temporaria);
  await expect(page).toHaveURL(/\/trocar-senha/);
  await expect(page.getByText('Sua senha é temporária.')).toBeVisible();
  await semRolagemHorizontal(page);
  await acessivel(page);

  const preencher = async (nova) => {
    await page.getByLabel('Senha atual', { exact: true }).fill(troca.senha_temporaria);
    await page.getByLabel('Senha nova', { exact: true }).fill(nova);
    await page.getByLabel('Repita a senha nova', { exact: true }).fill(nova);
    await page.getByRole('button', { name: 'Salvar senha' }).click();
  };
  await preencher('curta');
  await expect(page.getByRole('alert')).toBeVisible();

  await preencher(CREDENCIAL_NOVA);
  await expect(page).toHaveURL(/\/entrar/);
  await expect(page.getByText('Senha alterada.')).toBeVisible();

  await entrar(page, troca.cpf, CREDENCIAL_NOVA);
  await expect(page.getByRole('heading', { name: 'Início', level: 1 })).toBeVisible();
  expect(dados.senha).not.toBe(CREDENCIAL_NOVA);
});
