import test from 'node:test';
import assert from 'node:assert/strict';
import { criarSessao, urlDosTiles, msAteRenovar, buscarAtribuicao, criarFundo, esperaAposFalha, limitesParaViewport, ORIGEM, ID_FONTE, TENTATIVAS_MAXIMAS, ESPERA_MAXIMA_MS } from './fundo-google.js';

const CHAVE = 'chave-de-teste';
const resposta = (corpo, ok = true, status = 200) => ({ ok, status, json: async () => corpo });
const sessaoOk = { session: 'tok1', expiry: '2000000000', tileWidth: 256, tileHeight: 256, imageFormat: 'jpeg' };

test('criarSessao: POST com o corpo exigido e leitura de session/expiry', async () => {
  const chamadas = [];
  const buscar = async (url, opcoes) => { chamadas.push({ url, opcoes }); return resposta(sessaoOk); };
  const sessao = await criarSessao(buscar, CHAVE);
  assert.deepEqual(sessao, { token: 'tok1', expira: 2000000000, largura: 256 });
  assert.equal(chamadas[0].url, `${ORIGEM}/v1/createSession?key=${CHAVE}`);
  assert.equal(chamadas[0].opcoes.method, 'POST');
  const corpo = JSON.parse(chamadas[0].opcoes.body);
  assert.deepEqual([corpo.mapType, corpo.language, corpo.region], ['satellite', 'pt-BR', 'BR']);
});

test('criarSessao: recusa resposta com erro, sem token ou sem expiry (dado externo)', async () => {
  await assert.rejects(criarSessao(async () => resposta({}, false, 403), CHAVE), /403/);
  await assert.rejects(criarSessao(async () => resposta({ expiry: '1' }), CHAVE), /fora da forma/);
  await assert.rejects(criarSessao(async () => resposta({ session: '', expiry: '1' }), CHAVE), /fora da forma/);
  await assert.rejects(criarSessao(async () => resposta({ session: 'x', expiry: 'abc' }), CHAVE), /fora da forma/);
  await assert.rejects(criarSessao(async () => resposta(null), CHAVE), /fora da forma/);
});

test('urlDosTiles: placeholders z/x/y intactos e sessão codificada', () => {
  const url = urlDosTiles({ token: 'a b&c' }, CHAVE);
  assert.ok(url.startsWith(`${ORIGEM}/v1/2dtiles/{z}/{x}/{y}?`));
  assert.ok(url.includes('session=a+b%26c'));
});

test('msAteRenovar: antes do vencimento, nunca negativa, nunca acima do teto do temporizador', () => {
  assert.equal(msAteRenovar({ expira: 10000 }, 0), (10000 - 3600) * 1000);
  assert.equal(msAteRenovar({ expira: 100 }, 1e9), 0); // já vencida
  assert.equal(msAteRenovar({ expira: 1e12 }, 0), 2 ** 31 - 1);
});

test('buscarAtribuicao: devolve o copyright; erro e forma errada não viram texto inventado', async () => {
  const caixa = { norte: 1, sul: -1, leste: 2, oeste: -2, zoom: 12.4 };
  let pedido;
  const texto = await buscarAtribuicao(async (u) => { pedido = u; return resposta({ copyright: 'Imagens © 2026' }); }, CHAVE, { token: 't' }, caixa);
  assert.equal(texto, 'Imagens © 2026');
  assert.ok(pedido.includes('/tile/v1/viewport?') && pedido.includes('zoom=12') && pedido.includes('north=1'));
  assert.equal(await buscarAtribuicao(async () => resposta({}), CHAVE, { token: 't' }, caixa), '');
  await assert.rejects(buscarAtribuicao(async () => resposta({}, false, 500), CHAVE, { token: 't' }, caixa), /500/);
});

