'use strict';
// Página de auditoria (005 R6, R7; A2): lista, filtra e pagina, nos dois tamanhos, com axe e sem rolagem horizontal; e o acesso
// negado por URL direta. Os eventos vêm do seed e das próprias visitas: cada primeira página grava `auditoria_consultada`,
// então a paginação se forma sem dado extra. Nenhum teste aqui grava dado de negócio; só leitura e visitas.
const { test, expect } = require('@playwright/test');
const { dados, turmaDe, entrar, semRolagemHorizontal, acessivel, abrirMenu } = require('./apoio.js');

const LIMITE_DA_PAGINA = 30; // `ParametrosDaAuditoria.limite` (padrão)
const TENTATIVAS_PARA_PAGINAR = 45; // teto: cada visita grava um evento, então o laço para bem antes disso
const MENSAGEM_DO_FILTRO = 'Filtro inválido: confira as datas, a ação, as pessoas e a empresa escolhidas.'; // texto de `auditoria_paginas.py`

async function conferirTela(pagina) {
  await semRolagemHorizontal(pagina);
  await acessivel(pagina);
}

function linhas(pagina) {
  return pagina.getByRole('table', { name: 'Eventos da auditoria' }).locator('tbody tr');
}

// Todo CPF do seed (dado inventado): a página não pode mostrar nenhum deles.
function cpfsDoSeed() {
  const pessoas = [
    dados.plataforma, dados.administradora_a, dados.administrador_b, dados.sem_acesso, dados.inexistente,
    ...Object.values(dados.turmas).flatMap((turma) => Object.values(turma)),
  ];
  return pessoas.map((pessoa) => pessoa.cpf);
}

test('Administrador de empresa vê a lista de eventos nos dois tamanhos', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/auditoria/');
  await expect(page.getByRole('heading', { name: 'Auditoria', level: 1 })).toBeVisible();
  await expect(linhas(page).first()).toBeVisible();
  await conferirTela(page);
});

test('filtro por período: data sem eventos mostra o estado vazio, e período com eventos mostra linhas', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/auditoria/');
  // Positivo: o período que cobre o seed devolve linhas, então o filtro de fato consulta.
  await page.getByLabel('Desde', { exact: true }).fill('2000-01-01');
  await page.getByRole('button', { name: 'Filtrar' }).click();
  await expect(page).toHaveURL(/desde=2000-01-01/);
  await expect(linhas(page).first()).toBeVisible();
  await conferirTela(page);

  // Negativo: período antes de qualquer evento do seed e das visitas.
  await page.getByLabel('Até', { exact: true }).fill('2000-01-02');
  await page.getByRole('button', { name: 'Filtrar' }).click();
  await expect(page.getByText('Nenhum evento neste período.')).toBeVisible();
  await expect(linhas(page)).toHaveCount(0);
  await conferirTela(page);
});

test('filtro por ação mostra só eventos dessa ação', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/auditoria/?acao=convite_criado');
  const select = page.getByLabel('Ação', { exact: true });
  await expect(select).toHaveValue('convite_criado');
  const rotulo = (await select.locator('option:checked').textContent()).trim();
  await expect(linhas(page).first()).toBeVisible();
  const textos = await linhas(page).evaluateAll((trs) => trs.map((tr) => tr.children[1].textContent.trim()));
  expect(textos.length).toBeGreaterThan(0);
  expect(textos.every((texto) => texto === rotulo)).toBe(true);
  await conferirTela(page);
});

test('filtro inválido mostra o aviso e não lista eventos', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/auditoria/?ate=2026-13-45');
  await expect(page.getByText(MENSAGEM_DO_FILTRO)).toBeVisible();
  await expect(linhas(page)).toHaveCount(0);
  await expect(page.getByText('Nenhum evento neste período.')).toHaveCount(0);
  await conferirTela(page);
});

