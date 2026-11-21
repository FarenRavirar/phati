'use strict';
// Testes de navegador da tela de camadas do Administrador (008 T4.2; R18, R21; A8): envio, prévia e publicação, nos dois
// tamanhos exigidos (1280×720 e 320×568, em `playwright.config.js`). Dado inventado: o envio sai da API com um GeoJSON
// sintético, e os estados de erro e de carregamento vêm de `page.route`, então nenhum teste grava dado de negócio além do envio.
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel, turmaDe } = require('./apoio.js');

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

// Caminho pela interface (T4.2, B): o formulário de envio, a prévia, a publicação e a versão criada. A fazenda A3 tem estudo
// (`popular_sintetico`); a A1 segue sem, para o estado vazio. Nome de camada com sufixo: a publicação recusa nome repetido.
const FAZENDA_COM_ESTUDO = dados.fazendas_a[2];
const urlDaFazendaComEstudo = (sufixo) => `/empresa/${dados.empresa_a}/fazenda/${FAZENDA_COM_ESTUDO}/${sufixo}`;
const GEOJSON_DE_POLIGONO = Buffer.from(JSON.stringify({
  type: 'FeatureCollection',
  features: [{ type: 'Feature', properties: { valor: 1, obs: 'sintetico' }, geometry: { type: 'Polygon', coordinates: [[[-48.31, -10.71], [-48.29, -10.71], [-48.29, -10.69], [-48.31, -10.69], [-48.31, -10.71]]] } }],
}));

test('pela interface: envia o arquivo, vê a prévia, publica e a versão fica em análise', async ({ page }, informacoes) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(urlDaFazendaComEstudo('camadas/novo'));
  await page.locator('#campo_arquivo').setInputFiles({ name: 'camada-sintetica.geojson', mimeType: 'application/geo+json', buffer: GEOJSON_DE_POLIGONO });
  await page.locator('#enviar').click();
  await page.waitForURL(/\/camadas\/envio\/[0-9a-f-]{36}$/);
  await expect(page.locator('#previa-conteudo')).toBeVisible();
  await expect(page.locator('#previa-resumo')).toContainText('Feições');
  await expect(page.locator('[data-mapa-pronto]')).toHaveCount(1);
  await page.getByRole('link', { name: 'Ir para a publicação' }).click();
  await expect(page.locator('#formulario-publicacao')).toBeVisible();
  await page.locator('#campo_nome').fill(`Camada ${informacoes.project.name} ${Date.now()}`);
  await page.locator('#campo_tema').fill('Tema sintético'); // igual ao tema do estudo: a publicação recusa tema diferente
  await page.locator('#campo_origem').fill('Levantamento sintético');
  await page.locator('#campo_sistema_confirmado').check();
  await page.getByRole('button', { name: 'Publicar em análise' }).click();
  await expect(page.locator('#publicacao-sucesso')).toContainText('Versão 1 criada em análise.');
  await conferirTela(page);
});

test('envio inválido: o erro aparece na tela, a página segue no formulário e sem rolagem', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(urlDaFazendaComEstudo('camadas/novo'));
  await page.locator('#campo_arquivo').setInputFiles({ name: 'vazio.geojson', mimeType: 'application/geo+json', buffer: Buffer.from('') });
  await page.locator('#enviar').click();
  await expect(page.locator('#aviso-envio')).toBeVisible();
  await expect(page.locator('#aviso-envio .aviso-texto')).not.toHaveText('');
  await expect(page).toHaveURL(/\/camadas\/novo$/);
  await expect(page.locator('#formulario-envio')).toBeVisible();
  await conferirTela(page);
});

// Revisão de nós (R7, T4.1): a feição que cruza dois nós aparece na lista com a sugestão; a fora de todos os nós fica na
// própria fazenda sem escolha. As coordenadas vêm do seed (`dados.camadas`), não do spec.
function geojsonDeRevisao(aneis) {
  return Buffer.from(JSON.stringify({
    type: 'FeatureCollection',
    features: aneis.map((anel) => ({ type: 'Feature', properties: { valor: 1, obs: 'sintetico' }, geometry: { type: 'Polygon', coordinates: [anel] } })),
  }));
}

async function enviarEPrevia(page, conteudo) {
  await page.goto(urlDaFazendaComEstudo('camadas/novo'));
  await page.locator('#campo_arquivo').setInputFiles({ name: 'revisao.geojson', mimeType: 'application/geo+json', buffer: conteudo });
  await page.locator('#enviar').click();
  await page.waitForURL(/\/camadas\/envio\/[0-9a-f-]{36}$/);
  await expect(page.locator('#previa-conteudo')).toBeVisible();
  await expect(page.locator('[data-mapa-pronto]')).toHaveCount(1);
  await page.getByRole('link', { name: 'Ir para a publicação' }).click();
  await expect(page.locator('#formulario-publicacao')).toBeVisible();
}

async function preencherEPublicar(page, informacoes) {
  await page.locator('#campo_nome').fill(`Camada ${informacoes.project.name} ${Date.now()}`);
  await page.locator('#campo_tema').fill('Tema sintético');
  await page.locator('#campo_origem').fill('Levantamento sintético');
  await page.locator('#campo_sistema_confirmado').check();
  await page.getByRole('button', { name: 'Publicar em análise' }).click();
}

test('trocar nó e publicar: a feição que cruza dois nós recebe o nó escolhido na lista', async ({ page }, informacoes) => {
  await entrar(page, dados.administradora_a.cpf);
  await enviarEPrevia(page, geojsonDeRevisao([dados.camadas.cruza]));
  await expect(page.locator('#revisao-nos li')).toHaveCount(1);
  await conferirTela(page); // com a revisão aberta: axe (rótulo ligado ao select) e sem rolagem horizontal
  await page.locator('#revisao_no_1').selectOption({ label: 'Talhão A3-2' });
  await preencherEPublicar(page, informacoes);
  await expect(page.locator('#publicacao-sucesso')).toContainText('Versão 1 criada em análise.');
  await conferirTela(page);
});

test('fora de nós: a feição fica na própria fazenda e publica sem escolher', async ({ page }, informacoes) => {
  await entrar(page, dados.administradora_a.cpf);
  await enviarEPrevia(page, geojsonDeRevisao([dados.camadas.fora]));
  await expect(page.locator('#revisao_no_1')).toHaveValue('');
  await preencherEPublicar(page, informacoes);
  await expect(page.locator('#publicacao-sucesso')).toContainText('Versão 1 criada em análise.');
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

// O envio vencido nasce no `popular_sintetico` (mesmo dado de todo navegador, `dados.camadas.envio_vencido`); a tela não o cria.
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

// Entrada pela página da fazenda (P2 navegação): a ação "Publicar camada" leva à tela de envio; quem não publica não a vê.
test('a página da fazenda leva à publicação pela ação, e quem não publica não vê o link', async ({ page }, informacoes) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto(urlDaFazendaComEstudo(''));
  await page.getByRole('link', { name: 'Publicar camada' }).click();
  await expect(page).toHaveURL(/\/camadas\/novo$/);
  await expect(page.locator('#formulario-envio')).toBeVisible();
  await conferirTela(page);
  await page.context().clearCookies();
  await entrar(page, turmaDe(informacoes).usuaria.cpf);
  await page.goto(urlDaFazenda(''));
  await expect(page.getByRole('link', { name: 'Publicar camada' })).toHaveCount(0);
  await conferirTela(page);
});
