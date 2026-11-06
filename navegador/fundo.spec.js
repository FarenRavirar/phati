'use strict';
// Fundo próprio e ortofoto do pacote (spec 004b R7, R8, R11; A7). Roda no job `navegador` comum (mapa ligado, sem a flag do Google) na
// segunda fazenda da empresa A, que o `popular_sintetico` entrega com o pacote de referência. A primeira e a terceira seguem sem pacote.
// MapLibre real e PMTiles servido pelo app por `Range`; nenhuma requisição sai do host do app.
const { test, expect } = require('@playwright/test');
const { dados, entrar, turmaDe, semRolagemHorizontal, acessivel, observarRequisicoesExternas } = require('./apoio.js');

const [LON0, LAT0] = [-48.30, -10.75];
const P1 = [LON0, LAT0];
const comPacote = () => `/empresa/${dados.empresa_a}/fazenda/${dados.fazendas_a[1]}/`;
const semPacote = () => `/empresa/${dados.empresa_a}/fazenda/${dados.fazendas_a[0]}/`;
const arquivo = (nome) => `/empresa/${dados.empresa_a}/fazenda/${dados.fazendas_a[1]}/pacote/arquivo/${nome}?versao=1`;

const noMapa = (page, funcao, argumento) => page.evaluate(`(${funcao})(document.querySelector('[data-mapa]').mapa, ${JSON.stringify(argumento ?? null)})`);

async function esperarOcioso(page) {
  await page.waitForFunction(() => {
    const mapa = document.querySelector('[data-mapa]').mapa;
    return mapa && mapa.loaded() && !mapa.isMoving();
  });
}

async function abrir(page, baseURL, destino = comPacote()) {
  const externas = observarRequisicoesExternas(page, baseURL);
  const violacoes = [];
  const pacote = [];
  page.on('console', (m) => { if (/Content Security Policy/i.test(m.text())) violacoes.push(m.text()); });
  page.on('response', (r) => { if (r.url().includes('/pacote/arquivo/')) pacote.push({ nome: new URL(r.url()).pathname.split('/').pop(), status: r.status() }); });
  await entrar(page, dados.administradora_a.cpf);
  const resposta = await page.goto(destino);
  return { resposta, externas, violacoes, pacote };
}

async function mapaPronto(page, ativo = 'proprio') {
  const mapa = page.locator('[data-mapa]');
  await expect(mapa).toHaveAttribute('data-mapa-pronto', 'sim');
  await expect(mapa).toHaveAttribute('data-fundo-ativo', ativo);
  await esperarOcioso(page);
  return mapa;
}

async function tocar(page, [lon, lat]) {
  await page.locator('[data-mapa]').scrollIntoViewIfNeeded();
  await esperarOcioso(page);
  const alvo = await page.evaluate(([x, y]) => {
    const elemento = document.querySelector('[data-mapa]');
    const ponto = elemento.mapa.project([x, y]);
    const caixa = elemento.getBoundingClientRect();
    return { x: caixa.left + ponto.x, y: caixa.top + ponto.y };
  }, [lon, lat]);
  await page.mouse.click(alvo.x, alvo.y);
}

