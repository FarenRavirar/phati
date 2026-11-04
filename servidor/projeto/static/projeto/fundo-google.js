// Fundo online do mapa (004 R17 a R19): Map Tiles API do Google, sessão criada no navegador. Único arquivo do produto que
// conhece o Google (A10). O produto não guarda tile em lugar nenhum (nem em worker, nem em banco do navegador, nem em arquivo
// próprio): o Google proíbe pré-carregar e guardar tile; o cache é só o do navegador, que segue os cabeçalhos da resposta. Doc lida em 2026-11-04:
// https://developers.google.com/maps/documentation/tile/session_tokens (createSession)
// https://developers.google.com/maps/documentation/tile/2d-tiles-overview (viewport, 2dtiles)
// https://developers.google.com/maps/documentation/tile/policies (atribuição, cache)
export const ORIGEM = 'https://tile.googleapis.com';
export const ID_FONTE = 'fundo-online';
export const ID_CAMADA = 'fundo-online-tiles';
const MARGEM_RENOVACAO_S = 3600; // renova uma hora antes de `expiry`
const MAXIMO_TEMPORIZADOR_MS = 2 ** 31 - 1; // setTimeout estoura acima disto e dispararia na hora
export const PRAZO_SESSAO_MS = 10000; // sem prazo, um Google lento seguraria o mapa inteiro (review PR #43)
export const ESPERA_INICIAL_MS = 30000; // renovação que falha: 30 s, 60 s, 120 s... até o teto
export const ESPERA_MAXIMA_MS = 600000;
export const TENTATIVAS_MAXIMAS = 5; // depois disto para de pedir sessão; o mapa segue até o Google recusar o tile (R12)

const url = (caminho, parametros) => `${ORIGEM}${caminho}?${new URLSearchParams(parametros)}`;

// Dado externo: a resposta do Google é desconfiada até conferir a forma (`session` e `expiry` em segundos de época).
export async function criarSessao(buscar, chave, prazoMs = PRAZO_SESSAO_MS) {
  const resposta = await buscar(url('/v1/createSession', { key: chave }), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // `scale` 2x com `highDpi` entrega tiles de 512 px sobre a mesma área (doc, createSession): o MapLibre pede um nível a menos
    // com a mesma nitidez por pixel CSS. Medido em 2026-11-04 com o Google real, mesma vista: 8 → 6 tiles a 1280×720 e 8 → 4
    // a 320×568, imagem igual à vista. `tileWidth` volta 512 e `zoomDosTiles` já segue a largura.
    body: JSON.stringify({ mapType: 'satellite', language: 'pt-BR', region: 'BR', imageFormat: 'jpeg', scale: 'scaleFactor2x', highDpi: true }),
    signal: AbortSignal.timeout(prazoMs),
  });
  if (!resposta.ok) throw new Error(`sessão recusada (${resposta.status})`);
  const dados = await resposta.json();
  const expira = Number(dados?.expiry);
  if (typeof dados?.session !== 'string' || dados.session === '' || !Number.isFinite(expira)) {
    throw new Error('sessão fora da forma {session, expiry}');
  }
  const largura = dados.tileWidth === undefined ? 256 : Number(dados.tileWidth);
  if (!Number.isFinite(largura) || largura <= 0) throw new Error('sessão com tileWidth inválido');
  return { token: dados.session, expira, largura };
}

export const urlDosTiles = (sessao, chave) => `${ORIGEM}/v1/2dtiles/{z}/{x}/{y}?${new URLSearchParams({ session: sessao.token, key: chave })}`;

// Milissegundos até renovar; nunca negativo (sessão já vencida renova já) nem acima do teto do temporizador.
export function msAteRenovar(sessao, agoraMs) {
  const falta = (sessao.expira - MARGEM_RENOVACAO_S) * 1000 - agoraMs;
  return Math.min(MAXIMO_TEMPORIZADOR_MS, Math.max(0, falta));
}

// Espera antes da próxima tentativa de renovação, dobrando a cada falha (`falhas` >= 1) até o teto.
export const esperaAposFalha = (falhas) => Math.min(ESPERA_MAXIMA_MS, ESPERA_INICIAL_MS * 2 ** (falhas - 1));

// O viewport do Google exige latitude em (-90, 90) e longitude em (-180, 180); o `getBounds()` do MapLibre passa disso com o
// mundo repetido na tela. Vista de 360° ou mais vira o mundo todo; senão a longitude volta para o intervalo (oeste maior que
// leste = vista que cruza o antimeridiano, forma que a doc aceita). Review PR #43, CodeRabbit.
const LIMITE_LAT = 89.999;
const LIMITE_LON = 179.999;
const noIntervalo = (lon) => Math.min(LIMITE_LON, Math.max(-LIMITE_LON, ((((lon + 180) % 360) + 360) % 360) - 180));
export function limitesParaViewport({ norte, sul, leste, oeste }) {
  const lat = (v) => Math.min(LIMITE_LAT, Math.max(-LIMITE_LAT, v));
  const inteiro = leste - oeste >= 360;
  return { norte: lat(norte), sul: lat(sul), leste: inteiro ? LIMITE_LON : noIntervalo(leste), oeste: inteiro ? -LIMITE_LON : noIntervalo(oeste) };
}

// Zoom do tile que o MapLibre de fato pede: round(zoom + log2(512 / tileSize)), preso a 0..22 (doc do Google). Medido em
// 2026-11-04 no Chromium: com tiles de 256 px, `getZoom()` 11,96 pede tiles em z=13, e o viewport tem de ser consultado em 13
// para o crédito bater com as imagens à vista (review PR #43, Codex).
export const zoomDosTiles = (zoom, largura) => Math.min(22, Math.max(0, Math.round(zoom + Math.log2(512 / largura))));

