'use strict';
// Mapa de teste de layout (spec 004 R1, R3, R16; T1.7). Roda com PHATI_MAPA_TESTE_ATIVO=1 e PHATI_AMBIENTE=teste (job
// `navegador`). MapLibre real no Chromium, fundo neutro, sem rede externa e sem violação de política de conteúdo.
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel, observarRequisicoesExternas, LON0, LAT0, noMapa, esperarOcioso, tocar } = require('./apoio.js');

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
  expect(politica).not.toContain('worker-src');
  expect(politica).not.toContain('unsafe-eval');
  const mapa = page.locator('[data-mapa]');
  await expect(mapa).toHaveAttribute('data-mapa-pronto', 'sim');
  await expect(mapa).not.toHaveAttribute('data-mapa-erro', /.*/);
  await expect(mapa.locator('canvas.maplibregl-canvas')).toBeVisible();
  await expect(mapa).toHaveAttribute('data-mapa-fundo', '#e8ecef'); // COR_DO_FUNDO de fundo-neutro.js, lida do estilo ativo
  await expect(page.getByText('Não foi possível abrir o mapa neste navegador.')).toBeHidden();
  expect(violacoes, 'violação de CSP no console').toEqual([]);
  expect(externas, 'requisição para host que não é o do app').toEqual([]);
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('o mapa preenche a região abaixo do título (sem faixa vazia)', async ({ page, baseURL }) => {
  await abrirMapa(page, baseURL);
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-pronto', 'sim');
  const regiao = await page.locator('.regiao-mapa').boundingBox();
  const mapa = await page.locator('[data-mapa]').boundingBox();
  const folga = regiao.y + regiao.height - (mapa.y + mapa.height);
  expect(folga, `faixa vazia de ${folga}px abaixo do mapa`).toBeLessThanOrEqual(24);
});

test('falha ao carregar o motor mostra o aviso na região, nunca região vazia', async ({ page }) => {
  await page.route('**/maplibre-gl.mjs', (rota) => rota.abort());
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(url(dados.empresa_a, dados.fazendas_a[0]));
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-erro', 'sim');
  await expect(page.getByText('Não foi possível abrir o mapa neste navegador.')).toBeVisible();
  await acessivel(page);
});