test('o fundo próprio desenha a partir do PMTiles servido por Range, com a atribuição OpenStreetMap à vista', async ({ page, baseURL }) => {
  const { resposta, externas, violacoes, pacote } = await abrir(page, baseURL);
  const politica = resposta.headers()['content-security-policy'];
  expect(politica).not.toContain('unsafe-eval');
  await mapaPronto(page);
  await page.waitForFunction(() => document.querySelector('[data-mapa]').mapa.isSourceLoaded('fundo'));
  // O desenho é conferido nas feições renderizadas: a terra e a estrada do pacote sintético estão no quadro.
  const renderizadas = await noMapa(page, (m) => ({
    terra: m.queryRenderedFeatures({ layers: ['fundo-terra'] }).length,
    estrada: m.queryRenderedFeatures({ layers: ['fundo-estrada'] }).length,
  }));
  expect(renderizadas.terra, 'terra do pacote não desenhada').toBeGreaterThan(0);
  expect(renderizadas.estrada, 'estrada do pacote não desenhada').toBeGreaterThan(0);
  const doFundo = pacote.filter((p) => p.nome === 'fundo.pmtiles');
  expect(doFundo.length).toBeGreaterThan(0);
  expect(doFundo.every((p) => p.status === 206), `resposta que não é 206: ${JSON.stringify(doFundo)}`).toBe(true);
  const atribuicao = page.locator('[data-atribuicao-aberta]');
  await expect(atribuicao).toBeVisible();
  await expect(atribuicao).toHaveText('© OpenStreetMap contributors');
  // Nenhum controle do mapa cobre a atribuição: ela fica abaixo do mapa e o elemento no ponto dela é ela mesma.
  await atribuicao.evaluate((el) => el.scrollIntoView({ block: 'center' }));
  const livre = await atribuicao.evaluate((el) => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x + 2, r.y + r.height / 2)); });
  expect(livre, 'algum elemento cobre a atribuição').toBe(true);
  expect(violacoes, 'violação de CSP no console').toEqual([]);
  expect(externas, 'requisição para host que não é o do app').toEqual([]);
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('a ortofoto é uma camada desligada com a data de captura, que liga, muda de opacidade e de ordem como qualquer outra', async ({ page, baseURL }) => {
  const { pacote, externas } = await abrir(page, baseURL);
  await mapaPronto(page);
  const item = page.locator('[data-camada="camada-ortofoto"]');
  await expect(item).toContainText('Ortofoto (captura em 15/01/2026)'); // a data de captura aparece na tela
  const caixa = item.getByRole('checkbox');
  await expect(caixa).not.toBeChecked();
  expect(await noMapa(page, (m) => m.getLayoutProperty('camada-ortofoto', 'visibility'))).toBe('none');
  // Medido (2026-11-06): com a camada desligada o motor ainda lê o cabeçalho do PMTiles (um Range), mas nenhum tile.

  await caixa.check();
  expect(await noMapa(page, (m) => m.getLayoutProperty('camada-ortofoto', 'visibility'))).toBe('visible');
  await noMapa(page, (m) => m.jumpTo({ center: [-48.30, -10.75], zoom: 16 })); // a ortofoto de referência vai de z14 a z17
  await page.waitForFunction(() => document.querySelector('[data-mapa]').mapa.isSourceLoaded('ortofoto'));
  await expect.poll(() => pacote.filter((p) => p.nome === 'ortofoto.pmtiles' && p.status === 206).length).toBeGreaterThan(0);

  await item.getByRole('slider').fill('50');
  expect(await noMapa(page, (m) => m.getPaintProperty('camada-ortofoto', 'raster-opacity'))).toBe(0.5);

  // Ordem: começa como a mais baixa do produto; subir a leva por cima de uma camada vetorial.
  const posicao = () => noMapa(page, (m) => { const ids = m.getStyle().layers.map((l) => l.id); return ids.indexOf('camada-ortofoto') - ids.indexOf('camada-c-contorno'); });
  expect(await posicao(), 'a ortofoto não começa abaixo das camadas').toBeLessThan(0);
  await item.getByRole('button', { name: /^Subir Ortofoto/ }).click();
  expect(await posicao(), 'subir não levou a ortofoto acima da camada mais baixa').toBeGreaterThan(0);

  // A consulta lista só feição vetorial: sem valor de raster, a ortofoto nunca aparece nela.
  await noMapa(page, (m) => m.jumpTo({ center: [-48.30, -10.75], zoom: 12 }));
  await tocar(page, P1);
  const consulta = page.locator('[data-lista-consulta] li button');
  await expect(consulta.first()).toBeVisible();
  for (const texto of await consulta.allTextContents()) expect(texto).not.toMatch(/ortofoto/i);
  expect(externas).toEqual([]);
  await acessivel(page);
});

