// Adaptador do mapa (004 R15): o resto da página só conhece estas funções, nunca o motor. O fundo vem de fora
// (`fundo-neutro.js` agora, o fundo online na Fase 3); trocá-lo não toca camada, painel nem ficha.
// Carrega o MapLibre embutido só quando a página tem o elemento `[data-mapa]`, então importar este módulo no Node é seguro.
import { fundo as fundoNeutro } from './fundo-neutro.js';
import { ID_ORTOFOTO, dataPtBr, erroDeFontePropria, fundoAberto, ortofoto as ortofotoDoPacote, pacoteDaPagina, registrarProtocolo, validarEstilo } from './fundo-aberto.js';
import { criarTroca } from './troca-fundo.js';

// Área rural de Porto Nacional (TO), em terra para o fundo online ter imagem; mesmo ponto de LON0, LAT0 em camadas_sinteticas.py. Só vale até as camadas chegarem; depois o mapa enquadra a extensão delas.
export const CENTRO_INICIAL = [-48.30, -10.75];
export const ZOOM_INICIAL = 12;
export const TRANSPARENCIA_INICIAL = 40; // percentual; a opacidade é o complemento (R9)

export function montarEstilo(fundo) {
  const objeto = (valor) => typeof valor === 'object' && valor !== null;
  if (!fundo || !objeto(fundo.fontes) || !Array.isArray(fundo.camadas)) {
    throw new Error('fundo fora da forma {fontes, camadas}');
  }
  return { version: 8, sources: { ...fundo.fontes }, layers: [...fundo.camadas] };
}

// Id da camada mais baixa do produto, ou `undefined` sem nenhuma: o fundo online entra logo abaixo dela e nunca cobre as camadas.
export const antesDaPrimeiraCamada = (camadas) => camadas.find((c) => c.id.startsWith('camada-'))?.id;

export function criarMapa(maplibre, elemento, fundo) {
  return new maplibre.Map({ container: elemento, style: montarEstilo(fundo), center: CENTRO_INICIAL, zoom: ZOOM_INICIAL });
}

// ---- Lógica pura das camadas (sem MapLibre nem DOM; testada em `mapa.test.js`) -------------------------------------

// Dado externo (a rota de camadas) é desconfiado até conferir a forma; o que falta é erro, nunca camada vazia calada.
// Achado real (review PR #36, Greptile e Sourcery, média): confere também a geometria e todo campo que a ficha mostra.
export const CAMPOS_DA_FICHA = ['camada', 'atributo', 'valor', 'fonte', 'data', 'situacao', 'ressalva', 'origem', 'metodo'];

const ehPosicao = (p) => Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]) && Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 90;
const ehAnel = (anel) => Array.isArray(anel) && anel.length >= 4 && anel.every(ehPosicao);

export function validarColecao(colecao) {
  if (typeof colecao !== 'object' || colecao === null || colecao.type !== 'FeatureCollection' || !Array.isArray(colecao.features)) {
    throw new Error('camadas fora da forma FeatureCollection');
  }
  for (const feicao of colecao.features) {
    const p = feicao?.properties;
    if (typeof p !== 'object' || p === null || typeof p.camada_id !== 'string' || typeof p.cor !== 'string') {
      throw new Error('feição sem camada_id, camada ou cor');
    }
    const g = feicao.geometry;
    if (g?.type !== 'Polygon' || !Array.isArray(g.coordinates) || g.coordinates.length === 0 || !g.coordinates.every(ehAnel)) {
      throw new Error('feição sem geometria Polygon válida');
    }
    const faltando = CAMPOS_DA_FICHA.find((campo) => typeof p[campo] !== 'string');
    if (faltando) throw new Error(`feição sem camada_id, camada ou cor: falta o campo ${faltando} da ficha`);
  }
  return colecao;
}

// Camadas na ordem de aparição; a primeira fica por cima (ordem de desenho padrão).
export function camadasDaColecao(colecao) {
  const vistas = new Map();
  for (const { properties: p } of colecao.features) {
    if (!vistas.has(p.camada_id)) vistas.set(p.camada_id, { id: p.camada_id, nome: p.camada, cor: p.cor });
  }
  return [...vistas.values()];
}

// A ortofoto (004b R8) é uma camada raster só: um id de desenho, sem preenchimento nem contorno, e fora da consulta (sem valor de raster).
export const idsDeDesenho = (id) => (id === ID_ORTOFOTO ? { imagem: id } : { preenchimento: `${id}-preenchimento`, contorno: `${id}-contorno` });

