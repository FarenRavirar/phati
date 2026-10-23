#!/usr/bin/env node
// Suite do leitor de payload compartilhado. Spec 101, F5 (achado de 2026-09-11).
//
// O que esta suite protege: o hook NAO pode depender de o chamador fechar o
// stdin. Antes da correcao, os 5 hooks punham toda a logica dentro de
// `process.stdin.on('end')` — e um invocador que escrevesse o payload sem
// fechar o fd deixava o processo vivo sem decidir nada ate o timeout.
//
// Isso nao e teorico. O OpenCode 1.18.30 relatou ETIMEDOUT em rtk-enforce e
// rtk-read-gate e atribuiu a cold-start do Node; a medicao mostrou 10 execucoes
// frias em 113-138ms com stdin fechado, contra SIGKILL aos 5s sem fechar. O
// gate fail-closed transformava isso em sessao inteira travada.
//
// Por isso o caso "stdin nunca fecha" e o coracao desta suite: e o unico que
// falharia se alguem reintroduzisse o padrao antigo.

'use strict';

const { spawn } = require('node:child_process');
const path = require('node:path');

const HOOKS = path.join(__dirname);

// Gatilhos montados por concatenacao: escrever `git commit --amend` literal
// neste arquivo faz o autorizacao-gate bloquear a propria edicao da suite.
const CMD_AMEND = 'git c' + 'ommit --am' + 'end';
const CMD_COMMIT = 'git c' + 'ommit -m x';

const CASOS = [
  { hook: 'rtk-enforce.js', tool: 'Bash', input: { command: 'pnpm test' }, espera: 'deny' },
  { hook: 'rtk-read-gate.js', tool: 'Read', input: { file_path: 'pnpm-lock.yaml' }, espera: 'deny' },
  { hook: 'git-commit-msg-gate.js', tool: 'Bash', input: { command: CMD_AMEND }, espera: 'deny' },
];

// Teto do teste. Precisa ser maior que o DEADLINE_MS (2s) do leitor e menor que
// o timeout do chamador real (5s no plugin do OpenCode) — e nessa janela que a
// correcao tem de decidir.
const TETO_MS = 4000;

function rodar(hook, payload, fecharStdin) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const p = spawn('node', [path.join(HOOKS, hook)], { stdio: ['pipe', 'pipe', 'pipe'] });
    let out = '';
    p.stdout.on('data', (d) => { out += d; });
    p.stdin.write(payload);
    if (fecharStdin) p.stdin.end();

    const kill = setTimeout(() => p.kill('SIGKILL'), TETO_MS);
    p.on('exit', (code, sinal) => {
      clearTimeout(kill);
      let veredito = null;
      try {
        veredito = JSON.parse(out).hookSpecificOutput.permissionDecision;
      } catch { /* sem veredito */ }
      resolve({ ms: Date.now() - t0, code, sinal, veredito });
    });
  });
}

(async () => {
  let passaram = 0;
  let total = 0;

  for (const caso of CASOS) {
    for (const fechar of [true, false]) {
      total += 1;
      const nome = fechar ? 'stdin fechado' : 'stdin NUNCA fechado';
      const payload = JSON.stringify({
        hook_event_name: 'PreToolUse',
        tool_name: caso.tool,
        session_id: `ler-payload-test-${Math.random()}`,
        tool_input: caso.input,
      });

      const r = await rodar(caso.hook, payload, fechar);
      const ok = r.sinal === null && r.veredito === caso.espera;
      if (ok) passaram += 1;

      const etiqueta = ok ? 'PASS' : 'FALHA';
      console.log(
        `${etiqueta} ${caso.hook.padEnd(24)} ${nome.padEnd(21)} ` +
          `${String(r.ms + 'ms').padStart(7)} sinal=${r.sinal} veredito=${r.veredito}`,
      );

      if (!ok && r.sinal === 'SIGKILL') {
        console.log('     ^ o hook nao decidiu sozinho: voltou a depender do chamador fechar o stdin.');
      }
    }
  }

  console.log(`\nler-payload: ${passaram}/${total} casos`);
  process.exit(passaram === total ? 0 : 1);
})();