test('limitesParaViewport: vista maior que o mundo vira o mundo todo, longitude volta ao intervalo, latitude é presa', () => {
  const mundo = limitesParaViewport({ norte: 95, sul: -95, leste: 400, oeste: -300 });
  assert.deepEqual(mundo, { norte: 89.999, sul: -89.999, leste: 179.999, oeste: -179.999 });
  const deslocada = limitesParaViewport({ norte: 1, sul: -1, leste: 190, oeste: 170 }); // cruza o antimeridiano
  assert.equal(deslocada.oeste, 170);
  assert.equal(deslocada.leste, -170);
  assert.deepEqual(limitesParaViewport({ norte: 1, sul: -1, leste: 2, oeste: -2 }), { norte: 1, sul: -1, leste: 2, oeste: -2 });
  for (const v of [-720, -181, 0, 180, 181, 720]) {
    const l = limitesParaViewport({ norte: 0, sul: 0, leste: v, oeste: v });
    assert.ok(l.leste > -180 && l.leste < 180, String(v));
  }
});

test('buscarAtribuicao pede com longitudes dentro do intervalo e com prazo', async () => {
  let pedido;
  let opcoes;
  await buscarAtribuicao(async (u, o) => { pedido = u; opcoes = o; return resposta({ copyright: 'x' }); }, CHAVE, { token: 't' }, { norte: 1, sul: -1, leste: 500, oeste: -500, zoom: 1 });
  assert.ok(pedido.includes('east=179.999') && pedido.includes('west=-179.999'));
  assert.ok(opcoes.signal instanceof AbortSignal);
});

test('criarFundo: primeira busca de crédito que falha é repetida com espera crescente, sem mapa em movimento', async () => {
  let viewport = 0;
  const buscar = async (url) => {
    if (url.includes('createSession')) return resposta(sessaoOk);
    viewport += 1;
    return viewport < 3 ? resposta({}, false, 503) : resposta({ copyright: 'Imagens © 2026' });
  };
  const agendados = [];
  const fundo = await criarFundo({ chave: CHAVE, buscar, relogio: { setTimeout: (f, ms) => agendados.push({ f, ms }) } });
  const dados = { textContent: '' };
  fundo.aoCriarMapa(mapaFalso(), { dados });
  await new Promise((r) => setImmediate(r));
  assert.equal(dados.textContent, '');
  assert.deepEqual(agendados.map((a) => a.ms).slice(1), [30000]); // [0] é a renovação da sessão
  await agendados[1].f();
  assert.deepEqual(agendados.map((a) => a.ms).slice(1), [30000, 60000]);
  await agendados[2].f();
  assert.equal(dados.textContent, 'Imagens © 2026');
  assert.equal(agendados.length, 3); // sucesso: não agenda mais
});

function mapaFalso() {
  const fonte = { tiles: null, setTiles(t) { this.tiles = t; } };
  const ouvintes = {};
  return {
    fonte, ouvintes,
    getSource: (id) => (id === ID_FONTE ? fonte : undefined),
    getBounds: () => ({ getNorth: () => 1, getSouth: () => -1, getEast: () => 2, getWest: () => -2 }),
    getZoom: () => 12,
    on: (evento, f) => { ouvintes[evento] = f; },
  };
}

test('criarFundo: fonte raster, camada acima do neutro e atribuição escrita como texto', async () => {
  const buscar = async (url) => (url.includes('createSession') ? resposta(sessaoOk) : resposta({ copyright: '<img src=x onerror=alert(1)>' }));
  const agendados = [];
  const fundo = await criarFundo({ chave: CHAVE, buscar, relogio: { setTimeout: (f, ms) => agendados.push({ f, ms }) } });
  assert.equal(fundo.fontes[ID_FONTE].type, 'raster');
  assert.deepEqual(fundo.camadas.map((c) => c.source), [ID_FONTE]);
  const dados = { textContent: '' };
  const mapa = mapaFalso();
  fundo.aoCriarMapa(mapa, { dados });
  await new Promise((r) => setImmediate(r));
  assert.equal(dados.textContent, '<img src=x onerror=alert(1)>'); // textContent: o navegador não interpreta
  assert.equal(agendados.length, 1);
  assert.equal(typeof mapa.ouvintes.moveend, 'function');
});

