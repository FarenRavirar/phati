'use strict';
// Página da fazenda (R11): nome, empresa, árvore em leitura, estado vazio de camadas; acesso negado por URL direta.
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel, abrirMenu, caberNoBotao, TEXTO_LONGO } = require('./apoio.js');

const url = (empresa, fazenda) => `/empresa/${empresa}/fazenda/${fazenda}/`;

test('mostra nome, empresa, árvore de três níveis e a região de camadas', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(url(dados.empresa_a, dados.fazendas_a[0]));
  await expect(page.getByRole('heading', { name: 'Fazenda Inventada A1', level: 1 })).toBeVisible();
  // O nome da empresa fica no seletor de escopo da sidebar (fora de <main>); em 320 a sidebar é a gaveta, então abre antes.
  await abrirMenu(page);
  await expect(page.locator('.ag-escopo').getByText('Empresa Inventada A')).toBeVisible();
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
  // As camadas chegam depois da página e o painel cresce: medir as caixas antes disso dá layout de transição (intermitente na suíte inteira).
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-pronto', 'sim');
  await expect(page.locator('.regiao-camadas [data-camada]').first()).toBeVisible();
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
  await camadas.getByText('Mostrar ou ocultar camadas').click();
  await expect(conteudo).toBeHidden();
  await camadas.getByText('Mostrar ou ocultar camadas').click();
  await expect(conteudo).toBeVisible();
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('botão de resultado da consulta quebra texto longo e cabe no painel (regressão, nowrap do pacote)', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(url(dados.empresa_a, dados.fazendas_a[0]));
  const regiao = page.locator('.regiao-consulta');
  await expect(regiao).toBeVisible();
  // Mesma marcação que mapa.js monta para cada resultado (`ag-botao consulta-botao`); o texto longo é o caso que o painel precisa aguentar.
  await regiao.evaluate((r, textos) => {
    const lista = document.createElement('ul');
    lista.className = 'lista-consulta';
    for (const texto of textos) {
      const item = document.createElement('li');
      item.className = 'consulta-item';
      const b = document.createElement('button');
      b.className = 'ag-botao consulta-botao';
      b.type = 'button';
      b.dataset.variante = 'secundario';
      b.dataset.tamanho = 'md';
      b.textContent = texto;
      item.append(b);
      lista.append(item);
    }
    r.append(lista);
  }, ['Curto', TEXTO_LONGO]);
  // O botão de camada (`ag-botao botao-camada`, mapa.js) segue a mesma regra: mínimo de 44 px mesmo com o texto curto.
  await regiao.evaluate((r) => {
    const b = document.createElement('button');
    b.className = 'ag-botao botao-camada';
    b.type = 'button';
    b.dataset.variante = 'secundario';
    b.dataset.tamanho = 'md';
    b.textContent = 'Curta';
    r.append(b);
  });
  const botoes = regiao.locator('.consulta-botao');
  const curto = await caberNoBotao(botoes.nth(0));
  const longo = await caberNoBotao(botoes.nth(1));
  const camada = await caberNoBotao(regiao.locator('.botao-camada'));
  expect(camada.altura, 'botão de camada abaixo de 44 px').toBeGreaterThanOrEqual(44);
  expect(curto.altura, 'botão curto fica no mínimo de 44 px').toBeCloseTo(44, 0);
  expect(longo.altura, 'botão longo não fica abaixo de 44 px').toBeGreaterThanOrEqual(44);
  const painel = await regiao.boundingBox();
  const caixa = await botoes.nth(1).boundingBox();
  expect(caixa.width, 'botão longo passa da largura do painel').toBeLessThanOrEqual(painel.width + 0.5);
  await semRolagemHorizontal(page);
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
