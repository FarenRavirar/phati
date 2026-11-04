// Adaptador do mapa (004 R15, T1.7): lógica pura, sem MapLibre nem DOM. O MapLibre real roda em `navegador/mapa.spec.js`.
const test = require('node:test');
const assert = require('node:assert/strict');

test('importar o módulo no Node não carrega o MapLibre nem exige DOM', async () => {
  const mapa = await import('./mapa.js');
  for (const nome of ['CENTRO_INICIAL', 'ZOOM_INICIAL', 'criarMapa', 'esconderAviso', 'montarEstilo', 'mostrarErro', 'moverNaOrdem', 'ordenarConsulta', 'pedirPosicao']) {
    assert.ok(nome in mapa, nome);
  }
});

test('o estilo é o fundo abaixo de tudo, na versão 8 da especificação', async () => {
  const { montarEstilo } = await import('./mapa.js');
  const { fundo } = await import('./fundo-neutro.js');
  assert.deepEqual(montarEstilo(fundo()), { version: 8, sources: {}, layers: fundo().camadas });
});

test('aceita qualquer fundo com a forma {fontes, camadas}, não só o neutro', async () => {
  const { montarEstilo } = await import('./mapa.js');
  const outro = { fontes: { x: { type: 'raster', tiles: ['t'] } }, camadas: [{ id: 'x', type: 'raster', source: 'x' }] };
  const estilo = montarEstilo(outro);
  assert.deepEqual(Object.keys(estilo.sources), ['x']);
  assert.equal(estilo.layers[0].id, 'x');
});

test('fundo fora da forma é erro, não mapa em branco', async () => {
  const { montarEstilo } = await import('./mapa.js');
  for (const ruim of [undefined, null, {}, { fontes: {} }, { fontes: null, camadas: [] }, { fontes: {}, camadas: 'x' }, { fontes: {}, camadas: {} }]) {
    assert.throws(() => montarEstilo(ruim), /fora da forma/);
  }
});

test('criarMapa entrega ao motor o elemento, o estilo e o centro perto de (0°, 0°)', async () => {
  const { criarMapa, CENTRO_INICIAL, ZOOM_INICIAL } = await import('./mapa.js');
  const { fundo } = await import('./fundo-neutro.js');
  let recebido;
  class Falso { constructor(opcoes) { recebido = opcoes; } }
  const elemento = {};
  criarMapa({ Map: Falso }, elemento, fundo());
  assert.equal(recebido.container, elemento);
  assert.equal(recebido.style.version, 8);
  assert.deepEqual(recebido.center, CENTRO_INICIAL);
  assert.equal(recebido.zoom, ZOOM_INICIAL);
  assert.ok(Math.abs(CENTRO_INICIAL[0]) < 1 && Math.abs(CENTRO_INICIAL[1]) < 1);
});

test('mostrarErro marca o mapa e revela o aviso da região; sem aviso, só marca', async () => {
  const { mostrarErro } = await import('./mapa.js');
  const aviso = { hidden: true };
  const elemento = { dataset: {}, parentElement: { querySelector: (seletor) => (seletor === '[data-mapa-aviso]' ? aviso : null) } };
  mostrarErro(elemento);
  assert.equal(elemento.dataset.mapaErro, 'sim');
  assert.equal(aviso.hidden, false);
  const sozinho = { dataset: {}, parentElement: null };
  mostrarErro(sozinho);
  assert.equal(sozinho.dataset.mapaErro, 'sim');
});

test('esconderAviso some com o aviso e mostrarErro o traz de volta; sem aviso nenhum dos dois quebra', async () => {
  const { esconderAviso, mostrarErro } = await import('./mapa.js');
  const caixa = { hidden: false };
  const elemento = { dataset: {}, parentElement: { querySelector: () => caixa } };
  esconderAviso(elemento);
  assert.equal(caixa.hidden, true);
  mostrarErro(elemento);
  assert.equal(caixa.hidden, false);
  esconderAviso({ dataset: {}, parentElement: null });
});

// ---- Fase 2: camadas, ordem, transparência, consulta e posição ------------------------------------------------------

const FICHA = { atributo: 'a', valor: 'v', fonte: 'f', data: 'd', situacao: 's', ressalva: 'r', origem: 'o', metodo: 'm' };
const feicao = (id, camada_id, extra = {}) => ({ type: 'Feature', id, geometry: { type: 'Polygon', coordinates: [[[1, 2], [3, 2], [3, 4], [1, 2]]] }, properties: { ...FICHA, camada_id, camada: camada_id.toUpperCase(), cor: '--c', ...extra } });

