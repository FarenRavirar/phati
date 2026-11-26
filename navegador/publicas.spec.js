'use strict';
// Telas públicas da spec 012 (R18, R5): 404, termos e privacidade sem texto e acesso negado por URL direta, nos dois
// tamanhos (1280×720 e 320×568, pelos projetos do `playwright.config.js`). Esqueci, redefinir e trocar senha têm arquivo
// próprio. Termos e privacidade COM texto não rodam aqui: exigem `PHATI_TERMOS_ARQUIVO`, que o job não define.
const { test, expect } = require('@playwright/test');
const { semRolagemHorizontal, acessivel } = require('./apoio.js');

test('rota inexistente: 404 com a marca AgriOn, sem rolagem horizontal, axe limpo e volta ao início', async ({ page }) => {
  const resposta = await page.goto('/rota-que-nao-existe');
  expect(resposta.status()).toBe(404);
  await expect(page).toHaveTitle('Página não encontrada · AgriOn');
  await expect(page.getByRole('heading', { name: 'Página não encontrada', level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Voltar ao início' })).toBeVisible();
  await semRolagemHorizontal(page);
  await acessivel(page);
});

for (const caminho of ['/termos', '/privacidade']) {
  test(`${caminho} sem texto do mantenedor: 404 com a página de erro, sem rolagem horizontal e axe limpo`, async ({ page }) => {
    const resposta = await page.goto(caminho);
    expect(resposta.status()).toBe(404);
    await expect(page.getByRole('heading', { name: 'Página não encontrada', level: 1 })).toBeVisible();
    await semRolagemHorizontal(page);
    await acessivel(page);
  });
}

test('deslogado que abre a casca por URL direta vai ao login, sem ver a tela', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/entrar/);
  await expect(page.getByRole('button', { name: 'Entrar' })).toBeVisible();
});

// Espaçamento das telas públicas (spec 012, R18): o protótipo põe 6 px entre título e descrição (`.ag-publica-caixa > div > p`)
// e o vão da caixa (24 px) entre descrição e formulário, sem margem de título nem de parágrafo por cima.
test('título, descrição e formulário seguem o vão do protótipo (6 px e 24 px)', async ({ page }) => {
  await page.goto('/entrar');
  const titulo = await page.locator('.ag-publica-caixa h1').boundingBox();
  const descricao = await page.locator('.ag-cabecalho-descricao').boundingBox();
  const formulario = await page.locator('.ag-publica-formulario').boundingBox();
  expect(Math.abs(descricao.y - (titulo.y + titulo.height) - 6)).toBeLessThan(1);
  expect(Math.abs(formulario.y - (descricao.y + descricao.height) - 24)).toBeLessThan(1);
});

// Aviso (feedback/Aviso.jsx): o texto é o último filho do corpo, então o aviso não pode sobrar embaixo dele além do padding.
test('aviso da 404: nenhuma sobra vertical abaixo do texto além do padding do aviso', async ({ page }) => {
  await page.goto('/rota-que-nao-existe');
  const aviso = page.locator('.ag-aviso');
  const caixaAviso = await aviso.boundingBox();
  const texto = await page.locator('.ag-aviso-texto').boundingBox();
  const preenchimento = await aviso.evaluate((el) => {
    const cs = getComputedStyle(el);
    return parseFloat(cs.paddingBottom) + parseFloat(cs.borderBottomWidth);
  });
  expect(Math.abs(caixaAviso.y + caixaAviso.height - (texto.y + texto.height) - preenchimento)).toBeLessThan(1);
});

// Links e vãos nas telas públicas (spec 012, R18). Termos com texto não rodam na suíte comum (sem PHATI_TERMOS_ARQUIVO):
// a marcação equivalente (parágrafo com link no meio) entra por page.evaluate numa tela pública, sem .skip.
const PARAGRAFO_COM_LINK = '<p data-sintetico>Texto sintético com <a href="/termos">link no meio do texto</a>, seguido de mais texto.</p>';

test('link dentro de texto corrido fica inline; o avulso (rodapé e "Esqueci a senha") tem alvo de 24 px', async ({ page }) => {
  await page.goto('/entrar');
  await page.locator('.ag-publica-caixa').evaluate((caixa, html) => caixa.insertAdjacentHTML('beforeend', html), PARAGRAFO_COM_LINK);
  await expect(page.locator('p[data-sintetico] a')).toHaveCSS('display', 'inline');
  // Sem termos (suíte comum) o rodapé não tem link: o avulso entra por page.evaluate. O rodapé é flex, então o link vira
  // item de flex (display calculado `flex`): o que vale é a altura do alvo.
  await page.locator('.ag-publica-pe').evaluate((pe) => pe.insertAdjacentHTML('beforeend', '<a href="/privacidade">Privacidade</a>'));
  for (const avulso of [page.locator('.ag-publica-pe a').first(), page.getByRole('link', { name: 'Esqueci a senha' })]) {
    expect((await avulso.boundingBox()).height).toBeGreaterThanOrEqual(24);
  }
});

test('vão entre parágrafos da caixa pública é o gap da caixa (24 px), sem margem de parágrafo somada', async ({ page }) => {
  await page.goto('/entrar');
  await page.locator('.ag-publica-caixa').evaluate((caixa, html) => caixa.insertAdjacentHTML('beforeend', html + html), PARAGRAFO_COM_LINK);
  const vao = await page.locator('p[data-sintetico]').evaluateAll((ps) => ps[1].getBoundingClientRect().top - ps[0].getBoundingClientRect().bottom);
  const gap = await page.locator('.ag-publica-caixa').evaluate((caixa) => Number.parseFloat(getComputedStyle(caixa).rowGap));
  expect(Math.abs(vao - gap)).toBeLessThan(1);
});

test('rodapé: "© AgriOn" alinhado ao centro do texto dos links', async ({ page }) => {
  await page.goto('/entrar');
  const centroDoTexto = (alvo) => alvo.evaluate((el) => {
    const intervalo = document.createRange();
    intervalo.selectNodeContents(el);
    const caixa = intervalo.getBoundingClientRect();
    return caixa.top + caixa.height / 2;
  });
  await page.locator('.ag-publica-pe').evaluate((pe) => pe.insertAdjacentHTML('beforeend', '<a href="/privacidade">Privacidade</a>'));
  const marca = await centroDoTexto(page.locator('.ag-publica-pe > span'));
  const link = await centroDoTexto(page.locator('.ag-publica-pe a').first());
  expect(Math.abs(marca - link)).toBeLessThan(1);
});
