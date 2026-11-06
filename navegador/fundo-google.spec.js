'use strict';
// Fundo Google (spec 004 R17 a R19; T3.5). Roda no job `navegador` num segundo passo, com PHATI_MAPA_FUNDO_GOOGLE_ATIVO=1 e uma
// chave sintética, e só com PHATI_PROVA_GOOGLE=1 (ver `playwright.config.js`). Nenhuma requisição chega ao Google: todo o
// tráfego para `tile.googleapis.com` é atendido por um dublê de rede, e o teste confere que cada requisição foi atendida por ele.
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel } = require('./apoio.js');

const ORIGEM = 'https://tile.googleapis.com';
const PNG_1X1 = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');
const CORS = { 'access-control-allow-origin': '*', 'access-control-allow-headers': 'content-type', 'access-control-allow-methods': 'GET,POST' };

// Dublê: sessões numeradas (a renovação fica visível pelo número), copyright fixo, tile de 1 pixel.
// `segundosDeValidade` curto faz a página renovar logo (renova uma hora antes de `expiry`, então 3600 s de folga + o prazo).
async function dublarGoogle(page, { segundosDeValidade = 14 * 24 * 3600, recusarSessao = false, recusarPrimeiras = 0 } = {}) {
  const vistas = { recusadas: 0, atendidas: 0, sessoes: [], tiles: [], zoomsDosTiles: [], viewports: [] };
  let numero = 0;
  await page.route(`${ORIGEM}/**`, async (rota) => {
    const pedido = rota.request();
    const alvo = new URL(pedido.url());
    vistas.atendidas += 1;
    if (pedido.method() === 'OPTIONS') return rota.fulfill({ status: 204, headers: CORS });
    if (alvo.pathname === '/v1/createSession') {
      if (recusarSessao || vistas.recusadas < recusarPrimeiras) {
        vistas.recusadas += 1;
        return rota.fulfill({ status: 403, headers: CORS, json: { error: 'recusado' } });
      }
      numero += 1;
      vistas.sessoes.push(numero);
      const expiry = String(Math.floor(Date.now() / 1000) + segundosDeValidade);
      return rota.fulfill({ status: 200, headers: CORS, json: { session: `sessao-sintetica-${numero}`, expiry, tileWidth: 256, tileHeight: 256, imageFormat: 'jpeg' } });
    }
    if (alvo.pathname === '/tile/v1/viewport') {
      vistas.viewports.push(alvo.search);
      return rota.fulfill({ status: 200, headers: CORS, json: { copyright: 'Imagens sintéticas de teste', maxZoomRects: [] } });
    }
    if (alvo.pathname.startsWith('/v1/2dtiles/')) {
      vistas.tiles.push(alvo.searchParams.get('session'));
      vistas.zoomsDosTiles.push(alvo.pathname.split('/')[3]);
      return rota.fulfill({ status: 200, headers: { ...CORS, 'content-type': 'image/png' }, body: PNG_1X1 });
    }
    return rota.fulfill({ status: 404, headers: CORS });
  });
  return vistas;
}

// `elementFromPoint` devolve null fora da viewport (a atribuição fica abaixo do mapa, fora da tela em 1280×720 e 320×568,
// medido em 2026-11-04): rola o elemento à vista antes de olhar o que está no ponto.
async function centralizar(alvo) {
  await alvo.evaluate((el) => el.scrollIntoView({ block: 'center', inline: 'nearest' }));
}

// `cobrir` põe um div fixo sobre a caixa atual do elemento na MESMA execução síncrona que mede, depois da rolagem: sem ida ao
// navegador entre criar a capa e olhar o ponto, o layout não muda no meio (o teste do CI falhou uma vez com a capa fora do lugar).
async function medirCobertura(alvo, { cobrir = false } = {}) {
  await centralizar(alvo);
  return alvo.evaluate((el, cobrirAgora) => {
    el.scrollIntoView({ block: 'center', inline: 'nearest' });
    const r = el.getBoundingClientRect();
    if (cobrirAgora) {
      const capa = document.createElement('div');
      capa.style.cssText = `position:fixed;left:${r.x}px;top:${r.y}px;width:${r.width}px;height:${r.height}px;z-index:9999`;
      document.body.append(capa);
    }
    const x = r.x + 2;
    const y = r.y + r.height / 2;
    const topo = document.elementFromPoint(x, y);
    const quem = (n) => (n ? `${n.tagName.toLowerCase()}.${n.className}[${Object.keys(n.dataset).join(',')}]` : null);
    return { livre: el.contains(topo), ponto: [x, y], viewport: [window.innerWidth, window.innerHeight], caixa: [r.x, r.y, r.width, r.height], noPonto: quem(topo) };
  }, cobrir);
}