export const opacidadeDe = (transparencia) => Math.min(1, Math.max(0, 1 - Number(transparencia) / 100));

// `ordem` vai do topo para baixo; o desenho vai de baixo para cima, e cada camada leva o contorno logo acima do preenchimento.
export function ordemDeDesenho(ordem) {
  return [...ordem].reverse().flatMap((id) => Object.values(idsDeDesenho(id)));
}

// Sobe (-1) ou desce (+1) uma camada na ordem; nas pontas não muda.
export function moverNaOrdem(ordem, id, passo) {
  const de = ordem.indexOf(id);
  const para = de + passo;
  if (de < 0 || para < 0 || para >= ordem.length) return [...ordem];
  const nova = [...ordem];
  [nova[de], nova[para]] = [nova[para], nova[de]];
  return nova;
}

export const ligadasNaOrdem = (ordem, ligadas) => ordem.filter((id) => ligadas.has(id));

// Consulta: o MapLibre pode devolver a mesma feição mais de uma vez (feição cortada entre tiles). Fica uma por `id`,
// na ordem de desenho do próprio código (a do retorno do motor não é documentada, e no Android também não).
export function ordenarConsulta(feicoes, ordem) {
  const vistos = new Set();
  const unicas = feicoes.filter((f) => {
    const chave = f.id ?? JSON.stringify(f.properties);
    if (vistos.has(chave) || !ordem.includes(f.properties.camada_id)) return false;
    vistos.add(chave);
    return true;
  });
  return unicas.sort((a, b) => ordem.indexOf(a.properties.camada_id) - ordem.indexOf(b.properties.camada_id));
}

// Caixa [[oeste, sul], [leste, norte]] de todos os vértices, para enquadrar (R6).
export function limitesDaColecao(colecao) {
  const pontos = colecao.features.flatMap((f) => f.geometry.coordinates.flat(1));
  const lons = pontos.map((p) => p[0]);
  const lats = pontos.map((p) => p[1]);
  return [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]];
}

// Resposta da rota de camadas -> estado da região (R14): sem alcance (404 do `resolver_escopo`) e 403 são "sem permissão".
export function estadoDaResposta(status, quantidadeDeFeicoes = 1) {
  if (status === 403 || status === 404) return 'sem_permissao';
  if (status < 200 || status >= 300) return 'erro';
  return quantidadeDeFeicoes === 0 ? 'sem_informacao' : 'pronto';
}

export const formatarCoordenada = (valor) => valor.toLocaleString('pt-BR', { minimumFractionDigits: 5, maximumFractionDigits: 5 });

// ---- Posição do aparelho (R24): só depois do toque, só no navegador, nunca enviada ---------------------------------

export function geolocalizacaoDisponivel(ambiente) {
  return Boolean(ambiente.isSecureContext && ambiente.navigator?.geolocation);
}

export function mensagemDeErroDePosicao(erro) {
  if (erro?.code === 1) return 'Permissão de localização negada. O mapa segue como está.';
  if (erro?.code === 3) return 'Tempo esgotado ao obter a posição. Tente de novo.';
  return 'Não foi possível obter a posição do aparelho.';
}

export function pedirPosicao(geolocalizacao, aoAcertar, aoFalhar) {
  geolocalizacao.getCurrentPosition(
    (posicao) => aoAcertar([posicao.coords.longitude, posicao.coords.latitude]),
    (erro) => aoFalhar(mensagemDeErroDePosicao(erro)),
    { timeout: 10000, maximumAge: 60000 },
  );
}

// ---- Avisos de falha do motor --------------------------------------------------------------------------------------

// O aviso de falha nasce visível no HTML e só some quando o mapa é criado: se o próprio `mapa.js` ou o MapLibre não
// carregar (MIME errado, 404, CSP), a região mostra o aviso em vez de ficar vazia.
function aviso(elemento) {
  return elemento.parentElement?.querySelector('[data-mapa-aviso]');
}

export function esconderAviso(elemento) {
  const caixa = aviso(elemento);
  if (caixa) caixa.hidden = true;
}

// Tile que não chega (rede, cota, 403 do fundo online) não derruba o mapa nem as camadas: o motor emite `error` com `tile`.
export const erroDoMapaEhFatal = (evento) => !evento?.tile;

