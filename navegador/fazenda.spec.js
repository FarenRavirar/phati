'use strict';
// Página da fazenda (R11): nome, empresa, árvore em leitura, estado vazio de camadas; acesso negado por URL direta.
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel, abrirMenu } = require('./apoio.js');

const url = (empresa, fazenda) => `/empresa/${empresa}/fazenda/${fazenda}/`;

test('mostra nome, empresa, árvore de três níveis e a região de camadas', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(url(dados.empresa_a, dados.fazendas_a[0]));
  await expect(page.getByRole('heading', { name: 'Fazenda Inventada A1', level: 1 })).toBeVisible();
  await expect(page.getByText('Empresa Inventada A').first()).toBeVisible();
  for (const nome of ['Talhao 1', 'Gleba 1', 'Lote 1']) await expect(page.getByText(nome)).toBeVisible();
  // Com a flag do mapa ligada (job `navegador`) as camadas chegam e o "Sem camadas ainda." some; sem a flag ele fica (test_mapa.py).
  await expect(page.getByRole('heading', { name: 'Camadas', level: 2 })).toBeVisible();
  await abrirMenu(page);
  await expect(page.getByRole('link', { name: 'Fazendas', exact: true })).toHaveAttribute('aria-current', 'true');
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('regiões do mapa não se sobrepõem e os painéis recolhem (R22)', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(url(dados.empresa_a, dados.fazendas_a[0]));
  const nomes = ['mapa', 'camadas', 'consulta', 'ficha'];
  const caixas = [];
  for (const nome of nomes) {
    const regiao = page.locator(`.regiao-${nome}`);
    await expect(regiao).toBeVisible();
    caixas.push(await regiao.boundingBox());
  }
  for (let i = 0; i < caixas.length; i += 1) {
    for (let j = i + 1; j < caixas.length; j += 1) {
      const a = caixas[i];
      const b = caixas[j];
      const separadas = a.x + a.width <= b.x + 0.5 || b.x + b.width <= a.x + 0.5 || a.y + a.height <= b.y + 0.5 || b.y + b.height <= a.y + 0.5;
      expect(separadas, `${nomes[i]} e ${nomes[j]} se sobrepõem`).toBe(true);
    }
  }
  const camadas = page.locator('.regiao-camadas');
  const conteudo = camadas.locator('[data-camada]').first();
  await expect(conteudo).toBeVisible(); // as camadas sintéticas chegam com a flag do mapa
  await camadas.getByText('Mostrar ou ocultar camadas').click();
  await expect(conteudo).toBeHidden();
  await camadas.getByText('Mostrar ou ocultar camadas').click();
  await expect(conteudo).toBeVisible();
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
