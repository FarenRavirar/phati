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
  await expect(mapa).toHaveAttribute('data-satelite', 'sim');
  await expect(mapa).not.toHaveAttribute('data-fundo-online-erro', /.*/);
  await expect(page.getByText('O fundo do mapa está indisponível. Mostrando o fundo neutro.')).toBeHidden();
});

test('tile com 401 (sessão recusada): esquece a sessão guardada, avisa para recarregar e as camadas seguem', async ({ page }) => {
  await dublarGoogle(page);
  await page.route(`${ORIGEM}/v1/2dtiles/**`, (rota) => rota.fulfill({ status: 401, headers: CORS }));
  await abrir(page);
  await ativarSatelite(page);
  await expect(page.getByText('A sessão do satélite não vale mais. Recarregue a página e ative o satélite de novo.')).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('phati.fundo-google.sessao')), 'a sessão recusada ficou guardada').toBeNull();
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-camadas', '3');
});

test('tile que falha na rede não derruba o mapa nem as camadas', async ({ page }) => {
  await dublarGoogle(page);
  await page.route(`${ORIGEM}/v1/2dtiles/**`, (rota) => rota.abort());
  await abrir(page);
  const mapa = page.locator('[data-mapa]');
  await ativarSatelite(page);
  await expect(mapa).toHaveAttribute('data-mapa-camadas', '3');
  await expect(mapa).not.toHaveAttribute('data-mapa-erro', /.*/); // tile mudo não marca o mapa como quebrado
  await expect(page.getByText('Parte do fundo do mapa não carregou. As camadas seguem normais.')).toBeVisible();
});