async function abrir(page) {
  const violacoes = [];
  const googleVisto = [];
  page.on('console', (m) => { if (/Content Security Policy/i.test(m.text())) violacoes.push(m.text()); });
  page.on('request', (r) => { if (new URL(r.url()).origin === ORIGEM) googleVisto.push(r.url()); });
  await entrar(page, dados.administradora_a.cpf);
  const resposta = await page.goto(`/empresa/${dados.empresa_a}/fazenda/${dados.fazendas_a[0]}/`);
  return { resposta, violacoes, googleVisto };
}

// O satélite só carrega depois do clique (custo: cada tile é cobrado): espera o mapa pronto, clica e espera o fundo entrar.
async function ativarSatelite(page) {
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-pronto', 'sim');
  const botao = page.locator('[data-satelite]');
  await expect(botao).toBeEnabled();
  await botao.click();
}

test('a prova roda com a flag do Google ligada no servidor', async ({ page }) => {
  await dublarGoogle(page);
  await abrir(page);
  await expect(page.locator('[data-mapa]'), 'suba o app com PHATI_MAPA_FUNDO_GOOGLE_ATIVO=1 e uma chave sintética').toHaveAttribute('data-fundo-online-chave', /.+/);
});

test('sem clicar em Ativar satélite, nada sai para o Google e a atribuição não aparece', async ({ page }) => {
  const vistas = await dublarGoogle(page);
  const { googleVisto } = await abrir(page);
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-pronto', 'sim');
  await expect(page.locator('[data-satelite]')).toBeEnabled();
  await page.waitForTimeout(2000); // dá tempo de um pedido indevido aparecer
  expect(googleVisto, 'pedido ao Google sem a pessoa ligar o satélite').toEqual([]);
  expect(vistas.atendidas).toBe(0);
  await expect(page.locator('[data-mapa-atribuicao]')).toBeHidden();
  expect(await page.evaluate(() => document.querySelector('[data-mapa]').mapa.getSource('fundo-online') === undefined)).toBe(true);
});