test('validarColecao aceita FeatureCollection e recusa o que foge da forma', async () => {
  const { validarColecao } = await import('./mapa.js');
  const boa = { type: 'FeatureCollection', features: [feicao(1, 'a')] };
  assert.equal(validarColecao(boa), boa);
  for (const ruim of [null, 'x', {}, { type: 'FeatureCollection' }, { type: 'Feature', features: [] },
    { type: 'FeatureCollection', features: [{ properties: null }] },
    { type: 'FeatureCollection', features: [{ properties: { camada_id: 'a', camada: 'A' } }] }]) {
    assert.throws(() => validarColecao(ruim), /fora da forma|sem camada_id/);
  }
});

test('validarColecao confere a geometria e todos os campos que a ficha mostra', async () => {
  const { validarColecao, CAMPOS_DA_FICHA } = await import('./mapa.js');
  const com = (mudar) => { const f = feicao(1, 'a'); mudar(f); return { type: 'FeatureCollection', features: [f] }; };
  assert.throws(() => validarColecao(com((f) => { delete f.geometry; })), /geometria Polygon/);
  assert.throws(() => validarColecao(com((f) => { f.geometry = { type: 'Point', coordinates: [1, 2] }; })), /geometria Polygon/);
  assert.throws(() => validarColecao(com((f) => { f.geometry.coordinates = []; })), /geometria Polygon/);
  assert.throws(() => validarColecao(com((f) => { f.geometry.coordinates = [[[1, 2], [3, 4]]]; })), /geometria Polygon/); // anel curto
  assert.throws(() => validarColecao(com((f) => { f.geometry.coordinates[0][0] = [999, 2]; })), /geometria Polygon/); // fora de WGS 84
  assert.throws(() => validarColecao(com((f) => { f.geometry.coordinates[0][1] = ['3', 2]; })), /geometria Polygon/); // texto no lugar de número
  for (const campo of CAMPOS_DA_FICHA) {
    assert.throws(() => validarColecao(com((f) => { delete f.properties[campo]; })), new RegExp(`campo ${campo}`));
    assert.throws(() => validarColecao(com((f) => { f.properties[campo] = 3; })), new RegExp(`campo ${campo}`)); // número no lugar de texto
  }
  assert.doesNotThrow(() => validarColecao(com(() => {})));
});

test('camadasDaColecao lista cada camada uma vez, na ordem em que aparece', async () => {
  const { camadasDaColecao } = await import('./mapa.js');
  const lista = camadasDaColecao({ features: [feicao(1, 'b'), feicao(2, 'a'), feicao(3, 'b')] });
  assert.deepEqual(lista.map((c) => c.id), ['b', 'a']);
  assert.equal(lista[0].nome, 'B');
});

test('transparência vira opacidade complementar, presa entre 0 e 1', async () => {
  const { opacidadeDe } = await import('./mapa.js');
  assert.equal(opacidadeDe(0), 1);
  assert.equal(opacidadeDe(40), 0.6);
  assert.equal(opacidadeDe(100), 0);
  assert.equal(opacidadeDe(150), 0);
  assert.equal(opacidadeDe(-10), 1);
});

test('o desenho vai de baixo para cima e o contorno fica logo acima do preenchimento', async () => {
  const { ordemDeDesenho } = await import('./mapa.js');
  assert.deepEqual(ordemDeDesenho(['a', 'b']), ['b-preenchimento', 'b-contorno', 'a-preenchimento', 'a-contorno']);
  assert.deepEqual(ordemDeDesenho([]), []);
});

test('mover sobe e desce uma posição, e nas pontas não muda nem altera a lista original', async () => {
  const { moverNaOrdem } = await import('./mapa.js');
  const ordem = ['a', 'b', 'c'];
  assert.deepEqual(moverNaOrdem(ordem, 'c', -1), ['a', 'c', 'b']);
  assert.deepEqual(moverNaOrdem(ordem, 'a', 1), ['b', 'a', 'c']);
  assert.deepEqual(moverNaOrdem(ordem, 'a', -1), ['a', 'b', 'c']);
  assert.deepEqual(moverNaOrdem(ordem, 'c', 1), ['a', 'b', 'c']);
  assert.deepEqual(moverNaOrdem(ordem, 'x', 1), ['a', 'b', 'c']);
  assert.deepEqual(ordem, ['a', 'b', 'c']);
});

test('ligadasNaOrdem mantém a ordem de desenho e some com as desligadas', async () => {
  const { ligadasNaOrdem } = await import('./mapa.js');
  assert.deepEqual(ligadasNaOrdem(['a', 'b', 'c'], new Set(['c', 'a'])), ['a', 'c']);
});

test('a consulta ordena pela ordem de desenho do código, não pela do motor, e tira feição repetida', async () => {
  const { ordenarConsulta } = await import('./mapa.js');
  const achadas = [feicao(5, 'c'), feicao(1, 'a'), feicao(3, 'b'), feicao(1, 'a')];
  assert.deepEqual(ordenarConsulta(achadas, ['a', 'b', 'c']).map((f) => f.id), [1, 3, 5]);
  assert.deepEqual(ordenarConsulta(achadas, ['c', 'a']).map((f) => f.id), [5, 1]); // b desligada não entra
});