test('falha ao carregar o próprio mapa.js também deixa o aviso visível', async ({ page }) => {
  await page.route('**/projeto/mapa.js', (rota) => rota.abort());
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(url(dados.empresa_a, dados.fazendas_a[0]));
  await expect(page.getByRole('button', { name: 'Centralizar na minha posição' })).toBeDisabled(); // sem o script, o botão não promete o que não faz
  await expect(page.getByText('Não foi possível abrir o mapa neste navegador.')).toBeVisible();
  await expect(page.locator('[data-mapa]')).not.toHaveAttribute('data-mapa-pronto', /.*/);
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

// ---- Fase 2 (T2.4 a T2.7): camadas sintéticas, ordem, transparência, consulta, estados e posição ----------------------
// Pontos do dado sintético, em torno de LON0, LAT0 (camadas_sinteticas.py): P1 em três camadas; P2, P3 e P4 em uma feição só.
const P1 = [LON0, LAT0];
const P2 = [LON0 - 0.027, LAT0 + 0.008];
const P3 = [LON0 + 0.027, LAT0 + 0.008];
const P4 = [LON0, LAT0 - 0.027];

async function abrirComCamadas(page, baseURL) {
  const abertura = await abrirMapa(page, baseURL);
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-pronto', 'sim');
  await expect(page.locator('[data-camada]')).toHaveCount(3);
  await esperarOcioso(page);
  return abertura;
}

const idsDasCamadas = (page) => noMapa(page, (m) => m.getStyle().layers.map((l) => l.id).filter((id) => id.startsWith('camada-')));
const itensDaConsulta = (page) => page.locator('[data-lista-consulta] li button');

test('as três camadas abrem ligadas, o mapa enquadra a extensão e a legenda lista as três', async ({ page, baseURL }) => {
  const { externas, violacoes } = await abrirComCamadas(page, baseURL);
  await expect(page.locator('[data-lista-camadas] input[type="checkbox"]:checked')).toHaveCount(3);
  await expect(page.locator('[data-legenda] li')).toHaveText(['Camada A', 'Camada B', 'Camada C']);
  expect(await idsDasCamadas(page)).toEqual([
    'camada-c-preenchimento', 'camada-c-contorno', 'camada-b-preenchimento', 'camada-b-contorno', 'camada-a-preenchimento', 'camada-a-contorno']);
  const cobre = await noMapa(page, (m, pontos) => {
    const b = m.getBounds();
    return pontos.every((ponto) => b.contains(ponto));
  }, [[LON0 - 0.034, LAT0 - 0.034], [LON0 + 0.034, LAT0 + 0.014]]);
  expect(cobre, 'a extensão sintética cabe no enquadramento').toBe(true);
  expect(violacoes).toEqual([]);
  expect(externas).toEqual([]);
  await semRolagemHorizontal(page);
  await acessivel(page);
});

test('desligar e ligar uma camada muda a visibilidade das duas camadas de desenho e a legenda', async ({ page, baseURL }) => {
  await abrirComCamadas(page, baseURL);
  await page.getByRole('checkbox', { name: 'Camada B' }).uncheck();
  const visibilidade = () => noMapa(page, (m) => ['camada-b-preenchimento', 'camada-b-contorno'].map((id) => m.getLayoutProperty(id, 'visibility')));
  expect(await visibilidade()).toEqual(['none', 'none']);
  await expect(page.locator('[data-legenda] li')).toHaveText(['Camada A', 'Camada C']);
  await page.getByRole('checkbox', { name: 'Camada B' }).check();
  expect(await visibilidade()).toEqual(['visible', 'visible']);
  await expect(page.locator('[data-legenda] li')).toHaveText(['Camada A', 'Camada B', 'Camada C']);
});

test('todas desligadas: a consulta não acha nada e a legenda fica vazia (caminho infeliz)', async ({ page, baseURL }) => {
  await abrirComCamadas(page, baseURL);
  for (const nome of ['Camada A', 'Camada B', 'Camada C']) await page.getByRole('checkbox', { name: nome }).uncheck();
  await expect(page.locator('[data-legenda] li')).toHaveCount(0);
  await tocar(page, P1);
  await expect(page.locator('[data-estado-de="consulta"]')).toContainText('Sem informação.');
  await expect(itensDaConsulta(page)).toHaveCount(0);
});

test('subir e descer muda a ordem de desenho no estilo, na lista e na legenda', async ({ page, baseURL }) => {
  await abrirComCamadas(page, baseURL);
  await expect(page.getByRole('button', { name: 'Subir Camada A na ordem de desenho' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Descer Camada C na ordem de desenho' })).toBeDisabled();
  await page.getByRole('button', { name: 'Subir Camada B na ordem de desenho' }).click();
  expect(await idsDasCamadas(page)).toEqual([
    'camada-c-preenchimento', 'camada-c-contorno', 'camada-a-preenchimento', 'camada-a-contorno', 'camada-b-preenchimento', 'camada-b-contorno']);
  await expect(page.locator('[data-legenda] li')).toHaveText(['Camada B', 'Camada A', 'Camada C']);
  await tocar(page, P1); // a consulta segue a nova ordem de desenho
  await expect(itensDaConsulta(page).first()).toContainText('Camada B');
  await page.getByRole('button', { name: 'Descer Camada B na ordem de desenho' }).click();
  await expect(page.locator('[data-legenda] li')).toHaveText(['Camada A', 'Camada B', 'Camada C']);
});

test('o controle de transparência muda a opacidade do preenchimento e do contorno', async ({ page, baseURL }) => {
  await abrirComCamadas(page, baseURL);
  const opacidades = () => noMapa(page, (m) => [m.getPaintProperty('camada-c-preenchimento', 'fill-opacity'), m.getPaintProperty('camada-c-contorno', 'line-opacity')]);
  expect(await opacidades()).toEqual([0.6, 0.6]);
  await page.getByRole('slider', { name: 'Transparência de Camada C, em porcentagem' }).fill('100');
  expect(await opacidades()).toEqual([0, 0]);
  await page.getByRole('slider', { name: 'Transparência de Camada C, em porcentagem' }).fill('0');
  expect(await opacidades()).toEqual([1, 1]);
});

test('tocar onde há duas camadas e uma em análise lista exatamente três itens na ordem de desenho, com latitude e longitude', async ({ page, baseURL }) => {
  await abrirComCamadas(page, baseURL);
  await tocar(page, P1);
  const itens = itensDaConsulta(page);
  await expect(itens).toHaveCount(3);
  await expect(itens.nth(0)).toContainText('Camada A: Teor de argila, 32 % (Vigente, Medição de campo)');
  await expect(itens.nth(1)).toContainText('Camada B: Acidez do solo, 5,8 pH (Vigente, Estimativa)');
  await expect(itens.nth(2)).toContainText('Camada C: Declividade, 0 % (Em análise, Medição de campo)');
  await expect(page.locator('[data-coordenadas]')).toContainText(/Latitude -10,7[45]\d+, longitude -48,(29|30)\d+/);
  await expect(page.locator('[data-campo="camada"]')).toHaveText('Camada A'); // a ficha abre no painel da 003, com o primeiro item
  await itens.nth(1).click();
  await expect(page.locator('[data-campo="origem"]')).toHaveText('Estimativa');
  await expect(page.locator('[data-campo="metodo"]')).toHaveText('Interpolação sintética');
  await page.getByRole('checkbox', { name: 'Camada C' }).uncheck(); // desligada não entra na consulta
  await tocar(page, P1);
  await expect(itensDaConsulta(page)).toHaveCount(2);
});

test('substituída, arquivada e sem valor aparecem como tal, e ausente nunca vira zero', async ({ page, baseURL }) => {
  await abrirComCamadas(page, baseURL);
  await tocar(page, P2);
  await expect(itensDaConsulta(page)).toHaveCount(1);
  await expect(page.locator('[data-campo="situacao"]')).toHaveText('Substituída');
  await tocar(page, P3);
  await expect(page.locator('[data-campo="situacao"]')).toHaveText('Arquivada');
  await tocar(page, P4);
  await expect(page.locator('[data-campo="valor"]')).toHaveText('Sem informação');
  await expect(page.locator('[data-campo="valor"]')).not.toHaveText(/^0/);
});

test('tocar onde não há feição mostra sem informação, as coordenadas e limpa a ficha anterior', async ({ page, baseURL }) => {
  await abrirComCamadas(page, baseURL);
  await tocar(page, P1);
  await expect(page.locator('[data-campo="camada"]')).toHaveText('Camada A');
  await page.locator('[data-mapa]').scrollIntoViewIfNeeded();
  const topo = await page.locator('[data-mapa]').boundingBox();
  await page.mouse.click(topo.x + 4, topo.y + 4);
  await expect(page.locator('[data-estado-de="consulta"]')).toContainText('Sem informação.');
  await expect(page.locator('[data-coordenadas]')).toBeVisible();
  await expect(page.locator('[data-campo="camada"]')).toHaveCount(0); // ficha velha não fica sob consulta nova
  await expect(page.locator('[data-estado-de="ficha"]')).toContainText('A ficha, as fontes e as ressalvas aparecem aqui.');
});

test('nome de camada com HTML aparece como texto, no painel e na ficha, sem executar', async ({ page, baseURL }) => {
  const hostil = '<script>alert(1)</script>';
  await page.route('**/camadas.geojson', async (rota) => {
    const resposta = await rota.fetch();
    const corpo = await resposta.json();
    for (const f of corpo.features) if (f.properties.camada_id === 'camada-a') f.properties.camada = hostil;
    await rota.fulfill({ response: resposta, json: corpo });
  });
  let dialogo = false;
  page.on('dialog', async (d) => { dialogo = true; await d.dismiss(); });
  await abrirComCamadas(page, baseURL);
  await expect(page.locator('[data-camada="camada-a"] label')).toHaveText(hostil);
  await tocar(page, P1);
  await expect(page.locator('[data-campo="camada"]')).toHaveText(hostil);
  await expect(page.locator('[data-conteudo-de] script')).toHaveCount(0);
  expect(dialogo).toBe(false);
});

test('região de camadas: carregando enquanto a rota demora, e depois conteúdo', async ({ page, baseURL }) => {
  await page.route('**/camadas.geojson', async (rota) => { await new Promise((ok) => setTimeout(ok, 1500)); await rota.continue(); });
  await abrirMapa(page, baseURL);
  await expect(page.locator('[data-estado-de="camadas"]')).toContainText('Carregando…');
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-pronto', 'sim');
  await expect(page.locator('[data-estado-de="camadas"]')).toBeEmpty();
  await semRolagemHorizontal(page);
  await acessivel(page);
});

for (const [nome, resposta, texto] of [
  ['erro do servidor (500)', { status: 500, body: 'x' }, 'Não foi possível carregar as camadas.'],
  ['sem permissão (404)', { status: 404, body: 'x' }, 'Você não tem permissão para ver esta região.'],
  ['sem permissão (403)', { status: 403, body: 'x' }, 'Você não tem permissão para ver esta região.'],
  ['coleção vazia (sem informação)', { status: 200, contentType: 'application/geo+json', body: '{"type":"FeatureCollection","features":[]}' }, 'Sem informação.'],
  ['forma errada', { status: 200, contentType: 'application/geo+json', body: '{"type":"Outro"}' }, 'Não foi possível carregar as camadas.'],
  ['feição sem camada_id', { status: 200, contentType: 'application/geo+json', body: '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{}}]}' }, 'Não foi possível carregar as camadas.'],
  ['JSON quebrado', { status: 200, contentType: 'application/geo+json', body: '{' }, 'Não foi possível carregar as camadas.'],
]) {
  test(`região de camadas: ${nome}`, async ({ page, baseURL }) => {
    await page.route('**/camadas.geojson', (rota) => rota.fulfill(resposta));
    await abrirMapa(page, baseURL);
    await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-pronto', 'sim');
    for (const regiao of ['camadas', 'consulta', 'ficha']) await expect(page.locator(`[data-estado-de="${regiao}"]`)).toContainText(texto); // falha vale para as três regiões
    await expect(page.locator('[data-camada]')).toHaveCount(0);
    await semRolagemHorizontal(page);
    await acessivel(page);
  });
}

test('região de camadas: falha de rede mostra erro e o mapa segue de pé', async ({ page, baseURL }) => {
  await page.route('**/camadas.geojson', (rota) => rota.abort());
  await abrirMapa(page, baseURL);
  await expect(page.locator('[data-estado-de="camadas"]')).toContainText('Não foi possível carregar as camadas.');
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-pronto', 'sim');
  await expect(page.locator('[data-mapa] canvas.maplibregl-canvas')).toBeVisible();
});

test('o estado vazio inicial das regiões de consulta e de ficha está à vista antes de tocar', async ({ page, baseURL }) => {
  await abrirComCamadas(page, baseURL);
  await expect(page.locator('[data-estado-de="consulta"]')).toContainText('Escolha um ponto no mapa para consultar.');
  await expect(page.locator('[data-estado-de="ficha"]')).toContainText('A ficha, as fontes e as ressalvas aparecem aqui.');
});

test('sem alcance à fazenda, a rota de camadas dá 404 por URL direta; deslogado vai ao login', async ({ page, browser, baseURL }) => {
  await entrar(page, dados.sem_acesso.cpf);
  const caminho = `/empresa/${dados.empresa_a}/fazenda/${dados.fazendas_a[0]}/camadas.geojson`;
  const resposta = await page.request.get(caminho);
  expect(resposta.status()).toBe(404);
  expect(await resposta.text()).not.toContain('FeatureCollection');
  const anonimo = await (await browser.newContext({ baseURL })).newPage();
  const login = await anonimo.request.get(caminho, { maxRedirects: 0 });
  expect(login.status()).toBe(302);
  expect(login.headers().location).toContain('/entrar');
});

test('recentralizar: com permissão centraliza na posição e nenhuma requisição leva a posição', async ({ page, baseURL, context }) => {
  const externas = observarRequisicoesExternas(page, baseURL);
  const urls = [];
  page.on('request', (r) => urls.push(r.url() + (r.postData() ?? '')));
  await context.grantPermissions(['geolocation'], { origin: new URL(baseURL).origin });
  await context.setGeolocation({ latitude: -10.71234, longitude: -48.32345 });
  await abrirComCamadas(page, baseURL);
  await page.getByRole('button', { name: 'Centralizar na minha posição' }).click();
  await expect.poll(() => noMapa(page, (m) => m.getCenter().lat.toFixed(4))).toBe('-10.7123');
  expect(await noMapa(page, (m) => m.getCenter().lng.toFixed(4))).toBe('-48.3235');
  expect(urls.filter((u) => /10\.71234|48\.32345/.test(u))).toEqual([]);
  expect(externas).toEqual([]);
});

test('recentralizar: permissão negada mostra a mensagem e o mapa segue intacto', async ({ page, baseURL, context }) => {
  await context.clearPermissions();
  await abrirComCamadas(page, baseURL);
  const antes = await noMapa(page, (m) => m.getCenter().toArray());
  await page.getByRole('button', { name: 'Centralizar na minha posição' }).click();
  await expect(page.locator('[data-mapa-mensagem]')).toContainText('Permissão de localização negada');
  expect(await noMapa(page, (m) => m.getCenter().toArray())).toEqual(antes);
  await expect(page.locator('[data-camada]')).toHaveCount(3);
  await acessivel(page);
});

test('recentralizar: o botão não pede a posição ao abrir a página', async ({ page, baseURL, context }) => {
  await context.grantPermissions(['geolocation'], { origin: new URL(baseURL).origin });
  await page.addInitScript(() => {
    window.__pedidosDePosicao = 0;
    const original = navigator.geolocation.getCurrentPosition.bind(navigator.geolocation);
    navigator.geolocation.getCurrentPosition = (...a) => { window.__pedidosDePosicao += 1; return original(...a); };
  });
  await abrirComCamadas(page, baseURL);
  expect(await page.evaluate(() => window.__pedidosDePosicao)).toBe(0);
});

// ---- Achados da revisão da PR #36 ----------------------------------------------------------------------------------

test('o controle de transparência segue vivo: duas setas seguidas mudam o valor e o foco fica nele', async ({ page, baseURL }) => {
  await abrirComCamadas(page, baseURL);
  const controle = page.getByRole('slider', { name: 'Transparência de Camada C, em porcentagem' });
  await controle.focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await expect(controle).toBeFocused();
  await expect(controle).toHaveValue('42');
  expect(await noMapa(page, (m) => m.getPaintProperty('camada-c-preenchimento', 'fill-opacity'))).toBeCloseTo(0.58, 5);
});

test('subir mantém o foco: o botão ou, na ponta, o outro botão da mesma camada', async ({ page, baseURL }) => {
  await abrirComCamadas(page, baseURL);
  const subir = page.getByRole('button', { name: 'Subir Camada B na ordem de desenho' });
  await subir.focus();
  await page.keyboard.press('Enter'); // B vira a primeira: o Subir dela fica desabilitado
  await expect(page.getByRole('button', { name: 'Descer Camada B na ordem de desenho' })).toBeFocused();
  await page.keyboard.press('Enter'); // desce de novo
  await expect(page.locator('[data-legenda] li')).toHaveText(['Camada A', 'Camada B', 'Camada C']);
  await expect(page.getByRole('button', { name: 'Descer Camada B na ordem de desenho' })).toBeFocused();
});

test('desligar ou reordenar limpa a consulta e a ficha que já não valem', async ({ page, baseURL }) => {
  await abrirComCamadas(page, baseURL);
  await tocar(page, P1);
  await expect(itensDaConsulta(page)).toHaveCount(3);
  await page.getByRole('checkbox', { name: 'Camada C' }).uncheck();
  await expect(itensDaConsulta(page)).toHaveCount(0);
  await expect(page.locator('[data-estado-de="consulta"]')).toContainText('Escolha um ponto no mapa para consultar.');
  await expect(page.locator('[data-campo="camada"]')).toHaveCount(0);
  await tocar(page, P1);
  await expect(itensDaConsulta(page)).toHaveCount(2);
  await page.getByRole('button', { name: 'Subir Camada B na ordem de desenho' }).click();
  await expect(itensDaConsulta(page)).toHaveCount(0);
  await tocar(page, P1);
  await page.getByRole('slider', { name: 'Transparência de Camada A, em porcentagem' }).fill('10'); // transparência não invalida a consulta
  await expect(itensDaConsulta(page)).toHaveCount(2);
});

test('sessão expirada na rota de camadas leva ao login, não a um erro genérico', async ({ page, baseURL }) => {
  await page.route('**/camadas.geojson', (rota) => rota.fulfill({ status: 302, headers: { location: '/entrar?proximo=%2F' } }));
  await abrirMapa(page, baseURL);
  await page.waitForURL(/\/entrar\?.*expirou=1/);
  await expect(page.getByText('Sua sessão expirou.')).toBeVisible();
});

test('rota que nunca responde vira erro no prazo, nas três regiões', async ({ page, baseURL }) => {
  await page.route('**/camadas.geojson', () => {}); // nunca responde nem falha
  await page.route(url(dados.empresa_a, dados.fazendas_a[0]), async (rota) => {
    const resposta = await rota.fetch();
    await rota.fulfill({ response: resposta, body: (await resposta.text()).replace('data-camadas-tempo-limite="15000"', 'data-camadas-tempo-limite="800"') });
  });
  await abrirMapa(page, baseURL);
  for (const regiao of ['camadas', 'consulta', 'ficha']) {
    await expect(page.locator(`[data-estado-de="${regiao}"]`)).toContainText('Não foi possível carregar as camadas.');
  }
  await expect(page.locator('[data-mapa]')).toHaveAttribute('data-mapa-pronto', 'sim');
});

test('recentralizar antes de as camadas chegarem não é desfeito pelo enquadramento inicial', async ({ page, baseURL, context }) => {
  await page.route('**/camadas.geojson', async (rota) => { await new Promise((ok) => setTimeout(ok, 1500)); await rota.continue(); });
  // Motor lento: o botão existe no HTML antes de o script ligar o clique. Nasce desabilitado, então o toque espera (falha do CI da PR #36).
  await page.route('**/maplibre-gl.mjs', async (rota) => { await new Promise((ok) => setTimeout(ok, 2000)); await rota.continue(); });
  await context.grantPermissions(['geolocation'], { origin: new URL(baseURL).origin });
  await context.setGeolocation({ latitude: 0.41234, longitude: 0.42345 });
  await abrirMapa(page, baseURL);
  const botaoPosicao = page.getByRole('button', { name: 'Centralizar na minha posição' });
  await expect(botaoPosicao).toBeDisabled();
  await botaoPosicao.click(); // espera habilitar
  await expect.poll(() => noMapa(page, (m) => m.getCenter().lat.toFixed(4))).toBe('0.4123');
  await expect(page.locator('[data-camada]')).toHaveCount(3); // as camadas chegaram depois
  await esperarOcioso(page);
  expect(await noMapa(page, (m) => m.getCenter().lat.toFixed(4))).toBe('0.4123');
});