test('o fundo aparece por tiles da sessão, com política só para o domínio dos tiles e sem requisição real', async ({ page }) => {
  const vistas = await dublarGoogle(page);
  const { resposta, violacoes, googleVisto } = await abrir(page);
  await ativarSatelite(page);
  const politica = resposta.headers()['content-security-policy'];
  expect(politica).toContain(`connect-src 'self' ${ORIGEM}`);
  expect(politica).toContain(`img-src 'self' data: blob: ${ORIGEM}`);
  expect(politica).not.toContain('unsafe-eval');
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-pronto', 'sim');
  await expect.poll(() => vistas.tiles.length, 'nenhum tile pedido').toBeGreaterThan(0);
  expect(new Set(vistas.tiles)).toEqual(new Set(['sessao-sintetica-1']));
  // O crédito vale para o nível dos tiles à vista, que o MapLibre calcula com +1 para tiles de 256 px (medido: getZoom 11,96, tiles z=13).
  await expect.poll(() => vistas.viewports.length).toBeGreaterThan(0);
  const zoomDoCredito = new URLSearchParams(vistas.viewports[0]).get('zoom');
  expect(vistas.zoomsDosTiles, 'o viewport foi consultado num nível sem tile à vista').toContain(zoomDoCredito);
  expect(await page.evaluate(() => document.querySelector('[data-mapa]').mapa.getSource('fundo-online') !== undefined)).toBe(true);
  expect(googleVisto.length, 'toda requisição ao domínio foi atendida pelo dublê').toBeGreaterThan(0);
  expect(vistas.atendidas).toBe(googleVisto.length);
  expect(violacoes, 'violação de CSP no console').toEqual([]);
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('logo e atribuição de dados ficam à vista, fora do mapa, sem nada por cima', async ({ page }) => {
  await dublarGoogle(page);
  await abrir(page);
  await ativarSatelite(page);
  const atribuicao = page.locator('[data-mapa-atribuicao]');
  await expect(atribuicao).toContainText('Google Maps');
  await expect(atribuicao).toContainText('Imagens sintéticas de teste'); // vem do copyright do viewport
  // Logo oficial (T3.8): visível, carregado, com rótulo de acessibilidade, 16 a 19 dp de altura e área livre mínima (10, 10, 10 e 5).
  const logo = atribuicao.getByRole('img', { name: 'Google Maps' });
  await expect(logo).toBeVisible();
  expect(await logo.evaluate((img) => img.complete && img.naturalWidth > 0), 'o logo não carregou').toBe(true);
  const altura = (await logo.boundingBox()).height;
  expect(altura, `altura do logo ${altura}`).toBeGreaterThanOrEqual(16);
  expect(altura).toBeLessThanOrEqual(19);
  const livre = await atribuicao.evaluate((el) => { const c = getComputedStyle(el); return [c.paddingLeft, c.paddingRight, c.paddingTop, c.paddingBottom].map(parseFloat); });
  expect(livre.slice(0, 3).every((v) => v >= 10) && livre[3] >= 5, `área livre ${livre}`).toBe(true);
  await centralizar(atribuicao); // as duas caixas são medidas na mesma rolagem
  const caixa = await atribuicao.boundingBox();
  const mapa = await page.locator('[data-mapa]').boundingBox();
  expect(caixa.y, 'a atribuição não sobrepõe o mapa').toBeGreaterThanOrEqual(mapa.y + mapa.height - 1);
  expect((await medirCobertura(atribuicao)).livre, 'algum elemento cobre a atribuição').toBe(true);
});

test('a checagem de cobertura reprova quando um elemento cobre a atribuição', async ({ page }) => {
  await dublarGoogle(page);
  await abrir(page);
  await ativarSatelite(page);
  const atribuicao = page.locator('[data-mapa-atribuicao]');
  await expect(atribuicao).toContainText('Imagens sintéticas de teste'); // o crédito já chegou: a caixa não muda mais
  const medida = await medirCobertura(atribuicao, { cobrir: true });
  expect(medida.livre, JSON.stringify(medida)).toBe(false);
  expect(medida.noPonto).toMatch(/^div/);
});

test('a sessão é renovada antes de vencer e os tiles novos usam a sessão nova', async ({ page }) => {
  const vistas = await dublarGoogle(page, { segundosDeValidade: 3600 + 2 }); // renova 2 s depois de abrir
  await abrir(page);
  await ativarSatelite(page);
  await expect.poll(() => vistas.sessoes.length, { timeout: 20000 }).toBeGreaterThanOrEqual(2);
  await page.evaluate(() => document.querySelector('[data-mapa]').mapa.jumpTo({ zoom: 16 })); // força tiles novos
  await expect.poll(() => vistas.tiles.includes('sessao-sintetica-2'), { timeout: 20000 }).toBe(true);
});

test('sessão recusada: o mapa fica de pé no fundo neutro e a página avisa', async ({ page }) => {
  await dublarGoogle(page, { recusarSessao: true });
  await abrir(page);
  const mapa = page.locator('[data-mapa]');
  await ativarSatelite(page);
  await expect(mapa).toHaveAttribute('data-fundo-online-erro', 'sim');
  await expect(page.locator('[data-satelite]'), 'a pessoa pode tentar de novo').toBeEnabled();
  await expect(mapa).toHaveAttribute('data-mapa-fundo', '#e8ecef');
  await expect(page.getByText('O fundo do mapa está indisponível. Mostrando o fundo neutro.')).toBeVisible();
});

test('sessão recusada e depois aceita: o segundo clique liga o satélite e o erro da tentativa anterior some', async ({ page }) => {
  await dublarGoogle(page, { recusarPrimeiras: 1 });
  await abrir(page);
  const mapa = page.locator('[data-mapa]');
  await ativarSatelite(page);
  await expect(mapa).toHaveAttribute('data-fundo-online-erro', 'sim');
  await ativarSatelite(page); // botão voltou a habilitar
  await expect(mapa).toHaveAttribute('data-mapa-satelite', 'sim');
  await expect(mapa).not.toHaveAttribute('data-fundo-online-erro', /.*/);
  await expect(page.getByText('O fundo do mapa está indisponível. Mostrando o fundo neutro.')).toBeHidden();
});

test('tile com 401 (sessão recusada): desliga o satélite, esquece a sessão guardada e deixa ligar de novo', async ({ page }) => {
  const vistas = await dublarGoogle(page);
  await page.route(`${ORIGEM}/v1/2dtiles/**`, (rota) => rota.fulfill({ status: 401, headers: CORS }));
  await abrir(page);
  await ativarSatelite(page);
  await expect(page.getByText('A sessão do satélite não vale mais. Ative o satélite de novo.')).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('phati.fundo-google.sessao')), 'a sessão recusada ficou guardada').toBeNull();
  await expect(page.locator('[data-satelite]')).toBeEnabled();
  await expect(page.locator('[data-satelite]')).toHaveText('Ativar satélite');
  expect(await page.evaluate(() => document.querySelector('[data-mapa]').mapa.getSource('fundo-online')), 'o Google ficou no mapa').toBeUndefined();
  await expect(page.locator('[data-mapa-atribuicao]')).toBeHidden();
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-camadas', '3');
  expect(vistas.sessoes.length).toBe(1);
});

