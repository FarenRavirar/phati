'use strict';
// Página da fazenda (R11): nome, empresa, árvore em leitura, estado vazio de camadas; acesso negado por URL direta.
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel, abrirMenu } = require('./apoio.js');

const url = (empresa, fazenda) => `/empresa/${empresa}/fazenda/${fazenda}/`;

test('mostra nome, empresa, árvore de três níveis e "Sem camadas ainda."', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(url(dados.empresa_a, dados.fazendas_a[0]));
  await expect(page.getByRole('heading', { name: 'Fazenda Inventada A1', level: 1 })).toBeVisible();
  await expect(page.getByText('Empresa Inventada A').first()).toBeVisible();
  for (const nome of ['Talhao 1', 'Gleba 1', 'Lote 1']) await expect(page.getByText(nome)).toBeVisible();
  await expect(page.getByText('Sem camadas ainda.')).toBeVisible();
  await abrirMenu(page);
  await expect(page.getByRole('link', { name: 'Fazendas', exact: true })).toHaveAttribute('aria-current', 'true');
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('fazenda de outra empresa dá 404 sem revelar nome (URL direta)', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  const resposta = await page.goto(url(dados.empresa_b, dados.fazenda_b));
  expect(resposta.status()).toBe(404);
  await expect(page.getByText('Inventada B')).toHaveCount(0);
});

test('pessoa sem acesso recebe 404 na fazenda existente (URL direta)', async ({ page }) => {
  await entrar(page, dados.sem_acesso.cpf);
  const resposta = await page.goto(url(dados.empresa_a, dados.fazendas_a[0]));
  expect(resposta.status()).toBe(404);
  await expect(page.getByText('Inventada A')).toHaveCount(0);
});
