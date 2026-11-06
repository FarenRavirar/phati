// Fundo próprio do mapa (004b R7, R8): vetor aberto e ortofoto lidos de PMTiles que o servidor entrega por `Range`. Mesma forma de
// `fundo-neutro.js`: devolve `{ fontes, camadas }`. As camadas saem do `estilo_base.json`, o mesmo arquivo que o aplicativo
// recebe (R6): trocar cor ou largura lá muda a web e o aplicativo juntos. A web só troca as `url` das fontes pelas da rota.
// Este módulo não conhece o MapLibre nem o DOM, então importá-lo no Node é seguro.

export const FONTE_FUNDO = 'fundo';
export const FONTE_ORTOFOTO = 'ortofoto';
export const ID_ORTOFOTO = 'camada-ortofoto'; // o prefixo `camada-` põe a ortofoto entre as camadas do produto (`antesDaPrimeiraCamada`)

const objeto = (valor) => typeof valor === 'object' && valor !== null;

// Dado externo (o JSON estático) é desconfiado até conferir a forma.
export function validarEstilo(estilo) {
  const fonte = (nome, tipo) => objeto(estilo?.sources?.[nome]) && estilo.sources[nome].type === tipo;
  if (!objeto(estilo) || estilo.version !== 8 || !Array.isArray(estilo.layers) || !fonte(FONTE_FUNDO, 'vector') || !fonte(FONTE_ORTOFOTO, 'raster')) {
    throw new Error('estilo base fora da forma esperada');
  }
  if (!estilo.layers.every((c) => objeto(c) && typeof c.id === 'string' && typeof c.type === 'string')) {
    throw new Error('estilo base com camada sem id ou tipo');
  }
  return estilo;
}

// `pmtiles://` + endereço absoluto: o protocolo busca os trechos do arquivo por `Range` nesse endereço, e o `?versao=N` fica nele.
export const urlDoProtocolo = (url, origem) => `pmtiles://${new URL(url, origem).href}`;

// A atribuição aparece no `<p>` da página, não no controle do motor: um só lugar, sempre visível e fora do mapa (A7).
function fonteDe(estilo, nome, url, origem) {
  const fonte = { ...estilo.sources[nome], url: urlDoProtocolo(url, origem) };
  delete fonte.attribution;
  return fonte;
}

// Fundo vetorial e a cor de fundo do estilo; a ortofoto é outra camada (`ortofoto()`), que não troca com o fundo.
export function fundoAberto({ estilo, url, origem }) {
  validarEstilo(estilo);
  const camadas = estilo.layers.filter((c) => c.source === FONTE_FUNDO || c.type === 'background');
  return { fontes: { [FONTE_FUNDO]: fonteDe(estilo, FONTE_FUNDO, url, origem) }, camadas: structuredClone(camadas) };
}

// A ortofoto nasce desligada: o painel de camadas a liga, e os tiles só são pedidos com a camada visível.
export function ortofoto({ estilo, url, origem }) {
  validarEstilo(estilo);
  const camada = estilo.layers.find((c) => c.id === ID_ORTOFOTO && c.source === FONTE_ORTOFOTO);
  if (!camada) throw new Error('estilo base sem a camada da ortofoto');
  return {
    fontes: { [FONTE_ORTOFOTO]: fonteDe(estilo, FONTE_ORTOFOTO, url, origem) },
    camadas: [{ ...structuredClone(camada), layout: { ...camada.layout, visibility: 'none' } }],
  };
}

// 'AAAA-MM-DD' -> 'DD/MM/AAAA'. Texto fora desse formato volta como veio (nunca inventa data).
export function dataPtBr(texto) {
  const achado = /^(\d{4})-(\d{2})-(\d{2})$/.exec(texto ?? '');
  return achado ? `${achado[3]}/${achado[2]}/${achado[1]}` : (texto ?? '');
}

// Lê o que a página entrega por `data-pacote-*`. Sem `data-pacote-fundo` não há pacote: o mapa fica no fundo neutro.
export function pacoteDaPagina(dataset) {
  if (!dataset?.pacoteFundo || !dataset.pacoteEstilo) return null;
  return {
    estilo: dataset.pacoteEstilo,
    fundo: { url: dataset.pacoteFundo, atribuicao: dataset.pacoteAtribuicao ?? '' },
    ortofoto: dataset.pacoteOrtofoto
      ? { url: dataset.pacoteOrtofoto, atribuicao: dataset.pacoteOrtofotoAtribuicao ?? '', capturadaEm: dataset.pacoteOrtofotoData ?? '' }
      : null,
  };
}

// O protocolo `pmtiles://` precisa existir no MapLibre antes de uma fonte que o cite. `pmtiles` é o global do script embutido.
export function registrarProtocolo(maplibre, pmtiles) {
  if (typeof pmtiles?.Protocol !== 'function') throw new Error('biblioteca PMTiles ausente');
  const protocolo = new pmtiles.Protocol();
  maplibre.addProtocol('pmtiles', protocolo.tilev4);
  return protocolo;
}

// Falha de uma fonte do pacote (cabeçalho 403/404, rede, arquivo quebrado). O motor a emite como `error` com `sourceId` e sem
// `tile`: sem este teste o mapa inteiro apareceria como quebrado (`erroDoMapaEhFatal`).
export const erroDeFontePropria = (evento) => [FONTE_FUNDO, FONTE_ORTOFOTO].includes(evento?.sourceId);
