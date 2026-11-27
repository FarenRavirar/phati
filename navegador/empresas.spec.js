'use strict';
// Tela Fazendas (`/empresas/`, R20, Q17) e página da empresa (`/empresa/<id>/`, Q24): só as fazendas que a pessoa vê, busca e filtro por link.
// A linha inteira leva ao link da primeira célula (R37, JS de agrion-componentes.js). Dados do popular_sintetico: sem empresa arquivada.
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel, acessivelComMenuAberto, abrirMenu } = require('./apoio.js');

test.beforeEach(async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/empresas/');
});

test('lista só as fazendas autorizadas, marca o menu e passa no axe', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'Fazendas', level: 1 })).toBeVisible();
  await expect(page.locator('.ag-tabela tbody tr')).toHaveCount(3);
  await expect(page.getByText('Empresa Inventada B')).toHaveCount(0);
  await expect(page.getByText('Fazenda Inventada B1')).toHaveCount(0);
  await abrirMenu(page);
  await expect(page.getByRole('link', { name: 'Fazendas', exact: true })).toHaveAttribute('aria-current', 'page');
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('a busca vai ao servidor e avisa quando nada casa', async ({ page }) => {
  const busca = page.getByRole('searchbox', { name: 'Buscar fazenda' });
  await busca.fill('A2');
  await busca.press('Enter');
  await expect(page).toHaveURL(/busca=A2/);
  await expect(page.locator('.ag-tabela tbody tr')).toHaveCount(1);
  await expect(page.getByRole('link', { name: 'Fazenda Inventada A2' })).toBeVisible();
  await page.getByRole('searchbox', { name: 'Buscar fazenda' }).fill('zzz');
  await page.getByRole('searchbox', { name: 'Buscar fazenda' }).press('Enter');
  await expect(page.getByText('Nenhuma fazenda encontrada')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Limpar filtros' })).toBeVisible();
});

test('o Segmentado de situação marca a opção ativa e filtra por link', async ({ page }) => {
  const grupo = page.getByRole('group', { name: 'Filtrar fazendas' });
  await expect(grupo.getByRole('link', { name: 'Todas' })).toHaveAttribute('aria-current', 'true');
  await grupo.getByRole('link', { name: 'Ativas' }).click();
  await expect(page).toHaveURL(/situacao=ativas/);
  await expect(page.getByRole('group', { name: 'Filtrar fazendas' }).getByRole('link', { name: 'Ativas' })).toHaveAttribute('aria-current', 'true');
});

test('uma fazenda leva à página dela', async ({ page }) => {
  await page.getByRole('link', { name: 'Fazenda Inventada A1' }).click();
  await expect(page).toHaveURL(new RegExp(`/empresa/${dados.empresa_a}/fazenda/${dados.fazendas_a[0]}/$`));
});

test('clicar em qualquer célula da linha leva à fazenda, pelo link da primeira célula', async ({ page }) => {
  await page.locator('.ag-tabela tbody tr').first().locator('td').nth(2).click();
  await expect(page).toHaveURL(new RegExp(`/empresa/${dados.empresa_a}/fazenda/(${dados.fazendas_a.join('|')})/$`));
});

test('Abrir empresa do seletor leva à página da empresa, filtrada por ela (Q24)', async ({ page }) => {
  await abrirMenu(page);
  await page.getByRole('button', { name: 'Trocar empresa ou fazenda' }).click();
  await page.getByRole('link', { name: 'Abrir empresa' }).click();
  await expect(page).toHaveURL(new RegExp(`/empresa/${dados.empresa_a}/$`));
  await expect(page.getByRole('heading', { name: 'Empresa Inventada A', level: 1 })).toBeVisible();
  await expect(page.locator('.ag-tabela tbody tr')).toHaveCount(3);
  await expect(page.getByText('Fazenda Inventada B1')).toHaveCount(0);
  await acessivel(page);
});

test('a página da empresa mantém Fazendas no menu e tem Mais ações, Exportar e Nova fazenda', async ({ page }) => {
  await page.goto(`/empresa/${dados.empresa_a}/`);
  await abrirMenu(page);
  await expect(page.getByRole('link', { name: 'Fazendas', exact: true })).toHaveAttribute('aria-current', 'true');
  await expect(page.getByRole('link', { name: 'Exportar' })).toHaveAttribute('href', new RegExp(`/fazendas\\.csv\\?empresa=${dados.empresa_a}`));
  const lista = page.locator('.ag-mais-acoes-lista');
  await expect(lista).toBeHidden();
  // Em 320 o menu lateral aberto cobre a página e o botão Menu não fecha: recarrega a mesma tela (menu fechado).
  await page.goto(`/empresa/${dados.empresa_a}/`);
  await acessivel(page);
  await page.locator('summary[aria-label="Mais ações"]').click();
  for (const rotulo of ['Cadastrar fazenda', 'Pessoas', 'Cargos']) {
    await expect(lista.getByRole('link', { name: rotulo, exact: true })).toBeVisible();
  }
  await semRolagemHorizontal(page);
  // Menu aberto: o botão do segmentado fica coberto pela lista, e WCAG 2.2 SC 2.5.8 não exige o alvo nessa cobertura
  // (https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum). O auxiliar confere a página sem target-size e o
  // menu com target-size, nos seus itens.
  await acessivelComMenuAberto(page);
});

// Regressão da regra `:where(.ag-mais-acoes:not([open])) > .ag-mais-acoes-lista { display: none }` (agrion-proprio.css): fechado, a lista tem display none; aberto, aparece.
// Sem axe de propósito: o teste é da regra, não do layout (o axe do menu aberto está em outro teste).
test('regra do menu Mais ações: fechado, a lista tem display none; aberto, aparece', async ({ page }) => {
  await page.goto(`/empresa/${dados.empresa_a}/`);
  const lista = page.locator('.ag-mais-acoes-lista');
  await expect(lista).toHaveCSS('display', 'none');
  await page.locator('summary[aria-label="Mais ações"]').click();
  await expect(lista.getByRole('link', { name: 'Pessoas', exact: true })).toBeVisible();
});

test('empresa sem acesso dá 404 por URL direta e não mostra Mais ações', async ({ page }) => {
  const resposta = await page.goto(`/empresa/${dados.empresa_b}/`);
  expect(resposta.status()).toBe(404);
  await expect(page.locator('summary[aria-label="Mais ações"]')).toHaveCount(0);
  await expect(page.getByText('Empresa Inventada B')).toHaveCount(0);
});

test('Exportar da página da empresa baixa o CSV só das fazendas dela', async ({ page }) => {
  await page.goto(`/empresa/${dados.empresa_a}/`);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('link', { name: 'Exportar' }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.csv$/);
});