test('sem rede: o satélite se desliga inteiro, o fundo neutro fica sozinho e as camadas seguem', async ({ page }) => {
  await dublarGoogle(page);
  await page.route(`${ORIGEM}/v1/2dtiles/**`, (rota) => rota.abort());
  await abrir(page);
  const mapa = page.locator('[data-mapa]');
  await ativarSatelite(page);
  await expect(page.getByText('Sem rede ou sem resposta do fundo online: o satélite foi desligado e o mapa voltou ao fundo neutro.')).toBeVisible();
  await expect(mapa).toHaveAttribute('data-mapa-satelite', 'nao');
  await expect(mapa).toHaveAttribute('data-mapa-camadas', '3');
  await expect(mapa).not.toHaveAttribute('data-mapa-erro', /.*/); // tile mudo não marca o mapa como quebrado
  expect(await page.evaluate(() => { const m = document.querySelector('[data-mapa]').mapa; return [m.getSource('fundo-online'), m.getLayer('fundo-online-tiles')]; }), 'Google e neutro juntos').toEqual([undefined, undefined]);
  await expect(page.locator('[data-mapa-atribuicao]')).toBeHidden();
  await expect(page.locator('[data-satelite]')).toBeEnabled();
});

test('depois de desligar por falta de rede, o mesmo botão liga o satélite de novo, sem duplicar fonte nem camada', async ({ page }) => {
  const vistas = await dublarGoogle(page);
  let falhar = true;
  await page.route(`${ORIGEM}/v1/2dtiles/**`, (rota) => (falhar ? rota.abort() : rota.fallback())); // fallback: cai no dublê
  await abrir(page);
  await ativarSatelite(page);
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-satelite', 'nao');
  falhar = false;
  await ativarSatelite(page);
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-satelite', 'sim');
  await expect(page.locator('[data-mapa-atribuicao]')).toBeVisible();
  const camadas = await page.evaluate(() => document.querySelector('[data-mapa]').mapa.getStyle().layers.filter((l) => l.id === 'fundo-online-tiles').length);
  expect(camadas).toBe(1);
  await expect.poll(() => vistas.tiles.length).toBeGreaterThan(0);
});

test('tile 404 (sem imagem naquele ponto) não derruba o satélite nem avisa: o MapLibre trata como tile vazio', async ({ page }) => {
  await dublarGoogle(page);
  await page.route(`${ORIGEM}/v1/2dtiles/**`, (rota) => rota.fulfill({ status: 404, headers: CORS }));
  await abrir(page);
  await ativarSatelite(page);
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-satelite', 'sim');
  await page.waitForTimeout(2500); // dá tempo de um desligamento indevido aparecer
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-satelite', 'sim');
  await expect(page.locator('[data-mapa-atribuicao]')).toBeVisible();
  await expect(page.locator('[data-mapa-fundo-aviso]')).toBeHidden();
});

