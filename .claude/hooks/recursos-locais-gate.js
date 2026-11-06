#!/usr/bin/env node
// recursos-locais-gate — Stop: impede encerrar o turno com contêiner Docker ou `vmmemWSL` rodando.
//
// POR QUE EXISTE
// Pedido urgente do mantenedor em 2026-11-05: o `vmmemWSL` (VM do WSL2 do Docker Desktop) fica de pé depois do trabalho e
// "mata o PC". Quem sobe (PostgreSQL local, compose, Playwright) fecha ao terminar: `docker stop` do que subiu e
// `wsl --shutdown`. Isto é o gatilho; a regra escrita está no AGENTS.md (T0).
//
// CANAL: `exit 2` + stderr em `Stop` (mesmo canal e mesma trava de `caveman-resposta-final.js`): cobra uma vez por parada;
// `stop_hook_active` evita o laço. O hook só mede e avisa, nunca fecha nada sozinho (fechar derruba o banco que outra
// tarefa pode estar usando: quem decide é o agente, que sabe o que ele mesmo subiu).

const { execFileSync } = require('node:child_process');
const path = require('node:path');

const { lerPayload } = require(path.join(__dirname, 'ler-payload.js'));

/** `executar(comando, args)` devolve a saída em texto; falha lança. Devolve o que ainda está de pé. */
function medir(executar) {
  const sobras = [];
  try {
    const rodando = executar('docker', ['ps', '--format', '{{.Names}}']).split(/\r?\n/).filter(Boolean);
    if (rodando.length) sobras.push(`contêineres: ${rodando.join(', ')}`);
  } catch {
    // Docker fora do ar ou ausente: nada de contêiner a fechar.
  }
  try {
    const processos = executar('tasklist', ['/FI', 'IMAGENAME eq vmmemWSL.exe', '/FO', 'CSV', '/NH']);
    if (/vmmemWSL/i.test(processos)) sobras.push('processo vmmemWSL');
  } catch {
    // `tasklist` ausente (fora do Windows): nada a medir.
  }
  return sobras;
}

function mensagem(sobras) {
  return [
    `[recursos-locais] ainda de pé: ${sobras.join('; ')}.`,
    'Fechar antes de terminar: `docker stop <nome>` (só o que você subiu) e depois `wsl --shutdown`.',
    'Se a próxima tarefa precisa deles, avisar o mantenedor em vez de deixar ligado.',
  ].join('\n');
}

if (require.main === module) {
  lerPayload((bruto) => {
    let entrada;
    try {
      entrada = JSON.parse(bruto);
    } catch {
      process.exit(0);
    }
    if (entrada?.stop_hook_active) process.exit(0);
    const sobras = medir((comando, args) => execFileSync(comando, args, { encoding: 'utf8', timeout: 15000, stdio: ['ignore', 'pipe', 'ignore'] }));
    if (!sobras.length) process.exit(0);
    const motivo = mensagem(sobras);
    process.stderr.write(motivo);
    process.stdout.write(JSON.stringify({ decision: 'block', reason: motivo }));
    process.exit(2);
  });
}

module.exports = { medir, mensagem };