// Tile que falhou numa fonte do fundo online (não de camada própria): o fundo some ou fica incompleto, então a pessoa é avisada.
// Status do erro de tile do fundo online -> o que fazer. Sem status = falha de rede; 401 = sessão recusada; 403, 429 e 5xx = serviço
// ou cota. 404 e 400 só dizem que não há imagem ali (o provedor responde 404 sem cobertura): não derrubam o satélite todo.
export function motivoParaDesligar(status) {
  if (status === 401) return 'sessao';
  if (status === undefined || status === 0 || status === 403 || status === 429 || status >= 500) return 'servico';
  return 'parcial';
}

export const erroDeTileDoFundo = (evento, fontesDoFundo) => Boolean(evento?.tile) && Object.hasOwn(fontesDoFundo ?? {}, evento.sourceId);

// Falha de WebGL2, do módulo ou do motor: marca o elemento e mostra o aviso da região.
export function mostrarErro(elemento) {
  elemento.dataset.mapaErro = 'sim';
  const caixa = aviso(elemento);
  if (caixa) caixa.hidden = false;
}

// ---- Painéis (DOM). Todo texto de dado entra por `textContent`, nunca `innerHTML` (R13) ---------------------------------

const regiao = (id) => ({
  estado: document.querySelector(`[data-estado-de="${id}"]`),
  conteudo: document.querySelector(`[data-conteudo-de="${id}"]`),
});

const modelo = (nome) => document.querySelector(`template[data-modelo="${nome}"]`).content.firstElementChild.cloneNode(true);

// Estados da região (R14): vazio, carregando, erro, sem_permissao e sem_informacao; `texto` troca a frase do modelo.
export function definirEstado(id, estado, texto) {
  const { estado: caixa } = regiao(id);
  const bloco = modelo(estado);
  const alvo = bloco.querySelector('.vazio-texto, .aviso-texto');
  if (texto && alvo) alvo.textContent = texto;
  caixa.replaceChildren(bloco);
}

const limparEstado = (id) => regiao(id).estado.replaceChildren();

const TEXTO_CONSULTA = 'Escolha um ponto no mapa para consultar.';
const TEXTO_FICHA = 'A ficha, as fontes e as ressalvas aparecem aqui.';

// Achado real (review PR #36, Sourcery, média): consulta e ficha voltam ao vazio, porque o resultado antigo não vale para as camadas ligadas e a ordem de agora.
function limparConsulta() {
  for (const [id, texto] of [['consulta', TEXTO_CONSULTA], ['ficha', TEXTO_FICHA]]) {
    definirEstado(id, 'vazio', texto);
    regiao(id).conteudo.replaceChildren();
  }
}

function elemento(tag, classe, texto) {
  const no = document.createElement(tag);
  if (classe) no.className = classe;
  if (texto !== undefined) no.textContent = texto;
  return no;
}

function botao(texto, rotulo, aoClicar) {
  const b = elemento('button', 'botao botao-secundario botao-camada', texto);
  b.type = 'button';
  b.setAttribute('aria-label', rotulo);
  b.addEventListener('click', aoClicar);
  return b;
}

