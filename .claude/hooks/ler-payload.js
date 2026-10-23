// Leitura de stdin dos hooks de governanca. Spec 101, F5 (achado de 2026-09-11).
//
// Por que existe: os 5 hooks liam o payload com `process.stdin.on('end', ...)` e
// punham TODA a logica dentro desse callback. Se quem invoca escreve o payload e
// nao fecha o stdin, o evento 'end' nunca dispara: o processo fica vivo sem
// decidir nada e morre no timeout do chamador.
//
// O sintoma nao parece um bug de stdin — parece hook lento. Medido em 2026-09-11
// com o OpenCode 1.18.30, que relatou ETIMEDOUT em rtk-enforce e rtk-read-gate e
// atribuiu a cold-start do Node. Nao era:
//
//   10 execucoes frias, stdin fechado:  113-138ms, exit=0   (nenhuma perto de 5s)
//   stdin fechado imediato:                57ms,   exit=0
//   stdin fechado so em 6s:              5026ms,   SIGKILL
//   stdin nunca fechado:                 5013ms,   SIGKILL
//
// A diferenca entre passar e travar e quem fecha o stdin — nunca a temperatura
// do processo. Cold-start explicaria lentidao uniforme; o que se mede e 0% de
// lentidao com stdin fechado e 100% de timeout sem ele.
//
// Por que isso e grave alem do incomodo: o `tool.execute.before` do OpenCode
// falha closed (deliberadamente). Hook que nao responde nao "passa batido" — ele
// bloqueia toda chamada de ferramenta, e a sessao inteira trava. O modo de
// falha de um gate que depende do bom comportamento do chamador nao e governanca
// fraca, e paralisia.
//
// A correcao nao confia no chamador:
//   1. 'end'   — caminho normal, resolve na hora.
//   2. 'close' — stdin encerrado sem 'end' (pipe quebrado, fd fechado direto).
//   3. deadline interno — ultima linha de defesa: decide com o que ja chegou.
//
// O deadline e 2s, menor que o menor timeout de chamador conhecido (5s no
// plugin do OpenCode). Precisa ser menor de proposito: se o chamador mata o
// processo antes, quem decide e o timeout dele (fail-closed, turno derrubado);
// decidindo aqui primeiro, o hook responde com o payload que tem — que na
// pratica ja chegou inteiro, porque o dado vem num write so.
//
// `unref()` no timer para que ele nunca segure o processo vivo sozinho: sem
// isso, um hook que ja decidiu ficaria 2s parado a toa em TODA chamada.

'use strict';

const DEADLINE_MS = 2000;

/**
 * Le o payload JSON do stdin e chama `aoReceber(raw)` exatamente uma vez.
 * Nunca fica pendurado esperando um 'end' que talvez nao venha.
 */
function lerPayload(aoReceber) {
  let raw = '';
  let decidido = false;

  const decidir = () => {
    if (decidido) return;
    decidido = true;
    clearTimeout(timer);
    aoReceber(raw);
  };

  // Decide com o que chegou ate aqui. Payload vazio faz o hook sair com 0 (todos
  // tratam JSON invalido assim) — que e o certo: sem comando para inspecionar,
  // nao ha veredito a dar, e travar a chamada seria pior.
  const timer = setTimeout(decidir, DEADLINE_MS);
  if (typeof timer.unref === 'function') timer.unref();

  // Sem isto, `chunk` chega como Buffer e a concatenacao depende do toString
  // implicito — que quebra em multibyte partido entre dois chunks.
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (chunk) => { raw += chunk; });
  process.stdin.on('end', decidir);
  process.stdin.on('close', decidir);
  process.stdin.on('error', decidir);
}

module.exports = { lerPayload, DEADLINE_MS };