test('a fazenda sem pacote abre no fundo neutro, sem atributo, sem atribuição e sem pedir arquivo de pacote', async ({ page, baseURL }) => {
  const { pacote } = await abrir(page, baseURL, semPacote());
  const mapa = await mapaPronto(page, 'neutro');
  await expect(mapa).not.toHaveAttribute('data-pacote-fundo', /.*/);
  await expect(page.locator('[data-atribuicao-aberta]')).toHaveCount(0);
  await expect(page.locator('[data-camada="camada-ortofoto"]')).toHaveCount(0);
  expect(pacote).toEqual([]);
});

test('arquivo do fundo que não abre (404): o mapa fica de pé no neutro, avisa e mantém as camadas', async ({ page, baseURL }) => {
  await page.route('**/pacote/arquivo/fundo.pmtiles*', (rota) => rota.fulfill({ status: 404, body: '' }));
  await abrir(page, baseURL);
  const mapa = await mapaPronto(page, 'neutro');
  await expect(mapa).not.toHaveAttribute('data-mapa-erro', /.*/); // falha de fonte do pacote não marca o mapa como quebrado
  await expect(mapa).toHaveAttribute('data-fundo-proprio-erro', 'sim');
  await expect(page.getByText('O fundo do mapa da fazenda não abriu. Mostrando o fundo neutro.')).toBeVisible();
  await expect(page.locator('[data-atribuicao-aberta]')).toBeHidden();
  await expect(mapa).toHaveAttribute('data-mapa-camadas', '3');
  expect(await noMapa(page, (m) => [m.getSource('fundo'), m.getLayer('fundo-terra')])).toEqual([undefined, undefined]);
});

test('rede caída no fundo (aborto): o mapa fica no neutro, sem erro fatal', async ({ page, baseURL }) => {
  await page.route('**/pacote/arquivo/fundo.pmtiles*', (rota) => rota.abort());
  await abrir(page, baseURL);
  const mapa = await mapaPronto(page, 'neutro');
  await expect(mapa).not.toHaveAttribute('data-mapa-erro', /.*/);
  await expect(mapa).toHaveAttribute('data-mapa-camadas', '3');
});

test('ortofoto que não carrega: avisa e as outras camadas seguem', async ({ page, baseURL }) => {
  await page.route('**/pacote/arquivo/ortofoto.pmtiles*', (rota) => rota.fulfill({ status: 404, body: '' }));
  await abrir(page, baseURL);
  const mapa = await mapaPronto(page);
  await page.locator('[data-camada="camada-ortofoto"]').getByRole('checkbox').check();
  await noMapa(page, (m) => m.jumpTo({ center: [-48.30, -10.75], zoom: 16 }));
  await expect(page.getByText('A ortofoto não carregou. As outras camadas seguem normais.')).toBeVisible();
  await expect(mapa).not.toHaveAttribute('data-mapa-erro', /.*/);
  await expect(mapa).toHaveAttribute('data-fundo-ativo', 'proprio');
});

test('acesso negado por URL direta: quem não tem alcance na fazenda recebe 404 do fundo e da ortofoto', async ({ page }, informacoes) => {
  const usuaria = turmaDe(informacoes).usuaria; // só alcança a primeira fazenda
  await entrar(page, usuaria.cpf);
  for (const nome of ['fundo.pmtiles', 'ortofoto.pmtiles']) {
    const resposta = await page.request.get(arquivo(nome), { headers: { Range: 'bytes=0-15' } });
    expect(resposta.status(), nome).toBe(404);
  }
  const pagina = await page.goto(comPacote());
  expect(pagina.status()).toBe(404);
  await expect(page.locator('[data-mapa]')).toHaveCount(0);
});

test('acesso negado por URL direta: sem login, o arquivo do pacote manda para a entrada', async ({ page }) => {
  const resposta = await page.goto(arquivo('fundo.pmtiles'));
  expect(new URL(resposta.url()).pathname).toBe('/entrar');
});