function montarPainelDeCamadas(estado, aoMudar) {
  const { conteudo } = regiao('camadas');
  const lista = elemento('ul', 'lista-camadas');
  const legenda = elemento('ul', 'legenda');
  lista.dataset.listaCamadas = '';
  legenda.dataset.legenda = '';
  conteudo.replaceChildren(lista, elemento('h3', 'legenda-titulo', 'Legenda (cores provisórias)'), legenda);

  // Achado real (review PR #36, Codex, Greptile, Sourcery e Qodo, alta): cada controle nasce uma vez; recriar o que está sendo arrastado ou focado interrompe o ajuste.
  const itens = new Map(estado.ordem.map((id) => {
    const camada = estado.camadas.get(id);
    const item = elemento('li', 'camada');
    item.dataset.camada = id;
    const rotulo = elemento('label', 'camada-nome');
    const caixa = document.createElement('input');
    caixa.type = 'checkbox';
    caixa.checked = estado.ligadas.has(id);
    caixa.addEventListener('change', () => aoMudar({ tipo: 'ligar', id, ligada: caixa.checked }));
    rotulo.append(caixa, ' ', camada.nome);
    const transparencia = document.createElement('input');
    transparencia.type = 'range';
    transparencia.min = '0';
    transparencia.max = '100';
    transparencia.value = String(estado.transparencia.get(id));
    transparencia.setAttribute('aria-label', `Transparência de ${camada.nome}, em porcentagem`);
    transparencia.addEventListener('input', () => aoMudar({ tipo: 'transparencia', id, valor: Number(transparencia.value) }));
    const subir = botao('Subir', `Subir ${camada.nome} na ordem de desenho`, () => aoMudar({ tipo: 'mover', id, passo: -1 }));
    const descer = botao('Descer', `Descer ${camada.nome} na ordem de desenho`, () => aoMudar({ tipo: 'mover', id, passo: 1 }));
    item.append(rotulo, transparencia, subir, descer);
    return [id, { item, subir, descer }];
  }));

  function ordenarLista() {
    const foco = document.activeElement;
    estado.ordem.forEach((id, posicao) => {
      const { item, subir, descer } = itens.get(id);
      lista.append(item);
      subir.disabled = posicao === 0;
      descer.disabled = posicao === estado.ordem.length - 1;
    });
    // Mover o nó tira o foco do botão; devolve a ele, ou ao outro botão do item quando a ponta o desabilitou.
    if (foco instanceof HTMLElement && lista.contains(foco)) {
      const alvo = foco.disabled ? foco.closest('li')?.querySelector('button:not(:disabled)') : foco;
      alvo?.focus();
    }
  }

  function desenharLegenda() {
    legenda.replaceChildren(...ligadasNaOrdem(estado.ordem, estado.ligadas).map((id) => {
      const camada = estado.camadas.get(id);
      const item = elemento('li', 'legenda-item');
      if (!camada.raster) { // a ortofoto é imagem: não tem cor de legenda
        const amostra = elemento('span', 'legenda-amostra');
        amostra.style.backgroundColor = camada.corResolvida;
        amostra.setAttribute('aria-hidden', 'true');
        item.append(amostra, ' ');
      }
      item.append(camada.nome);
      return item;
    }));
  }

  ordenarLista();
  desenharLegenda();
  return (mudanca) => {
    if (mudanca.tipo === 'mover') ordenarLista();
    if (mudanca.tipo !== 'transparencia') desenharLegenda();
  };
}

function mostrarFicha(propriedades) {
  const { conteudo } = regiao('ficha');
  limparEstado('ficha');
  const ficha = modelo('ficha');
  for (const dd of ficha.querySelectorAll('[data-campo]')) dd.textContent = propriedades[dd.dataset.campo];
  conteudo.replaceChildren(ficha);
}

function mostrarConsulta(itens, lngLat) {
  const { conteudo } = regiao('consulta');
  const coordenadas = elemento('p', 'consulta-coordenadas');
  coordenadas.dataset.coordenadas = '';
  coordenadas.textContent = `Latitude ${formatarCoordenada(lngLat.lat)}, longitude ${formatarCoordenada(lngLat.lng)}`;
  if (itens.length === 0) {
    conteudo.replaceChildren(coordenadas);
    definirEstado('consulta', 'sem_informacao');
    definirEstado('ficha', 'vazio', TEXTO_FICHA);
    regiao('ficha').conteudo.replaceChildren();
    return;
  }
  limparEstado('consulta');
  const lista = elemento('ul', 'lista-consulta');
  lista.dataset.listaConsulta = '';
  for (const { properties: p } of itens) {
    const item = elemento('li', 'consulta-item');
    const b = elemento('button', 'botao botao-secundario consulta-botao', `${p.camada}: ${p.atributo}, ${p.valor} (${p.situacao}, ${p.origem})`);
    b.type = 'button';
    b.addEventListener('click', () => mostrarFicha(p));
    item.append(b);
    lista.append(item);
  }
  conteudo.replaceChildren(coordenadas, lista);
  mostrarFicha(itens[0].properties);
}

// ---- Montagem -------------------------------------------------------------------------------------------------------

function desenharCamadas(mapa, colecao, estado, imagem) {
  mapa.addSource('camadas', { type: 'geojson', data: colecao });
  for (const id of [...estado.ordem].reverse()) {
    if (id === ID_ORTOFOTO) { // a ortofoto entra desligada (`ortofotoDoPacote`) e com a opacidade do painel
      for (const [fonte, definicao] of Object.entries(imagem.fontes)) mapa.addSource(fonte, definicao);
      for (const camada of imagem.camadas) mapa.addLayer({ ...camada, paint: { ...camada.paint, 'raster-opacity': opacidadeDe(estado.transparencia.get(id)) } });
      continue;
    }
    const { preenchimento, contorno } = idsDeDesenho(id);
    const cor = estado.camadas.get(id).corResolvida;
    const opacidade = opacidadeDe(estado.transparencia.get(id));
    const filtro = ['==', ['get', 'camada_id'], id];
    mapa.addLayer({ id: preenchimento, type: 'fill', source: 'camadas', filter: filtro, paint: { 'fill-color': cor, 'fill-opacity': opacidade } });
    mapa.addLayer({ id: contorno, type: 'line', source: 'camadas', filter: filtro, paint: { 'line-color': cor, 'line-width': 2, 'line-opacity': opacidade } });
  }
}

