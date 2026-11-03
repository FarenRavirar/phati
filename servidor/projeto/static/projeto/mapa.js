// Adaptador do mapa (004 R15): o resto da página só conhece estas funções, nunca o motor. O fundo vem de fora
// (`fundo-neutro.js` agora, o fundo online na Fase 3); trocá-lo não toca camada, painel nem ficha.
// Carrega o MapLibre embutido só quando a página tem o elemento `[data-mapa]`, então importar este módulo no Node é seguro.
import { fundo as fundoNeutro } from './fundo-neutro.js';

// Perto de (0°, 0°): nenhuma fazenda real cabe aqui (004 R5). A Fase 2 troca por o enquadramento das camadas.
export const CENTRO_INICIAL = [0, 0];
export const ZOOM_INICIAL = 12;

const FORMA_DO_FUNDO = ['fontes', 'camadas'];

export function montarEstilo(fundo) {
  if (!fundo || FORMA_DO_FUNDO.some((chave) => typeof fundo[chave] !== 'object' || fundo[chave] === null)) {
    throw new Error('fundo fora da forma {fontes, camadas}');
  }
  return { version: 8, sources: { ...fundo.fontes }, layers: [...fundo.camadas] };
}

export function criarMapa(maplibre, elemento, fundo) {
  return new maplibre.Map({ container: elemento, style: montarEstilo(fundo), center: CENTRO_INICIAL, zoom: ZOOM_INICIAL });
}

// Falha de WebGL2, do módulo ou do motor: marca o elemento e mostra o aviso da região, nunca uma região vazia.
export function mostrarErro(elemento) {
  elemento.dataset.mapaErro = 'sim';
  const aviso = elemento.parentElement?.querySelector('[data-mapa-aviso]');
  if (aviso) aviso.hidden = false;
}

async function iniciar() {
  const elemento = document.querySelector('[data-mapa]');
  if (!elemento) return;
  try {
    const maplibre = await import('./terceiros/maplibre/maplibre-gl.mjs');
    const mapa = criarMapa(maplibre, elemento, fundoNeutro());
    mapa.once('load', () => { elemento.dataset.mapaPronto = 'sim'; });
    mapa.on('error', () => mostrarErro(elemento));
  } catch {
    mostrarErro(elemento);
  }
}

if (typeof document !== 'undefined') iniciar();
