'use strict';
// Página da fazenda com o mapa desligado, que é o padrão de produção (spec 004 R1, R21; T5.3, achado do Qodo na PR #35).
// Roda à parte, com o servidor subido com PHATI_MAPA_TESTE_ATIVO=0 (`PHATI_PROVA_MAPA_DESLIGADO=1`, ver `playwright.config.js`).
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel } = require('./apoio.js');

const url = (empresa, fazenda) => `/empresa/${empresa}/fazenda/${fazenda}/`;

test('sem a flag a fazenda abre sem mapa, sem MapLibre e com o aviso de região vazia', async ({ page }) => {
  const pedidos = [];
  page.on('request', (r) => pedidos.push(r.url()));
  await entrar(page, dados.administradora_a.cpf);
  const resposta = await page.goto(url(dados.empresa_a, dados.fazendas_a[0]));
  expect(resposta.status()).toBe(200);
  await expect(page.getByRole('heading', { name: 'Fazenda Inventada A1', level: 1 })).toBeVisible();
  await expect(page.getByText('O mapa aparece quando a fazenda tiver camadas.')).toBeVisible();
  await expect(page.locator('[data-mapa]')).toHaveCount(0);
  await expect(page.locator('.maplibregl-canvas')).toHaveCount(0);
  const politica = resposta.headers()['content-security-policy'];
  expect(politica).not.toContain('blob:');
  expect(politica).not.toContain('worker-src');
  await semRolagemHorizontal(page);
  await acessivel(page);
  // Depois dos auxiliares: eles também mexem na página, e nenhuma requisição de mapa pode ter saído durante eles (CodeRabbit, PR #49).
  expect(pedidos.filter((u) => /maplibre|projeto\/mapa\.js|camadas\.geojson/.test(u))).toEqual([]);
});

test('sem a flag o acesso negado segue negado e sem mapa', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  const resposta = await page.goto(url(dados.empresa_b, dados.fazenda_b));
  expect(resposta.status()).toBe(404);
  await expect(page.locator('[data-mapa]')).toHaveCount(0);
});
