// Fundo próprio (004b R7, R8, A7): forma devolvida, estilo compartilhado com o aplicativo, URL do protocolo e caminhos infelizes. Sem rede.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ESTILO = JSON.parse(fs.readFileSync(path.join(__dirname, 'estilo_base.json'), 'utf8'));
const ORIGEM = 'http://127.0.0.1:8080';
const URL_FUNDO = '/empresa/1/fazenda/2/pacote/arquivo/fundo.pmtiles?versao=3';
const URL_ORTO = '/empresa/1/fazenda/2/pacote/arquivo/ortofoto.pmtiles?versao=3';

const carregar = () => import('./fundo-aberto.js');

test('o fundo aberto tem uma fonte vetorial por PMTiles na rota do pacote, sem atribuição no motor', async () => {
  const { fundoAberto } = await carregar();
  const { fontes } = fundoAberto({ estilo: ESTILO, url: URL_FUNDO, origem: ORIGEM });
  assert.deepEqual(Object.keys(fontes), ['fundo']);
  assert.equal(fontes.fundo.type, 'vector');
  assert.equal(fontes.fundo.url, `pmtiles://${ORIGEM}${URL_FUNDO}`);
  assert.equal(fontes.fundo.attribution, undefined); // a atribuição fica no <p> da página (A7)
});

test('as camadas do fundo saem do estilo compartilhado e a ortofoto não entra nelas', async () => {
  const { fundoAberto } = await carregar();
  const { camadas } = fundoAberto({ estilo: ESTILO, url: URL_FUNDO, origem: ORIGEM });
  assert.deepEqual(camadas.map((c) => c.id), ['fundo-cor', 'fundo-terra', 'fundo-estrada']);
  assert.ok(camadas.every((c) => c.type !== 'raster'));
});

test('a ortofoto é uma camada raster desligada com prefixo de camada do produto, tamanho de tile do estilo e sem alterar o estilo lido', async () => {
  const { ortofoto, ID_ORTOFOTO } = await carregar();
  const antes = JSON.stringify(ESTILO);
  const { fontes, camadas } = ortofoto({ estilo: ESTILO, url: URL_ORTO, origem: ORIGEM });
  assert.equal(ID_ORTOFOTO, 'camada-ortofoto');
  assert.equal(fontes.ortofoto.type, 'raster');
  assert.equal(fontes.ortofoto.tileSize, ESTILO.sources.ortofoto.tileSize);
  assert.equal(fontes.ortofoto.url, `pmtiles://${ORIGEM}${URL_ORTO}`);
  assert.equal(camadas.length, 1);
  assert.equal(camadas[0].id, ID_ORTOFOTO);
  assert.equal(camadas[0].layout.visibility, 'none');
  assert.equal(JSON.stringify(ESTILO), antes);
});

test('nenhum endereço do pacote cita o Google e nenhuma fonte usa o protocolo de arquivo local do aplicativo', async () => {
  const { fundoAberto, ortofoto } = await carregar();
  const texto = JSON.stringify([fundoAberto({ estilo: ESTILO, url: URL_FUNDO, origem: ORIGEM }), ortofoto({ estilo: ESTILO, url: URL_ORTO, origem: ORIGEM })]);
  assert.ok(!/google/i.test(texto));
  assert.ok(!texto.includes('file://'));
});

test('estilo fora da forma é recusado: sem fonte, sem versão, camada sem id', async () => {
  const { validarEstilo } = await carregar();
  assert.throws(() => validarEstilo(null), /estilo base/);
  assert.throws(() => validarEstilo({ ...ESTILO, version: 7 }), /estilo base/);
  assert.throws(() => validarEstilo({ ...ESTILO, sources: {} }), /estilo base/);
  assert.throws(() => validarEstilo({ ...ESTILO, sources: { ...ESTILO.sources, fundo: { type: 'raster' } } }), /estilo base/);
  assert.throws(() => validarEstilo({ ...ESTILO, layers: [{ type: 'fill' }] }), /sem id ou tipo/);
});