test('criarFundo: renova a sessão antes de expirar e troca os tiles da fonte', async () => {
  let n = 0;
  const buscar = async (url) => (url.includes('createSession') ? resposta({ ...sessaoOk, session: `tok${++n}` }) : resposta({ copyright: '' }));
  const agendados = [];
  const fundo = await criarFundo({ chave: CHAVE, buscar, relogio: { setTimeout: (f, ms) => agendados.push({ f, ms }) } });
  const mapa = mapaFalso();
  fundo.aoCriarMapa(mapa, { dados: { textContent: '' } });
  await agendados[0].f();
  assert.ok(mapa.fonte.tiles[0].includes('session=tok2'));
  assert.equal(agendados.length, 2); // reagendou
});

test('esperaAposFalha dobra a cada falha e para no teto', () => {
  assert.deepEqual([1, 2, 3].map(esperaAposFalha), [30000, 60000, 120000]);
  assert.equal(esperaAposFalha(50), ESPERA_MAXIMA_MS);
});

test('criarFundo: renovação que falha não derruba o mapa, espera cada vez mais e para no limite', async () => {
  let primeira = true;
  const buscar = async (url) => {
    if (!url.includes('createSession')) return resposta({ copyright: '' });
    if (primeira) { primeira = false; return resposta(sessaoOk); }
    return resposta({}, false, 503);
  };
  const agendados = [];
  const fundo = await criarFundo({ chave: CHAVE, buscar, relogio: { setTimeout: (f, ms) => agendados.push({ f, ms }) } });
  const mapa = mapaFalso();
  fundo.aoCriarMapa(mapa, { dados: { textContent: '' } });
  for (let i = 0; i < TENTATIVAS_MAXIMAS + 2 && agendados[i]; i += 1) await agendados[i].f();
  assert.equal(mapa.fonte.tiles, null);
  assert.deepEqual(agendados.slice(1).map((a) => a.ms), [30000, 60000, 120000, 240000]); // nunca zero: sem rajada de pedidos
  assert.equal(agendados.length, TENTATIVAS_MAXIMAS); // 1 agendamento inicial + 4 esperas; parou
});

test('criarFundo: falha ao buscar a atribuição mantém o crédito já exibido', async () => {
  let viewport = 0;
  const buscar = async (url) => {
    if (url.includes('createSession')) return resposta(sessaoOk);
    viewport += 1;
    return viewport === 1 ? resposta({ copyright: 'Imagens © 2026' }) : resposta({}, false, 500);
  };
  const fundo = await criarFundo({ chave: CHAVE, buscar, relogio: { setTimeout: () => {} } });
  const dados = { textContent: '' };
  const mapa = mapaFalso();
  fundo.aoCriarMapa(mapa, { dados });
  await new Promise((r) => setImmediate(r));
  assert.equal(dados.textContent, 'Imagens © 2026');
  await mapa.ouvintes.moveend();
  assert.equal(dados.textContent, 'Imagens © 2026');
});

test('criarSessao: tileWidth inválido é recusado, ausente cai no padrão e a requisição leva prazo', async () => {
  const comLargura = (tileWidth) => async () => resposta({ session: 's', expiry: '1', tileWidth });
  await assert.rejects(criarSessao(comLargura(-256), CHAVE), /tileWidth/);
  await assert.rejects(criarSessao(comLargura(0), CHAVE), /tileWidth/);
  await assert.rejects(criarSessao(comLargura('x'), CHAVE), /tileWidth/);
  assert.equal((await criarSessao(comLargura(undefined), CHAVE)).largura, 256);
  let sinal;
  await criarSessao(async (_u, o) => { sinal = o.signal; return resposta(sessaoOk); }, CHAVE);
  assert.ok(sinal instanceof AbortSignal);
});

test('criarFundo: sessão recusada na criação rejeita (o mapa.js cai para o fundo neutro)', async () => {
  await assert.rejects(criarFundo({ chave: CHAVE, buscar: async () => resposta({}, false, 403), relogio: {} }), /403/);
});
