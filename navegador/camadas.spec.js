'use strict';
// Testes de navegador da tela de camadas do Administrador (008 T4.2; R18, R21; A8): envio, prévia e publicação, nos dois
// tamanhos exigidos (1280×720 e 320×568, em `playwright.config.js`). Dado inventado: o envio sai da API com um GeoJSON
// sintético, e os estados de erro e de carregamento vêm de `page.route`, então nenhum teste grava dado de negócio além do envio.
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel } = require('./apoio.js');

const ENVIO_INEXISTENTE = '00000000-0000-0000-0000-000000000001';
const ARQUIVO_SINTETICO = Buffer.from(JSON.stringify({
  type: 'FeatureCollection',
  features: [{ type: 'Feature', properties: { valor: 1 }, geometry: { type: 'Point', coordinates: [-48.3, -10.7] } }],
}));
const RESPOSTA_DA_PREVIA = {
  formato: 'GeoJSON', tipo: 'Point', sistema: 'WGS 84', origem_sistema: 'formato', transformacao: 'equivalencia',
  avisos: [], contagem: 1, colunas: ['<img src=x onerror="alert(1)">'], nos_sugeridos: [null],
};

const FAZENDA = dados.fazendas_a[0];
const urlDaFazenda = (sufixo) => `/empresa/${dados.empresa_a}/fazenda/${FAZENDA}/${sufixo}`;

async function conferirTela(pagina) {
  await semRolagemHorizontal(pagina);
  await acessivel(pagina);
}

// O envio nasce pela API, com o token CSRF da própria tela de envio (o mesmo que `camadas.js` usa).
async function criarEnvio(pagina, conteudo = ARQUIVO_SINTETICO) {
  await pagina.goto(urlDaFazenda('camadas/novo'));
  const token = await pagina.locator('#formulario-envio input[name="csrfmiddlewaretoken"]').inputValue();
  const resposta = await pagina.request.post(`/api/v1/fazendas/${FAZENDA}/envios`, {
    headers: { 'X-CSRFToken': token },
    multipart: { arquivo: { name: 'camada-sintetica.geojson', mimeType: 'application/geo+json', buffer: conteudo } },
  });
  expect(resposta.status()).toBe(201);
  return (await resposta.json()).envio_id;
}

// Responde só as leituras da prévia (GET); o resto segue para a rede real.
function mockarPrevia(pagina, responder) {
  return pagina.route(/\/api\/v1\/envios\/[^/]+$/, (rota) => {
    if (rota.request().method() !== 'GET') return rota.continue();
    return responder(rota);
  });
}

test('envio: a tela de escolha de arquivo aparece e passa no axe', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(urlDaFazenda('camadas/novo'));
  await expect(page.locator('#formulario-envio')).toBeVisible();
  await conferirTela(page);
});

test('prévia real: o envio criado pela API mostra o resumo', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  const envioId = await criarEnvio(page);
  await page.goto(urlDaFazenda(`camadas/envio/${envioId}`));
  await expect(page.locator('#previa-conteudo')).toBeVisible();
  await expect(page.locator('#previa-resumo')).toContainText('Feições');
  await conferirTela(page);
});

// Ponto e linha desenham na prévia sem erro (o mapa aceita os tipos GeoJSON, e o validador continua estrito).
const GEOMETRIAS_SINTETICAS = {
  ponto: { type: 'Point', coordinates: [-48.3, -10.7] },
  linha: { type: 'LineString', coordinates: [[-48.31, -10.71], [-48.29, -10.69], [-48.28, -10.68]] },
};
for (const [nome, geometria] of Object.entries(GEOMETRIAS_SINTETICAS)) {
  test(`${nome}: a prévia desenha no mapa sem erro na região de camadas`, async ({ page }) => {
    await entrar(page, dados.administradora_a.cpf);
    const conteudo = Buffer.from(JSON.stringify({ type: 'FeatureCollection', features: [{ type: 'Feature', properties: { valor: 1 }, geometry: geometria }] }));
    const envioId = await criarEnvio(page, conteudo);
    await page.goto(urlDaFazenda(`camadas/envio/${envioId}`));
    await expect(page.locator('[data-mapa-pronto]')).toHaveCount(1);
    await expect(page.locator('[data-estado-de="camadas"]')).not.toContainText('Não foi possível carregar as camadas.');
    await conferirTela(page);
  });
}

test('carregando: a prévia mostra o aviso enquanto a API não responde', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  const envioId = await criarEnvio(page);
  await mockarPrevia(page, () => {}); // a resposta nunca chega: o aviso de carregamento fica na tela
  await page.goto(urlDaFazenda(`camadas/envio/${envioId}`));
  await expect(page.getByText('Carregando a prévia…')).toBeVisible();
  await conferirTela(page);
});

test('vazio: fazenda sem estudo mostra o estado vazio na publicação, sem formulário', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  const envioId = await criarEnvio(page);
  await page.goto(urlDaFazenda(`camadas/envio/${envioId}/publicar`));
  await expect(page.getByText('não tem estudo cadastrado')).toBeVisible();
  await expect(page.locator('#formulario-publicacao')).toHaveCount(0);
  await conferirTela(page);
});

// O envio vencido é preparado antes da rodada (`navegador/preparar-camadas.py`, `manage.py shell`): a tela não cria nem
// envelhece envio por conta própria. O id vem de `dados.camadas.envio_vencido`.
test('expirado: envio vencido mostra o aviso, sem prévia nem formulário', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(urlDaFazenda(`camadas/envio/${dados.camadas.envio_vencido}`));
  await expect(page.getByText('Este envio expirou. Envie o arquivo de novo.')).toBeVisible();
  await expect(page.locator('[data-api-previa]')).toHaveCount(0);
  await conferirTela(page);
});

test('erro: falha da API vira aviso de erro na tela, sem prévia', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  const envioId = await criarEnvio(page);
  await mockarPrevia(page, (rota) => rota.fulfill({ status: 500, contentType: 'application/json', body: '{}' }));
  await page.goto(urlDaFazenda(`camadas/envio/${envioId}`));
  await expect(page.locator('#previa-erro')).toBeVisible();
  await expect(page.locator('#previa-erro')).toContainText('Não foi possível concluir. Tente de novo.');
  await expect(page.locator('#previa-conteudo')).toBeHidden();
  await conferirTela(page);
});

test('marcação vinda do arquivo aparece como texto escapado', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  const envioId = await criarEnvio(page);
  await mockarPrevia(page, (rota) => rota.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RESPOSTA_DA_PREVIA) }));
  await page.goto(urlDaFazenda(`camadas/envio/${envioId}`));
  await expect(page.locator('#previa-colunas')).toContainText('<img src=x onerror="alert(1)">');
  await expect(page.locator('#previa-colunas img')).toHaveCount(0);
  await conferirTela(page);
});

test('sem permissão: quem não publica recebe 404 por URL direta, sem texto técnico', async ({ page }) => {
  await entrar(page, dados.sem_acesso.cpf);
  const resposta = await page.goto(urlDaFazenda('camadas/novo'));
  expect(resposta.status()).toBe(404);
  await expect(page.getByText('object (')).toHaveCount(0);
  await conferirTela(page);
});

test('envio inexistente por URL direta: 404 igual ao de envio alheio', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  const resposta = await page.goto(urlDaFazenda(`camadas/envio/${ENVIO_INEXISTENTE}`));
  expect(resposta.status()).toBe(404);
  await expect(page.getByText('object (')).toHaveCount(0);
});