// Atribuição de dados vem do `copyright` do viewport (não se escreve à mão). O texto entra por `textContent`.
export async function buscarAtribuicao(buscar, chave, sessao, { norte, sul, leste, oeste, zoom }, prazoMs = PRAZO_SESSAO_MS) {
  const caixa = limitesParaViewport({ norte, sul, leste, oeste });
  const resposta = await buscar(url('/tile/v1/viewport', { session: sessao.token, key: chave, zoom: Math.round(zoom), north: caixa.norte, south: caixa.sul, east: caixa.leste, west: caixa.oeste }), { signal: AbortSignal.timeout(prazoMs) });
  if (!resposta.ok) throw new Error(`viewport recusado (${resposta.status})`);
  const dados = await resposta.json();
  return typeof dados?.copyright === 'string' ? dados.copyright : '';
}

// Sessão guardada no navegador (token, validade, largura e uma marca da chave; a chave nunca). O token faz parte da URL do
// tile: sessão nova a cada visita muda a URL e o cache do navegador, que o Google libera por 24 h (`private, max-age=86400`,
// ETag; medido em 2026-11-04), nunca acerta e cada visita paga a vista inteira (8 tiles). A doc permite reaproveitar o token
// até `expiry`, cerca de duas semanas ("You can use the same session token across multiple clients"). Dado lido de volta é
// desconfiado: forma errada, vencida, de outra chave ou armazenamento que lança (modo privado) vira sessão nova.
// shortcut: a marca é um hash de 32 bits só para notar troca de chave, não é segurança; trocar por outra coisa se a chave rodar com frequência.
export const CHAVE_ARMAZEM = 'phati.fundo-google.sessao';
const marcaDaChave = (chave) => { let h = 0; for (const c of chave) h = (Math.imul(h, 31) + c.charCodeAt(0)) | 0; return h; };
export function lerSessaoGuardada(armazem, chave, agoraMs) {
  try {
    const d = JSON.parse(armazem.getItem(CHAVE_ARMAZEM));
    const forma = typeof d?.token === 'string' && d.token !== '' && Number.isFinite(d.expira) && Number.isFinite(d.largura) && d.largura > 0;
    return forma && d.marca === marcaDaChave(chave) && msAteRenovar(d, agoraMs) > 0 ? { token: d.token, expira: d.expira, largura: d.largura } : null;
  } catch {
    return null;
  }
}
export function guardarSessao(armazem, chave, sessao) {
  try {
    armazem.setItem(CHAVE_ARMAZEM, JSON.stringify({ ...sessao, marca: marcaDaChave(chave) }));
  } catch {
    // Sem armazenamento (modo privado, cheio): o mapa segue, só perde o reaproveitamento entre visitas.
  }
}

// Mesma forma do `fundo-neutro.js` mais `aoCriarMapa`, que liga a atribuição e a renovação. `relogio` e `buscar` entram
// de fora para o teste não depender de rede nem de tempo real.
export async function criarFundo({ chave, buscar = globalThis.fetch?.bind(globalThis), relogio = globalThis, armazem = globalThis.localStorage }) {
  let sessao = lerSessaoGuardada(armazem, chave, Date.now());
  if (!sessao) {
    sessao = await criarSessao(buscar, chave);
    guardarSessao(armazem, chave, sessao);
  }
  return {
    fontes: { [ID_FONTE]: { type: 'raster', tiles: [urlDosTiles(sessao, chave)], tileSize: sessao.largura } },
    camadas: [{ id: ID_CAMADA, type: 'raster', source: ID_FONTE }],
    aoCriarMapa(mapa, { dados }) {
      let falhas = 0;
      const renovar = async () => {
        try {
          sessao = await criarSessao(buscar, chave);
          guardarSessao(armazem, chave, sessao);
          mapa.getSource(ID_FONTE)?.setTiles([urlDosTiles(sessao, chave)]);
          falhas = 0;
          agendar();
        } catch {
          // Sessão não renovada: o prazo da velha já passou, então a espera cresce em vez de repetir sem pausa. Passado o
          // limite, para; os tiles seguem até o Google recusar e o mapa mostra o erro de tile (R12).
          falhas += 1;
          if (falhas < TENTATIVAS_MAXIMAS) relogio.setTimeout(renovar, esperaAposFalha(falhas));
        }
      };
      const agendar = () => relogio.setTimeout(renovar, msAteRenovar(sessao, Date.now()));
      agendar();
      let ultima = 0;
      let falhasDeCredito = 0;
      let repeticao; // temporizador da repetição pendente: uma só, nunca empilhadas (review PR #43, Greptile)
      const atualizar = async () => {
        relogio.clearTimeout?.(repeticao);
        repeticao = undefined;
        const minha = ++ultima;
        const limites = mapa.getBounds();
        try {
          const texto = await buscarAtribuicao(buscar, chave, sessao, {
            norte: limites.getNorth(), sul: limites.getSouth(), leste: limites.getEast(), oeste: limites.getWest(), zoom: zoomDosTiles(mapa.getZoom(), sessao.largura),
          });
          if (minha === ultima) dados.textContent = texto;
          falhasDeCredito = 0;
        } catch {
          // Falha não apaga o crédito das imagens que seguem à vista. Com o mapa parado nenhum `moveend` viria, então tenta de
          // novo com espera crescente e para no limite (mesma regra da renovação da sessão).
          falhasDeCredito += 1;
          if (minha === ultima && falhasDeCredito < TENTATIVAS_MAXIMAS) repeticao = relogio.setTimeout(atualizar, esperaAposFalha(falhasDeCredito));
        }
      };
      mapa.on('moveend', atualizar);
      void atualizar();
    },
  };
}