// ---- Troca de fundo com o pacote da fazenda (spec 004b R9, R10; A8) -----------------------------------------------------------
// A segunda fazenda da empresa A tem o pacote de referência (`popular_sintetico`). O Google continua atendido só pelo dublê de rede;
// o fundo próprio vem do PMTiles servido pelo app. Em nenhum quadro os dois fundos podem estar no estilo ao mesmo tempo.
const COM_PACOTE = () => `/empresa/${dados.empresa_a}/fazenda/${dados.fazendas_a[1]}/`;
const FUNDO_DA_FAZENDA = 'fundo do mapa da fazenda';

async function abrirComPacote(page) {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(COM_PACOTE());
  const mapa = page.locator('[data-mapa]');
  await expect(mapa).toHaveAttribute('data-mapa-pronto', 'sim');
  await expect(mapa).toHaveAttribute('data-fundo-ativo', 'proprio');
  // Observador de exclusão mútua: a cada quadro conta quantas vezes os dois fundos estiveram no estilo juntos.
  await page.evaluate(() => {
    const m = document.querySelector('[data-mapa]').mapa;
    window.__juntos = 0;
    window.__marca = 'sem-recarregar';
    m.on('render', () => { if (m.getLayer('fundo-terra') && m.getLayer('fundo-online-tiles')) window.__juntos += 1; });
  });
  return mapa;
}

const juntos = (page) => page.evaluate(() => window.__juntos);
const fundos = (page) => page.evaluate(() => {
  const m = document.querySelector('[data-mapa]').mapa;
  return { proprio: Boolean(m.getSource('fundo') || m.getLayer('fundo-terra')), online: Boolean(m.getSource('fundo-online') || m.getLayer('fundo-online-tiles')) };
});

test('com pacote: o satélite tira o fundo da fazenda, a atribuição acompanha o fundo e o mesmo botão volta nos dois sentidos', async ({ page }) => {
  const vistas = await dublarGoogle(page);
  const mapa = await abrirComPacote(page);
  const osm = page.locator('[data-atribuicao-aberta]');
  const googleAtribuicao = page.locator('[data-mapa-atribuicao]');
  await expect(osm).toBeVisible();
  await expect(googleAtribuicao).toBeHidden();
  expect(vistas.atendidas, 'o Google foi chamado sem a pessoa ligar').toBe(0);
  expect(await fundos(page)).toEqual({ proprio: true, online: false });

  await page.locator('[data-satelite]').click();
  await expect(mapa).toHaveAttribute('data-fundo-ativo', 'online');
  expect(await fundos(page), 'os dois fundos no estilo').toEqual({ proprio: false, online: true });
  await expect(osm).toBeHidden();
  await expect(googleAtribuicao).toBeVisible();
  await expect(page.locator('[data-satelite]')).toHaveText('Voltar ao fundo da fazenda');
  await expect(mapa).toHaveAttribute('data-mapa-camadas', '3');

  for (let volta = 0; volta < 2; volta += 1) { // escolha manual nos dois sentidos, repetida
    await page.locator('[data-satelite]').click(); // volta ao fundo da fazenda
    await expect(mapa).toHaveAttribute('data-fundo-ativo', 'proprio');
    expect(await fundos(page)).toEqual({ proprio: true, online: false });
    await expect(osm).toBeVisible();
    await expect(googleAtribuicao).toBeHidden();
    await expect(page.locator('[data-satelite]')).toHaveText('Ativar satélite');
    await page.locator('[data-satelite]').click(); // liga de novo
    await expect(mapa).toHaveAttribute('data-fundo-ativo', 'online');
    expect(await fundos(page)).toEqual({ proprio: false, online: true });
  }
  expect(await juntos(page), 'quadros com os dois fundos no estilo').toBe(0);
  await expect(mapa).not.toHaveAttribute('data-mapa-erro', /.*/);
});