function aplicar(mapa, estado, mudanca) {
  const { id } = mudanca;
  const { preenchimento, contorno, imagem } = idsDeDesenho(id);
  if (mudanca.tipo === 'ligar') {
    estado.ligadas[mudanca.ligada ? 'add' : 'delete'](id);
    for (const camada of Object.values(idsDeDesenho(id))) mapa.setLayoutProperty(camada, 'visibility', mudanca.ligada ? 'visible' : 'none');
  } else if (mudanca.tipo === 'transparencia') {
    estado.transparencia.set(id, mudanca.valor);
    if (imagem) {
      mapa.setPaintProperty(imagem, 'raster-opacity', opacidadeDe(mudanca.valor));
    } else {
      mapa.setPaintProperty(preenchimento, 'fill-opacity', opacidadeDe(mudanca.valor));
      mapa.setPaintProperty(contorno, 'line-opacity', opacidadeDe(mudanca.valor));
    }
  } else if (mudanca.tipo === 'mover') {
    estado.ordem = moverNaOrdem(estado.ordem, id, mudanca.passo);
    for (const camada of ordemDeDesenho(estado.ordem)) mapa.moveLayer(camada);
  }
}

let recentralizado = false; // achado real (review PR #36, Sourcery, média): a pessoa já escolheu o centro, o enquadramento inicial não o desfaz

function ligarCamadas(mapa, alvo, colecao, imagem) {
  const lista = camadasDaColecao(colecao);
  const estilo = getComputedStyle(document.documentElement);
  const camadas = new Map(lista.map((c) => {
    const corResolvida = estilo.getPropertyValue(c.cor).trim();
    if (!corResolvida) throw new Error(`cor ${c.cor} sem valor em camadas.css`);
    return [c.id, { ...c, corResolvida }];
  }));
  const estado = {
    camadas, ordem: lista.map((c) => c.id), ligadas: new Set(lista.map((c) => c.id)),
    transparencia: new Map(lista.map((c) => [c.id, TRANSPARENCIA_INICIAL])),
  };
  if (imagem) { // ortofoto do pacote: a camada mais baixa do produto, desligada e opaca, até a pessoa ligar (R8)
    camadas.set(ID_ORTOFOTO, { id: ID_ORTOFOTO, nome: imagem.nome, raster: true });
    estado.ordem.push(ID_ORTOFOTO);
    estado.transparencia.set(ID_ORTOFOTO, 0);
  }
  desenharCamadas(mapa, colecao, estado, imagem);
  if (!recentralizado) mapa.fitBounds(limitesDaColecao(colecao), { padding: 24, duration: 0 });
  const atualizarPainel = montarPainelDeCamadas(estado, (mudanca) => {
    aplicar(mapa, estado, mudanca);
    atualizarPainel(mudanca);
    if (mudanca.tipo !== 'transparencia') limparConsulta();
  });
  limparEstado('camadas');
  mapa.on('click', (e) => {
    const alcancaveis = ligadasNaOrdem(estado.ordem, estado.ligadas).map((id) => idsDeDesenho(id).preenchimento).filter(Boolean);
    const achadas = alcancaveis.length ? mapa.queryRenderedFeatures(e.point, { layers: alcancaveis }) : [];
    mostrarConsulta(ordenarConsulta(achadas, ligadasNaOrdem(estado.ordem, estado.ligadas)), e.lngLat);
  });
  alvo.dataset.mapaCamadas = String(lista.length);
}

function ligarRecentralizar(mapa) {
  const botaoPosicao = document.querySelector('[data-recentralizar]');
  const mensagem = document.querySelector('[data-mapa-mensagem]');
  if (!botaoPosicao || !mensagem) return;
  const dizer = (texto) => {
    mensagem.querySelector('.aviso-texto').textContent = texto;
    mensagem.hidden = !texto;
  };
  if (!geolocalizacaoDisponivel(window)) {
    botaoPosicao.disabled = true;
    dizer('A posição do aparelho só funciona em conexão segura (HTTPS) e em navegador com localização.');
    return;
  }
  // Nasce desabilitado no HTML e só habilita aqui, com o clique já ligado: em runner lento o toque cedo demais se perdia (CI da PR #36).
  botaoPosicao.disabled = false;
  botaoPosicao.addEventListener('click', () => {
    dizer('');
    pedirPosicao(navigator.geolocation, (centro) => {
      recentralizado = true;
      mapa.jumpTo({ center: centro });
    }, dizer);
  });
}