test('paginação: Mais antigos traz a página seguinte e mantém o filtro', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  // Cada visita grava um `auditoria_consultada` para a empresa; o filtro por essa ação junta só esses eventos até passar de 30.
  const consulta = '/auditoria/?acao=auditoria_consultada';
  const maisAntigos = page.getByRole('link', { name: 'Mais antigos' });
  for (let tentativa = 0; tentativa < TENTATIVAS_PARA_PAGINAR; tentativa++) {
    await page.goto(consulta);
    if (await maisAntigos.isVisible()) break;
  }
  await expect(maisAntigos, `sem "Mais antigos" após ${TENTATIVAS_PARA_PAGINAR} visitas`).toBeVisible();
  await expect(linhas(page)).toHaveCount(LIMITE_DA_PAGINA);
  expect(await maisAntigos.getAttribute('href')).toMatch(/acao=auditoria_consultada.*depois=\d+|depois=\d+.*acao=auditoria_consultada/);
  await conferirTela(page);

  await maisAntigos.click();
  await expect(page).toHaveURL(/depois=\d+/);
  await expect(page).toHaveURL(/acao=auditoria_consultada/);
  const textos = await linhas(page).evaluateAll((trs) => trs.map((tr) => tr.children[1].textContent.trim()));
  expect(textos.length).toBeGreaterThan(0);
  expect(textos.length).toBeLessThanOrEqual(LIMITE_DA_PAGINA);
  const rotulo = (await page.getByLabel('Ação', { exact: true }).locator('option:checked').textContent()).trim();
  expect(textos.every((texto) => texto === rotulo)).toBe(true);
  await conferirTela(page);
});

test('a página não mostra CPF', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/auditoria/');
  await expect(linhas(page).first()).toBeVisible();
  const texto = await page.locator('body').innerText();
  for (const cpf of cpfsDoSeed()) expect(texto).not.toContain(cpf);
  expect(texto).not.toMatch(/\d{3}\.\d{3}\.\d{3}-\d{2}/);
});

test('filtro por quem agiu mostra só eventos dessa pessoa, e a página segue sem CPF', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/auditoria/');
  await expect(linhas(page).first()).toBeVisible();
  // Nome de quem aparece na primeira linha: dado do seed, não nome fixo. Coluna "Quem" é a terceira (índice 2).
  const nome = (await linhas(page).first().locator('td').nth(2).textContent()).trim();
  await page.getByLabel('Quem agiu', { exact: true }).selectOption({ label: nome });
  await page.getByRole('button', { name: 'Filtrar' }).click();
  await expect(page).toHaveURL(/pessoa_id=\d+/);
  await expect(linhas(page).first()).toBeVisible();
  const quem = await linhas(page).evaluateAll((trs) => trs.map((tr) => tr.children[2].textContent.trim()));
  expect(quem.length).toBeGreaterThan(0);
  expect(quem.every((texto) => texto === nome)).toBe(true);
  const texto = await page.locator('body').innerText();
  for (const cpf of cpfsDoSeed()) expect(texto).not.toContain(cpf);
  expect(texto).not.toMatch(/\d{3}\.\d{3}\.\d{3}-\d{2}/);
  await conferirTela(page);
});

test('item Auditoria no menu só aparece para quem tem a ação', async ({ page }, informacoes) => {
  const item = () => page.getByRole('link', { name: 'Auditoria', exact: true });
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  await abrirMenu(page);
  await expect(item()).toHaveCount(1); // controle positivo: o seletor acha o item quando ele existe

  await page.context().clearCookies();
  await entrar(page, turmaDe(informacoes).usuaria.cpf);
  await page.goto('/');
  await abrirMenu(page);
  await expect(page).not.toHaveURL(/\/entrar/); // o login deu certo, então a ausência do item não é falha de sessão
  await expect(item()).toHaveCount(0);

  await page.context().clearCookies();
  await entrar(page, dados.sem_acesso.cpf);
  await page.goto('/');
  await abrirMenu(page);
  await expect(item()).toHaveCount(0);
});

test('quem não lê a auditoria recebe 404 por URL direta, sem texto técnico', async ({ page }, informacoes) => {
  for (const cpf of [turmaDe(informacoes).usuaria.cpf, dados.sem_acesso.cpf]) {
    await page.context().clearCookies();
    await entrar(page, cpf);
    const resposta = await page.goto('/auditoria/');
    expect(resposta.status()).toBe(404);
    const resposta2 = await page.goto('/auditoria/?acao=convite_criado');
    expect(resposta2.status()).toBe(404);
    await expect(page.getByText('object (')).toHaveCount(0);
  }
});
