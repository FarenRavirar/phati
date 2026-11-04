// Adaptador do mapa (004 R15): o resto da página só conhece estas funções, nunca o motor. O fundo vem de fora
// (`fundo-neutro.js` agora, o fundo online na Fase 3); trocá-lo não toca camada, painel nem ficha.
// Carrega o MapLibre embutido só quando a página tem o elemento `[data-mapa]`, então importar este módulo no Node é seguro.
import { fundo as fundoNeutro } from './fundo-neutro.js';

// Perto de (0°, 0°): nenhuma fazenda real cabe aqui (004 R5). Só vale até as camadas chegarem; depois o mapa enquadra a extensão delas.
export const CENTRO_INICIAL = [0, 0];
export const ZOOM_INICIAL = 12;
export const TRANSPARENCIA_INICIAL = 40; // percentual; a opacidade é o complemento (R9)

export function montarEstilo(fundo) {
  const objeto = (valor) => typeof valor === 'object' && valor !== null;
  if (!fundo || !objeto(fundo.fontes) || !Array.isArray(fundo.camadas)) {
    throw new Error('fundo fora da forma {fontes, camadas}');
  }
  return { version: 8, sources: { ...fundo.fontes }, layers: [...fundo.camadas] };
}

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

export const idsDeDesenho = (id) => ({ preenchimento: `${id}-preenchimento`, contorno: `${id}-contorno` });

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
      const amostra = elemento('span', 'legenda-amostra');
      amostra.style.backgroundColor = camada.corResolvida;
      amostra.setAttribute('aria-hidden', 'true');
      item.append(amostra, ' ', camada.nome);
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

function desenharCamadas(mapa, colecao, estado) {
  mapa.addSource('camadas', { type: 'geojson', data: colecao });
  for (const id of [...estado.ordem].reverse()) {
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
  const { preenchimento, contorno } = idsDeDesenho(id);
  if (mudanca.tipo === 'ligar') {
    estado.ligadas[mudanca.ligada ? 'add' : 'delete'](id);
    for (const camada of [preenchimento, contorno]) mapa.setLayoutProperty(camada, 'visibility', mudanca.ligada ? 'visible' : 'none');
  } else if (mudanca.tipo === 'transparencia') {
    estado.transparencia.set(id, mudanca.valor);
    mapa.setPaintProperty(preenchimento, 'fill-opacity', opacidadeDe(mudanca.valor));
    mapa.setPaintProperty(contorno, 'line-opacity', opacidadeDe(mudanca.valor));
  } else if (mudanca.tipo === 'mover') {
    estado.ordem = moverNaOrdem(estado.ordem, id, mudanca.passo);
    for (const camada of ordemDeDesenho(estado.ordem)) mapa.moveLayer(camada);
  }
}

let recentralizado = false; // achado real (review PR #36, Sourcery, média): a pessoa já escolheu o centro, o enquadramento inicial não o desfaz

function ligarCamadas(mapa, alvo, colecao) {
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
  desenharCamadas(mapa, colecao, estado);
  if (!recentralizado) mapa.fitBounds(limitesDaColecao(colecao), { padding: 24, duration: 0 });
  const atualizarPainel = montarPainelDeCamadas(estado, (mudanca) => {
    aplicar(mapa, estado, mudanca);
    atualizarPainel(mudanca);
    if (mudanca.tipo !== 'transparencia') limparConsulta();
  });
  limparEstado('camadas');
  mapa.on('click', (e) => {
    const alcancaveis = ligadasNaOrdem(estado.ordem, estado.ligadas).map((id) => idsDeDesenho(id).preenchimento);
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

async function carregarCamadas(mapa, alvo) {
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
    ligarCamadas(mapa, alvo, colecao);
  } catch {
    falharRegioes('erro', FALHA); // rede, prazo, JSON quebrado, forma errada ou erro ao desenhar
  } finally {
    clearTimeout(relogio);
  }
}

async function iniciar() {
  const alvo = document.querySelector('[data-mapa]');
  if (!alvo) return;
  try {
    const maplibre = await import('./terceiros/maplibre/maplibre-gl.mjs');
    const mapa = criarMapa(maplibre, alvo, fundoNeutro());
    alvo.mapa = mapa; // os testes de navegador projetam coordenadas e consultam o estilo por aqui
    esconderAviso(alvo);
    ligarRecentralizar(mapa);
    mapa.once('load', async () => {
      alvo.dataset.mapaFundo = mapa.getPaintProperty('fundo-neutro', 'background-color');
      await carregarCamadas(mapa, alvo);
      alvo.dataset.mapaPronto = 'sim';
    });
    mapa.on('error', () => mostrarErro(alvo));
  } catch {
    mostrarErro(alvo);
  }
}

if (typeof document !== 'undefined') void iniciar(); // `iniciar` captura o próprio erro