test('com pacote: sessão recusada deixa o fundo da fazenda de pé, com aviso', async ({ page }) => {
  await dublarGoogle(page, { recusarSessao: true });
  const mapa = await abrirComPacote(page);
  await page.locator('[data-satelite]').click();
  await expect(page.getByText(`O fundo do mapa está indisponível. Mostrando o ${FUNDO_DA_FAZENDA}.`)).toBeVisible();
  await expect(mapa).toHaveAttribute('data-fundo-ativo', 'proprio');
  expect(await fundos(page)).toEqual({ proprio: true, online: false });
  await expect(page.locator('[data-satelite]')).toBeEnabled();
  expect(await juntos(page)).toBe(0);
});

test('com pacote: sem rede o satélite cai para o fundo da fazenda sem recarregar, com as camadas e a ficha de pé', async ({ page }) => {
  await dublarGoogle(page);
  let falhar = false;
  await page.route(`${ORIGEM}/v1/2dtiles/**`, (rota) => (falhar ? rota.abort() : rota.fallback()));
  const mapa = await abrirComPacote(page);
  await page.locator('[data-satelite]').click();
  await expect(mapa).toHaveAttribute('data-fundo-ativo', 'online');
  // Consulta feita com o satélite ligado: a ficha já carregada continua na tela quando o fundo muda.
  await page.evaluate(() => document.querySelector('[data-mapa]').mapa.jumpTo({ center: [-48.30, -10.75], zoom: 12 }));
  await page.waitForFunction(() => { const m = document.querySelector('[data-mapa]').mapa; return m.loaded() && !m.isMoving(); });
  await page.locator('[data-mapa]').scrollIntoViewIfNeeded(); // rola antes de projetar o ponto: a posição na tela muda com a rolagem
  const alvo = await page.evaluate(() => {
    const e = document.querySelector('[data-mapa]');
    const p = e.mapa.project([-48.30, -10.75]);
    const c = e.getBoundingClientRect();
    return { x: c.left + p.x, y: c.top + p.y };
  });
  await page.mouse.click(alvo.x, alvo.y);
  await expect(page.locator('[data-lista-consulta] li button').first()).toBeVisible();
  falhar = true;
  await page.evaluate(() => document.querySelector('[data-mapa]').mapa.jumpTo({ zoom: 15 })); // tiles novos, todos recusados
  await expect(page.getByText(`o mapa voltou ao ${FUNDO_DA_FAZENDA}.`, { exact: false })).toBeVisible();
  await expect(mapa).toHaveAttribute('data-fundo-ativo', 'proprio');
  await expect(mapa).toHaveAttribute('data-mapa-satelite', 'nao');
  expect(await fundos(page)).toEqual({ proprio: true, online: false });
  expect(await page.evaluate(() => window.__marca), 'a página recarregou').toBe('sem-recarregar');
  await expect(mapa).toHaveAttribute('data-mapa-camadas', '3');
  await expect(page.locator('[data-lista-consulta] li button').first(), 'a consulta já carregada sumiu').toBeVisible();
  await expect(mapa).not.toHaveAttribute('data-mapa-erro', /.*/);
  expect(await juntos(page)).toBe(0);
});

test('com pacote: a ortofoto ligada fica por cima do satélite, como camada', async ({ page }) => {
  await dublarGoogle(page);
  const mapa = await abrirComPacote(page);
  await page.locator('[data-camada="camada-ortofoto"]').getByRole('checkbox').check();
  await page.locator('[data-satelite]').click();
  await expect(mapa).toHaveAttribute('data-fundo-ativo', 'online');
  await expect(page.locator('[data-atribuicao-ortofoto]'), 'crédito da ortofoto sumiu com o satélite').toBeVisible();
  const ordem = await page.evaluate(() => {
    const m = document.querySelector('[data-mapa]').mapa;
    const ids = m.getStyle().layers.map((l) => l.id);
    return { online: ids.indexOf('fundo-online-tiles'), ortofoto: ids.indexOf('camada-ortofoto'), visivel: m.getLayoutProperty('camada-ortofoto', 'visibility') };
  });
  expect(ordem.online).toBeGreaterThanOrEqual(0);
  expect(ordem.ortofoto, 'a ortofoto não ficou acima do satélite').toBeGreaterThan(ordem.online);
  expect(ordem.visivel).toBe('visible');
});