const TEMPO_LIMITE_PADRAO_MS = 15000;

// Achado real (review PR #36, Qodo, média): falha de carregamento vale para as três regiões; consulta e ficha não ficam pedindo um toque que não responde.
function falharRegioes(estado, texto) {
  for (const id of ['camadas', 'consulta', 'ficha']) definirEstado(id, estado, texto);
}

async function carregarCamadas(mapa, alvo, imagem) {
  definirEstado('camadas', 'carregando');
  const controle = new AbortController();
  const prazo = Number(alvo.dataset.camadasTempoLimite) || TEMPO_LIMITE_PADRAO_MS;
  const relogio = setTimeout(() => controle.abort(), prazo); // achado real (review PR #36, Sourcery, média): sem prazo o "Carregando…" nunca acabava
  const FALHA = 'Não foi possível carregar as camadas.';
  try {
    // Achado real (review PR #36, Qodo e Sourcery, média): `manual`, porque sessão expirada responde redirecionamento ao login e seguir devolveria HTML com 200.
    const resposta = await fetch(alvo.dataset.camadasUrl, {
      credentials: 'same-origin', headers: { Accept: 'application/geo+json' }, redirect: 'manual', signal: controle.signal,
    });
    if (resposta.type === 'opaqueredirect') {
      window.location.assign(`/entrar?proximo=${encodeURIComponent(window.location.pathname)}&expirou=1`);
      return;
    }
    let estado = estadoDaResposta(resposta.status);
    let colecao;
    if (estado === 'pronto') {
      colecao = validarColecao(await resposta.json());
      estado = estadoDaResposta(resposta.status, colecao.features.length);
    }
    if (estado !== 'pronto') {
      falharRegioes(estado, estado === 'erro' ? FALHA : undefined);
      return;
    }
    ligarCamadas(mapa, alvo, colecao, imagem);
  } catch {
    falharRegioes('erro', FALHA); // rede, prazo, JSON quebrado, forma errada ou erro ao desenhar
  } finally {
    clearTimeout(relogio);
  }
}

// Sem prazo, um módulo ou uma sessão presos seguram a criação do mapa inteiro, neutro e camadas incluídos (review PR #43).
export const PRAZO_FUNDO_MS = 12000;
export function comPrazo(promessa, ms) {
  let relogio;
  const estouro = new Promise((_, rejeitar) => { relogio = setTimeout(() => rejeitar(new Error('prazo do fundo esgotado')), ms); });
  return Promise.race([promessa, estouro]).finally(() => clearTimeout(relogio));
}

// Fundo online opcional: a página só entrega chave e módulo com a flag ligada. O módulo vem do atributo, então este
// arquivo não conhece o provedor (A10). Falha na sessão = fundo neutro e aviso, nunca mapa quebrado (R12).
// Aviso do fundo em região própria: o `[data-mapa-mensagem]` é da posição do aparelho, que o apaga ao clicar (review PR #43, Qodo).
function avisarFundo(alvo, texto) {
  const caixa = alvo.parentElement.querySelector('[data-mapa-fundo-aviso]');
  if (!caixa) return;
  caixa.querySelector('.aviso-texto').textContent = texto;
  caixa.hidden = false;
}

// Nome do fundo que fica de pé quando o online cai ou nem abre: o do pacote da fazenda, ou o neutro sem pacote (R9).
const nomeDoFundo = (troca) => (troca.estado().ativo === 'proprio' ? 'fundo do mapa da fazenda' : 'fundo neutro');

async function carregarFundoOnline(alvo, troca) {
  const { fundoOnlineChave: chave, fundoOnlineModulo: modulo } = alvo.dataset;
  if (!chave || !modulo) return null;
  try {
    return await comPrazo((async () => (await import(modulo)).criarFundo({ chave }))(), PRAZO_FUNDO_MS);
  } catch {
    alvo.dataset.fundoOnlineErro = 'sim';
    avisarFundo(alvo, `O fundo do mapa está indisponível. Mostrando o ${nomeDoFundo(troca)}.`);
    return null;
  }
}