test('estilo sem a camada da ortofoto é recusado', async () => {
  const { ortofoto } = await carregar();
  const semOrtofoto = { ...ESTILO, layers: ESTILO.layers.filter((c) => c.type !== 'raster') };
  assert.throws(() => ortofoto({ estilo: semOrtofoto, url: URL_ORTO, origem: ORIGEM }), /sem a camada da ortofoto/);
});

test('o endereço do protocolo é sempre absoluto, e endereço relativo parte da origem da página', async () => {
  const { urlDoProtocolo } = await carregar();
  assert.equal(urlDoProtocolo('/a/b.pmtiles?versao=1', 'https://x.test'), 'pmtiles://https://x.test/a/b.pmtiles?versao=1');
  assert.throws(() => urlDoProtocolo('/a', 'sem-origem'), TypeError);
});

test('a data da ortofoto aparece em dia/mês/ano e texto estranho volta como veio', async () => {
  const { dataPtBr } = await carregar();
  assert.equal(dataPtBr('2026-01-15'), '15/01/2026');
  assert.equal(dataPtBr(''), '');
  assert.equal(dataPtBr(undefined), '');
  assert.equal(dataPtBr('15 de janeiro'), '15 de janeiro');
});

test('sem data-pacote-fundo ou sem o estilo não há pacote; sem ortofoto o pacote só leva o fundo', async () => {
  const { pacoteDaPagina } = await carregar();
  assert.equal(pacoteDaPagina({}), null);
  assert.equal(pacoteDaPagina(undefined), null);
  assert.equal(pacoteDaPagina({ pacoteFundo: URL_FUNDO }), null);
  const so = pacoteDaPagina({ pacoteFundo: URL_FUNDO, pacoteEstilo: '/estilo.json', pacoteAtribuicao: '© OSM' });
  assert.deepEqual(so, { estilo: '/estilo.json', fundo: { url: URL_FUNDO, atribuicao: '© OSM' }, ortofoto: null });
  const com = pacoteDaPagina({ pacoteFundo: URL_FUNDO, pacoteEstilo: '/e', pacoteOrtofoto: URL_ORTO, pacoteOrtofotoData: '2026-01-15' });
  assert.equal(com.ortofoto.url, URL_ORTO);
  assert.equal(com.ortofoto.capturadaEm, '2026-01-15');
});

test('o protocolo pmtiles é registrado uma vez no motor; sem a biblioteca, falha com mensagem', async () => {
  const { registrarProtocolo } = await carregar();
  const chamadas = [];
  class Protocolo { constructor() { this.tilev4 = () => {}; } }
  const protocolo = registrarProtocolo({ addProtocol: (...a) => chamadas.push(a) }, { Protocol: Protocolo });
  assert.equal(chamadas.length, 1);
  assert.equal(chamadas[0][0], 'pmtiles');
  assert.equal(chamadas[0][1], protocolo.tilev4);
  assert.throws(() => registrarProtocolo({ addProtocol() {} }, undefined), /biblioteca PMTiles ausente/);
  assert.throws(() => registrarProtocolo({ addProtocol() {} }, {}), /biblioteca PMTiles ausente/);
});

test('erro de fonte do pacote é reconhecido pelo id, com ou sem tile; fonte do produto e erro sem fonte, não', async () => {
  const { erroDeFontePropria } = await carregar();
  assert.equal(erroDeFontePropria({ sourceId: 'fundo' }), true);
  assert.equal(erroDeFontePropria({ sourceId: 'ortofoto', tile: {} }), true);
  assert.equal(erroDeFontePropria({ sourceId: 'camadas' }), false);
  assert.equal(erroDeFontePropria({ error: new Error('x') }), false);
  assert.equal(erroDeFontePropria(undefined), false);
});
