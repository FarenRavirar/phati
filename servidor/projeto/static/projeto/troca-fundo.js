// Troca de fundo do mapa (004b R9, R10): quem está por baixo das camadas do produto é o fundo neutro (sempre), mais o fundo
// próprio ou o fundo online, nunca os dois (D086, D088; cláusula 3.2.3(e) do Google). A troca tira um antes de pôr o outro, sem
// tocar nas camadas do produto, que ficam acima (`antes` devolve a camada abaixo da qual o fundo entra).
// Só conhece a interface mínima do mapa (`addSource`, `addLayer`, `removeLayer`, `removeSource`, `getLayer`, `getSource`),
// então é testado com um dublê, sem MapLibre. O motivo da troca (rede, sessão, cota) é de quem chama.

export function criarTroca(mapa, { proprio = null, antes = () => undefined } = {}) {
  let ativo = 'neutro'; // 'neutro' | 'proprio' | 'online'
  let modo = 'automatico'; // 'manual' quando a pessoa escolheu; 'automatico' na abertura e na volta por falha
  let online = null;

  function tirar(fundo) {
    for (const camada of fundo.camadas) if (mapa.getLayer(camada.id)) mapa.removeLayer(camada.id);
    for (const id of Object.keys(fundo.fontes)) if (mapa.getSource(id)) mapa.removeSource(id);
  }

  function colocar(fundo) {
    for (const [id, fonte] of Object.entries(fundo.fontes)) if (!mapa.getSource(id)) mapa.addSource(id, fonte);
    const abaixo = antes();
    for (const camada of fundo.camadas) if (!mapa.getLayer(camada.id)) mapa.addLayer(camada, abaixo);
  }

  function tirarOnline() {
    if (!online) return;
    const saindo = online;
    online = null;
    saindo.parar?.(); // sem renovar sessão nem consultar crédito de um fundo que saiu
    tirar(saindo);
  }

  // Fundo próprio: na abertura, na volta por falha do online ou por escolha da pessoa. Sem pacote fica o neutro.
  function usarProprio({ manual = false } = {}) {
    tirarOnline();
    modo = manual ? 'manual' : 'automatico';
    if (!proprio) {
      ativo = 'neutro';
      return;
    }
    colocar(proprio);
    ativo = 'proprio';
  }

  return {
    estado: () => ({ ativo, modo }),
    usarProprio,

    // Fundo online: o próprio sai antes de ele entrar (R10).
    usarOnline(fundo, { manual = true } = {}) {
      tirarOnline();
      if (proprio) tirar(proprio);
      colocar(fundo);
      online = fundo;
      ativo = 'online';
      modo = manual ? 'manual' : 'automatico';
    },

    // O arquivo do pacote não abriu: sai o próprio e o neutro fica sozinho. Não mexe no fundo online, se for ele o ativo.
    falhouProprio() {
      if (!proprio) return;
      tirar(proprio);
      if (ativo === 'proprio') ativo = 'neutro';
    },

    // Fundo online que o motor deu por perdido (sessão, rede, cota): volta ao próprio, por falha, não por escolha.
    falhouOnline() {
      if (ativo === 'online') usarProprio();
    },

    online: () => online,
  };
}