// O satélite só carrega quando a pessoa o liga: cada tile do fundo online é cobrado, então quem abre a fazenda para outra coisa não paga.
// Antes do clique o mapa tem só o fundo da fazenda (ou o neutro, sem pacote): 0 sessão, 0 tile. Depois de ligado, o cache que o provedor
// autoriza (HTTP, pelos cabeçalhos, 24 h) segue valendo: tile fresco aparece mesmo sem rede. Faltando serviço (sem rede, sessão
// recusada, cota), o satélite se desliga inteiro e o fundo da fazenda volta; fundo online e fundo próprio nunca juntos (D088; R9, R10,
// R22 da 004b), por `troca-fundo.js`. Com pacote, o mesmo botão volta ao fundo da fazenda (escolha manual nos dois sentidos, R9).
// Devolve `habilitar` (mapa pronto) e `desligar(texto)`; `{fundo}` no texto vira o nome do fundo que ficou.
function prepararSatelite(mapa, alvo, troca, aoMudar) {
  const botao = document.querySelector('[data-satelite]');
  if (!botao) return { habilitar() {}, desligar() {} };
  const atribuicao = alvo.parentElement.querySelector('[data-mapa-atribuicao]');
  const temProprio = Boolean(alvo.dataset.pacoteFundo);
  async function ligar() {
    botao.disabled = true;
    const online = await carregarFundoOnline(alvo, troca);
    if (!online) {
      botao.disabled = false; // `carregarFundoOnline` já avisou; a pessoa pode tentar de novo
      return;
    }
    troca.usarOnline(online);
    atribuicao.hidden = false;
    online.aoCriarMapa(mapa, { dados: atribuicao.querySelector('[data-atribuicao-dados]') });
    alvo.parentElement.querySelector('[data-mapa-fundo-aviso]')?.setAttribute('hidden', '');
    delete alvo.dataset.fundoOnlineErro; // recuperou: o erro da tentativa anterior não vale mais (achado Sourcery, baixa)
    delete alvo.dataset.fundoOnlineSessao;
    alvo.dataset.mapaSatelite = 'sim';
    botao.textContent = temProprio ? 'Voltar ao fundo da fazenda' : 'Satélite ativado';
    botao.disabled = !temProprio; // sem pacote não há para onde voltar: o botão fica parado, como na 004
    aoMudar();
  }
  function voltar() {
    troca.usarProprio({ manual: true });
    atribuicao.hidden = true;
    alvo.dataset.mapaSatelite = 'nao';
    botao.textContent = 'Ativar satélite';
    alvo.parentElement.querySelector('[data-mapa-fundo-aviso]')?.setAttribute('hidden', '');
    aoMudar();
  }
  botao.addEventListener('click', () => (troca.estado().ativo === 'online' ? voltar() : ligar()));
  return {
    habilitar() { botao.disabled = false; },
    desligar(texto) {
      if (troca.estado().ativo !== 'online') return;
      troca.falhouOnline(); // para o fundo online (sem renovar sessão nem consultar crédito) e recoloca o da fazenda
      atribuicao.hidden = true;
      alvo.dataset.mapaSatelite = 'nao';
      botao.textContent = 'Ativar satélite';
      botao.disabled = false;
      avisarFundo(alvo, texto.replace('{fundo}', nomeDoFundo(troca)));
      aoMudar();
    },
  };
}

export const nomeDaOrtofoto = (ortofoto) => (ortofoto.capturadaEm ? `Ortofoto (captura em ${dataPtBr(ortofoto.capturadaEm)})` : 'Ortofoto');

// Pacote da fazenda (004b R7, R8): protocolo `pmtiles://`, estilo compartilhado e as duas fontes. Qualquer falha aqui deixa o mapa no
// fundo neutro com aviso, nunca quebrado (R9); sem `data-pacote-fundo` (sem pacote, sem permissão) nada disso roda.
async function prepararPacote(maplibre, alvo) {
  const pacote = pacoteDaPagina(alvo.dataset);
  if (!pacote) return { proprio: null, imagem: null };
  try {
    return await comPrazo((async () => {
      registrarProtocolo(maplibre, globalThis.pmtiles);
      const resposta = await fetch(pacote.estilo, { credentials: 'same-origin' });
      if (!resposta.ok) throw new Error(`estilo base ${resposta.status}`);
      const estilo = validarEstilo(await resposta.json());
      const origem = window.location.origin;
      const proprio = fundoAberto({ estilo, url: pacote.fundo.url, origem });
      const imagem = pacote.ortofoto ? { ...ortofotoDoPacote({ estilo, url: pacote.ortofoto.url, origem }), nome: nomeDaOrtofoto(pacote.ortofoto) } : null;
      return { proprio, imagem };
    })(), PRAZO_FUNDO_MS);
  } catch {
    alvo.dataset.fundoProprioErro = 'sim';
    avisarFundo(alvo, 'O fundo do mapa da fazenda está indisponível. Mostrando o fundo neutro.');
    return { proprio: null, imagem: null };
  }
}

