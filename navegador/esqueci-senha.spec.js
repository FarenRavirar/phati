'use strict';
// Esqueci a senha (R6): a resposta é a mesma, exista o CPF ou não.
const { test, expect } = require('@playwright/test');
const { dados, semRolagemHorizontal, acessivel } = require('./apoio.js');

const NEUTRA = 'Se o CPF estiver cadastrado, enviamos um link de redefinição para o e-mail da conta.';

test('carrega, cabe na tela e passa no axe', async ({ page }) => {
  await page.goto('/esqueci-senha');
  await expect(page.getByRole('heading', { name: 'Esqueci a senha', level: 1 })).toBeVisible();
  await semRolagemHorizontal(page);
  await acessivel(page);
});

for (const [rotulo, cpf] of [['CPF cadastrado', dados.sem_acesso.cpf], ['CPF que ninguém tem', dados.inexistente.cpf]]) {
  test(`${rotulo} recebe a mesma mensagem neutra`, async ({ page }) => {
    await page.goto('/esqueci-senha');
    await page.getByLabel('CPF', { exact: true }).fill(cpf);
    await page.getByRole('button', { name: 'Enviar link' }).click();
    await expect(page.getByText(NEUTRA)).toBeVisible();
    await acessivel(page);
  });
}