test('limites cobrem todos os vértices', async () => {
  const { limitesDaColecao } = await import('./mapa.js');
  assert.deepEqual(limitesDaColecao({ features: [feicao(1, 'a')] }), [[1, 2], [3, 4]]);
});

test('o estado da região vem do status: sem alcance é sem permissão, falha é erro, vazio é sem informação', async () => {
  const { estadoDaResposta } = await import('./mapa.js');
  assert.equal(estadoDaResposta(404), 'sem_permissao');
  assert.equal(estadoDaResposta(403), 'sem_permissao');
  assert.equal(estadoDaResposta(500), 'erro');
  assert.equal(estadoDaResposta(302), 'erro');
  assert.equal(estadoDaResposta(200, 0), 'sem_informacao');
  assert.equal(estadoDaResposta(200, 3), 'pronto');
});

test('coordenada sai com vírgula e cinco casas', async () => {
  const { formatarCoordenada } = await import('./mapa.js');
  assert.equal(formatarCoordenada(0.3), '0,30000');
});

test('posição: ok centraliza, negada e esgotada mostram a mensagem, e a falta de API desabilita', async () => {
  const { pedirPosicao, geolocalizacaoDisponivel, mensagemDeErroDePosicao } = await import('./mapa.js');
  const falsa = (resultado) => ({ getCurrentPosition: (ok, erro) => (resultado.code ? erro(resultado) : ok(resultado)) });
  let centro;
  pedirPosicao(falsa({ coords: { longitude: 0.31, latitude: 0.32 } }), (c) => { centro = c; }, () => assert.fail());
  assert.deepEqual(centro, [0.31, 0.32]);
  const mensagens = [];
  for (const code of [1, 2, 3]) pedirPosicao(falsa({ code }), () => assert.fail(), (m) => mensagens.push(m));
  assert.match(mensagens[0], /negada/);
  assert.match(mensagens[1], /Não foi possível/);
  assert.match(mensagens[2], /Tempo esgotado/);
  assert.equal(mensagemDeErroDePosicao(undefined), mensagens[1]);
  assert.equal(geolocalizacaoDisponivel({ isSecureContext: true, navigator: { geolocation: {} } }), true);
  assert.equal(geolocalizacaoDisponivel({ isSecureContext: false, navigator: { geolocation: {} } }), false);
  assert.equal(geolocalizacaoDisponivel({ isSecureContext: true, navigator: {} }), false);
});

test('combinarFundos: o neutro fica embaixo e o online por cima, sem perder fonte nenhuma', async () => {
  const { combinarFundos } = await import('./mapa.js');
  const neutro = { fontes: {}, camadas: [{ id: 'n' }] };
  const online = { fontes: { f: { type: 'raster' } }, camadas: [{ id: 'o' }] };
  const junto = combinarFundos(neutro, online);
  assert.deepEqual(junto.camadas.map((c) => c.id), ['n', 'o']);
  assert.deepEqual(Object.keys(junto.fontes), ['f']);
  assert.deepEqual(neutro.camadas, [{ id: 'n' }]); // entradas intactas
});

test('aviso do fundo só para tile de fonte do fundo online, não de camada própria nem erro sem tile', async () => {
  const { erroDeTileDoFundo } = await import('./mapa.js');
  const fontes = { 'fundo-online': {} };
  assert.equal(erroDeTileDoFundo({ tile: {}, sourceId: 'fundo-online' }, fontes), true);
  assert.equal(erroDeTileDoFundo({ tile: {}, sourceId: 'camada-a' }, fontes), false);
  assert.equal(erroDeTileDoFundo({ sourceId: 'fundo-online' }, fontes), false);
  assert.equal(erroDeTileDoFundo({ tile: {}, sourceId: 'fundo-online' }, undefined), false);
  assert.equal(erroDeTileDoFundo(undefined, fontes), false);
});

test('comPrazo: devolve o valor a tempo e rejeita quando a promessa trava', async () => {
  const { comPrazo } = await import('./mapa.js');
  assert.equal(await comPrazo(Promise.resolve('ok'), 1000), 'ok');
  await assert.rejects(comPrazo(new Promise(() => {}), 20), /prazo do fundo/);
  await assert.rejects(comPrazo(Promise.reject(new Error('falhou')), 1000), /falhou/); // erro da própria promessa passa
});

test('erro de tile não é fatal; erro do motor sem tile é', async () => {
  const { erroDoMapaEhFatal } = await import('./mapa.js');
  assert.equal(erroDoMapaEhFatal({ tile: {}, sourceId: 'fundo-online' }), false);
  assert.equal(erroDoMapaEhFatal({ error: new Error('x') }), true);
  assert.equal(erroDoMapaEhFatal(undefined), true);
});
