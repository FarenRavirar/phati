'use strict';
// Mapa de teste de layout (spec 004 R1, R3, R16; T1.7). Roda com PHATI_MAPA_TESTE_ATIVO=1 e PHATI_AMBIENTE=teste (job
// `navegador`). MapLibre real no Chromium, fundo neutro, sem rede externa e sem violação de política de conteúdo.
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel, observarRequisicoesExternas } = require('./apoio.js');

const url = (empresa, fazenda) => `/empresa/${empresa}/fazenda/${fazenda}/`;

async function abrirMapa(page, baseURL) {
  const externas = observarRequisicoesExternas(page, baseURL);
  const violacoes = [];
  page.on('console', (m) => { if (/Content Security Policy/i.test(m.text())) violacoes.push(m.text()); });
  await entrar(page, dados.administradora_a.cpf);
  const resposta = await page.goto(url(dados.empresa_a, dados.fazendas_a[0]));
  return { resposta, externas, violacoes };
}

test('o mapa abre com fundo neutro, sem violação de política e sem rede externa', async ({ page, baseURL }) => {
  const { resposta, externas, violacoes } = await abrirMapa(page, baseURL);
  const politica = resposta.headers()['content-security-policy'];
  expect(politica).toContain("img-src 'self' data: blob:");
  expect(politica).toContain("worker-src 'self' blob:");
  expect(politica).not.toContain('unsafe-eval');
  const mapa = page.locator('[data-mapa]');
  await expect(mapa).toHaveAttribute('data-mapa-pronto', 'sim');
  await expect(mapa).not.toHaveAttribute('data-mapa-erro', /.*/);
  await expect(mapa.locator('canvas.maplibregl-canvas')).toBeVisible();
  expect(violacoes, 'violação de CSP no console').toEqual([]);
  expect(externas, 'requisição para host que não é o do app').toEqual([]);
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('o detector de rede externa reprova quando uma requisição externa acontece', async ({ page, baseURL }) => {
  const externas = observarRequisicoesExternas(page, baseURL);
  await page.goto('http://externo.invalid/').catch(() => {});
  expect(externas).toEqual(['http://externo.invalid/']);
});

test('outras páginas seguem com a política da 002 (sem blob nem worker)', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  const resposta = await page.goto('/empresas/');
  const politica = resposta.headers()['content-security-policy'];
  expect(politica).not.toContain('blob:');
  expect(politica).not.toContain('worker-src');
});

test('sem acesso à fazenda, o mapa não existe por URL direta (404)', async ({ page }) => {
  await entrar(page, dados.sem_acesso.cpf);
  const resposta = await page.goto(url(dados.empresa_a, dados.fazendas_a[0]));
  expect(resposta.status()).toBe(404);
  await expect(page.locator('[data-mapa]')).toHaveCount(0);
});
