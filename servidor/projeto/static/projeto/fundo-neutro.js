// Fundo neutro do mapa de teste (004 R15): sem tile, sem rede. Mesma forma que o `fundo-google.js` terá na Fase 3:
// `fundo()` devolve as fontes e as camadas que ficam abaixo de todas as camadas do contrato.
export const COR_DO_FUNDO = '#e8ecef';

export function fundo() {
  return { fontes: {}, camadas: [{ id: 'fundo-neutro', type: 'background', paint: { 'background-color': COR_DO_FUNDO } }] };
}