// Atribuição do fundo ativo (R10): a do OpenStreetMap só enquanto o fundo da fazenda é o ativo; a do fundo online o `prepararSatelite` mostra.
function mostrarAtribuicaoAberta(alvo, troca) {
  const caixa = alvo.parentElement.querySelector('[data-atribuicao-aberta]');
  alvo.dataset.fundoAtivo = troca.estado().ativo;
  if (!caixa) return;
  caixa.textContent = alvo.dataset.pacoteAtribuicao ?? '';
  caixa.hidden = troca.estado().ativo !== 'proprio';
}

// Erro de fonte do pacote: sem `tile` é o arquivo que não abriu (403, 404, rede) e o fundo da fazenda sai; com `tile` é um pedaço que
// falhou e só se avisa. A ortofoto nunca derruba o mapa.
function tratarErroDoPacote(e, alvo, troca) {
  const fundo = e.sourceId === 'fundo';
  if (fundo && !e.tile) {
    alvo.dataset.fundoProprioErro = 'sim';
    troca.falhouProprio();
    mostrarAtribuicaoAberta(alvo, troca);
    avisarFundo(alvo, 'O fundo do mapa da fazenda não abriu. Mostrando o fundo neutro.');
  } else {
    avisarFundo(alvo, fundo ? 'Parte do fundo do mapa da fazenda não carregou. As camadas seguem normais.' : 'A ortofoto não carregou. As outras camadas seguem normais.');
  }
}

async function iniciar() {
  const alvo = document.querySelector('[data-mapa]');
  if (!alvo) return;
  try {
    const maplibre = await import('./terceiros/maplibre/maplibre-gl.mjs');
    const { proprio, imagem } = await prepararPacote(maplibre, alvo);
    const mapa = criarMapa(maplibre, alvo, fundoNeutro());
    const troca = criarTroca(mapa, { proprio, antes: () => antesDaPrimeiraCamada(mapa.getStyle().layers) });
    const satelite = prepararSatelite(mapa, alvo, troca, () => mostrarAtribuicaoAberta(alvo, troca));
    alvo.mapa = mapa; // os testes de navegador projetam coordenadas e consultam o estilo por aqui
    esconderAviso(alvo);
    ligarRecentralizar(mapa);
    mapa.once('load', async () => {
      alvo.dataset.mapaFundo = mapa.getPaintProperty('fundo-neutro', 'background-color');
      troca.usarProprio();
      mostrarAtribuicaoAberta(alvo, troca);
      await carregarCamadas(mapa, alvo, imagem);
      alvo.dataset.mapaPronto = 'sim';
      satelite.habilitar();
    });
    mapa.on('error', (e) => {
      if (erroDeFontePropria(e)) {
        tratarErroDoPacote(e, alvo, troca);
        return; // fonte do pacote nunca é fatal: o neutro e as camadas seguem
      }
      if (erroDeTileDoFundo(e, troca.online()?.fontes)) {
        alvo.dataset.fundoOnlineErro = 'sim';
        const motivo = motivoParaDesligar(e.error?.status);
        if (motivo === 'sessao') {
          troca.online()?.descartarSessao?.(); // 401: esquece a guardada, a próxima ativação cria outra (review PR #44, CodeRabbit)
          satelite.desligar('A sessão do satélite não vale mais. Ative o satélite de novo.');
        } else if (motivo === 'servico') {
          satelite.desligar('Sem rede ou sem resposta do fundo online: o satélite foi desligado e o mapa voltou ao {fundo}. Ative o satélite de novo quando quiser.');
        } else {
          avisarFundo(alvo, 'Parte do fundo do mapa não carregou. As camadas seguem normais.'); // 400 e 404: sem imagem naquele ponto
        }
      }
      if (erroDoMapaEhFatal(e)) mostrarErro(alvo);
    });
  } catch {
    mostrarErro(alvo);
  }
}

if (typeof document !== 'undefined') void iniciar(); // `iniciar` captura o próprio erro
