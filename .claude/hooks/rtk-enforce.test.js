#!/usr/bin/env node
// Suíte do rtk-enforce. Roda com: node rtk-enforce.test.js
//
// Existe pelo mesmo motivo de `git-commit-msg-gate.test.js`: regra de hook que
// bloqueia comando precisa de teste, porque um falso-positivo trava trabalho
// legítimo e ninguém descobre até doer. Os casos "passa" importam mais que os
// "bloqueia" — cada um deles é um modo de falha em que o gate atrapalharia.

const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOK = path.join(__dirname, 'rtk-enforce.js');

// Fixture próprio: o gate de `rtk grep` olha o disco (arquivo x diretório), então
// os casos rodam num diretório temporário com `arquivo.md` e `specs/` de verdade.
const FIXTURE = fs.mkdtempSync(path.join(os.tmpdir(), 'rtk-enforce-'));
fs.writeFileSync(path.join(FIXTURE, 'arquivo.md'), '# exemplo\n');
fs.writeFileSync(path.join(FIXTURE, 'outro.md'), '# outro\n');
fs.mkdirSync(path.join(FIXTURE, 'specs'));

const CASES = [
  // --- leitura-parcial-crua (regra nova, 2026-08-07) ---
  { cmd: `sed -n '1,50p' arquivo.ts`, deny: true, rule: 'leitura-parcial-crua' },
  { cmd: `sed -n '300,345p' .github/workflows/exemplo.yml`, deny: true, rule: 'leitura-parcial-crua' },
  { cmd: `sed -n "1,20p" src/app.ts`, deny: true, rule: 'leitura-parcial-crua' },
  { cmd: `head -c 500 src/app.ts`, deny: true, rule: 'leitura-parcial-crua' },
  { cmd: `awk 'NR<50' x.ts`, deny: true, rule: 'leitura-parcial-crua' },

  // Filtro de pipe NÃO é leitura de arquivo — bloquear aqui quebraria o jeito
  // canônico de filtrar segredo da saída da VM (AGENTS.md §Decisão, pausa e dúvida).
  { cmd: `ssh maruko 'sed "s/=.*/=<omitido>/" /opt/phati/.env'`, deny: false },
  { cmd: `cat x.md | sed 's/a/b/'`, deny: false },
  { cmd: `git log | awk '{print $1}'`, deny: false },
  { cmd: `rtk read x.ts`, deny: false },
  // Substituição in-place não é leitura.
  { cmd: `sed -i 's/foo/bar/' x.ts`, deny: false },

  // --- regras pré-existentes: não podem regredir ---
  { cmd: `pnpm verify:api`, deny: true, rule: 'pnpm-script-sem-run' },
  { cmd: `pnpm test`, deny: true, rule: 'pnpm-script-sem-run' },
  { cmd: `pnpm run lint`, deny: true, rule: 'script-pesado-sem-rtk' },
  { cmd: `pnpm --filter @phati/exemplo test`, deny: true, rule: 'pnpm-filter' },
  { cmd: `rtk pnpm run lint`, deny: false },
  { cmd: `rtk pnpm verify:api`, deny: false },
  { cmd: `pnpm install`, deny: false },
  { cmd: `cd apps/exemplo && rtk tsc -p tsconfig.json`, deny: false },
  { cmd: `rtk tsc`, deny: true, rule: 'rtk-subcomando-quebrado-no-turbo' },

  // --- rtk-grep-em-diretorio (spec 101 F3.0) ---
  // Medido: `rtk grep "AGENTS" specs` -> "grep: specs: Is a directory".
  { cmd: `rtk grep "termo" apps`, deny: true },
  { cmd: `rtk grep "padrao" packages/ui`, deny: true },
  // Com -r o grep nativo funciona: nao e o caso que o gate mira.
  { cmd: `rtk grep -r "termo" apps`, deny: false },
  { cmd: `rtk grep -rn "termo" apps`, deny: false },
  // `rtk rg` cobre arquivo e diretorio, entao nunca e bloqueado por esta regra.
  { cmd: `rtk rg "termo" apps`, deny: false },

  // Regressão: sem -r, arquivo único é uso legítimo do grep. O gate olha o disco.
  { cmd: `rtk grep -n X arquivo.md`, deny: false },
  { cmd: `rtk grep -n "termo" arquivo.md`, deny: false },
  { cmd: `rtk grep -n "a b" arquivo.md`, deny: false },
  { cmd: `rtk grep -e "termo" arquivo.md`, deny: false },
  { cmd: `rtk grep -A 2 "termo" arquivo.md`, deny: false },
  { cmd: `rtk grep -n "termo" arquivo.md 2>&1`, deny: false },
  { cmd: `rtk grep -n X specs`, deny: true, rule: 'rtk-grep-em-diretorio' },
  { cmd: `rtk grep -n "termo" arquivo.md specs`, deny: true, rule: 'rtk-grep-em-diretorio' },
  { cmd: `rtk grep -e "termo" specs`, deny: true, rule: 'rtk-grep-em-diretorio' },
  { cmd: `rtk grep -n "termo" arquivo.md && rtk grep -n "x" specs`, deny: true, rule: 'rtk-grep-em-diretorio' },
  { cmd: `rtk grep -rn X specs`, deny: false },
  { cmd: `rtk grep -rn X arquivo.md`, deny: false },
  // Sem alvo: grep lê stdin ou falha; sem -r continua bloqueado.
  { cmd: `rtk grep -n "termo"`, deny: true, rule: 'rtk-grep-em-diretorio' },
  // Caminho inexistente: comportamento anterior preservado (bloqueia sem -r).
  { cmd: `rtk grep -n "termo" inexistente.md`, deny: true, rule: 'rtk-grep-em-diretorio' },

  // Regressão: grep lendo de pipe (stdin) sem alvo é legítimo. Sem pipe, sem alvo, continua bloqueado.
  { cmd: `cmd 2>&1 | rtk grep -n X`, deny: false },
  { cmd: `cmd | rtk grep -n -- "--agent"`, deny: false },
  { cmd: `rtk grep -n X`, deny: true, rule: 'rtk-grep-em-diretorio' },
  // Pipe não libera alvo que é diretório: grep lê o diretório, não o stdin.
  { cmd: `cmd | rtk grep -n X specs`, deny: true, rule: 'rtk-grep-em-diretorio' },

  // A1 — opções com valor são consumidas como o grep faz (separado, anexado, `--`).
  // `-r` que é valor de -e não é recursivo: o alvo `specs` é diretório -> deny.
  { cmd: `rtk grep -e -r specs`, deny: true, rule: 'rtk-grep-em-diretorio' },
  // Padrão anexado (`-ePAT`) é padrão, não alvo: `arquivo.md` continua sendo o alvo.
  { cmd: `rtk grep -nePADRAO arquivo.md`, deny: false },
  { cmd: `rtk grep -nePADRAO specs`, deny: true, rule: 'rtk-grep-em-diretorio' },
  // Valor separado de opção longa (`--include *.md`) não vira alvo.
  { cmd: `rtk grep --include *.md -n X arquivo.md`, deny: false },
  { cmd: `rtk grep --include=*.md -n X arquivo.md`, deny: false },
  { cmd: `rtk grep -A3 -n X arquivo.md`, deny: false },
  // Após `--`, `-r` é padrão literal; aspa também torna o token padrão.
  { cmd: `rtk grep -- -r arquivo.md`, deny: false },
  { cmd: `rtk grep "-r" specs`, deny: true, rule: 'rtk-grep-em-diretorio' },

  // A2 — alvo relativo resolve no diretório do `cd` literal encadeado por `&&`.
  // `../arquivo.md` existe a partir de specs/ (é FIXTURE/arquivo.md).
  { cmd: `cd specs && rtk grep -n X ../arquivo.md`, deny: false },
  // `arquivo.md` só existe no cwd do hook, não em specs/: bloqueia.
  { cmd: `cd specs && rtk grep -n X arquivo.md`, deny: true, rule: 'rtk-grep-em-diretorio' },
  // cd dinâmico: diretório desconhecido, alvo relativo bloqueia.
  { cmd: `cd $ALVO && rtk grep -n X arquivo.md`, deny: true, rule: 'rtk-grep-em-diretorio' },
  // cd após `;` não é encadeado por `&&`: diretório desconhecido.
  { cmd: `cd specs; rtk grep -n X ../arquivo.md`, deny: true, rule: 'rtk-grep-em-diretorio' },

  // A3 — separadores dentro de aspa ou com escape não dividem o segmento.
  { cmd: `rtk grep -n "a;b" arquivo.md`, deny: false },
  { cmd: `rtk grep -n 'a|b' arquivo.md`, deny: false },
  { cmd: `rtk grep -n "a && b" specs`, deny: true, rule: 'rtk-grep-em-diretorio' },
  { cmd: `rtk grep -n a\\;b arquivo.md`, deny: false },

  // A4 — a sugestão reescreve só o segmento negado, não o primeiro `rtk grep`.
  { cmd: `rtk grep -n X arquivo.md && rtk grep -n Y specs`, deny: true, rule: 'rtk-grep-em-diretorio', sugestao: `rtk grep -n X arquivo.md && rtk rg -n Y specs` },
  { cmd: `rtk grep -n X specs && rtk grep -n Y specs`, deny: true, rule: 'rtk-grep-em-diretorio', sugestao: `rtk rg -n X specs && rtk rg -n Y specs` },

  // A6 — vários arquivos existentes passam (contrato: todos os alvos são arquivos existentes).
  { cmd: `rtk grep -n X arquivo.md outro.md`, deny: false },
  { cmd: `rtk grep -n X arquivo.md inexistente.md`, deny: true, rule: 'rtk-grep-em-diretorio' },
  { cmd: `rtk grep -n X arquivo.md outro.md specs`, deny: true, rule: 'rtk-grep-em-diretorio' },

  // --- rtk-diff-solto (spec 101 F3.0) ---
  { cmd: `rtk diff AGENTS.md`, deny: true },
  { cmd: `rtk diff`, deny: true },
  { cmd: `rtk git diff AGENTS.md`, deny: false },
  { cmd: `rtk git diff --stat`, deny: false },
  // Falso-positivo a evitar: mencionar a regra nao dispara a regra.
  { cmd: `rtk rg "rtk diff" AGENTS.md`, deny: false },
];

let failed = 0;

for (const testCase of CASES) {
  let out = '';
  try {
    out = execFileSync(process.execPath, [HOOK], {
      input: JSON.stringify({ tool_input: { command: testCase.cmd } }),
      encoding: 'utf8',
      cwd: FIXTURE,
    });
  } catch {
    console.log(`ERRO ao executar: ${testCase.cmd}`);
    failed += 1;
    continue;
  }

  const denied = out.includes('"permissionDecision":"deny"');

  if (denied !== testCase.deny) {
    console.log(`FALHOU  ${testCase.cmd}`);
    console.log(`        esperado ${testCase.deny ? 'DENY' : 'passar'}, obteve ${denied ? 'DENY' : 'passou'}`);
    failed += 1;
    continue;
  }

  if (denied && testCase.rule) {
    const reason = JSON.parse(out).hookSpecificOutput.permissionDecisionReason;
    if (!reason.includes(testCase.rule)) {
      console.log(`FALHOU  ${testCase.cmd}`);
      console.log(`        regra esperada ${testCase.rule}, motivo: ${reason.split('\n')[0]}`);
      failed += 1;
      continue;
    }
    if (testCase.sugestao && !reason.includes(`  ${testCase.sugestao}`)) {
      console.log(`FALHOU  ${testCase.cmd}`);
      console.log(`        sugestao esperada: ${testCase.sugestao}`);
      console.log(`        motivo: ${reason}`);
      failed += 1;
      continue;
    }
  }

  console.log(`ok      ${denied ? '[DENY]' : '[pass]'} ${testCase.cmd}`);
}

fs.rmSync(FIXTURE, { recursive: true, force: true });

console.log('');
if (failed > 0) {
  console.log(`${failed} de ${CASES.length} falharam`);
  process.exit(1);
}
console.log(`${CASES.length}/${CASES.length} passaram`);

// --- Checagem de higiene do grep (TOCTOU): contrato fixado com statSync injetado, sem disco. ---
// A regra olha o alvo no momento do hook. Alvo que some ou vira diretório depois só faz o grep falhar: o hook não
// revalida na execução e não muda a decisão por isso.
const test = require('node:test');
const assert = require('node:assert/strict');
const { grepPermitido } = require('./rtk-enforce.js');

const arg = (valor) => ({ valor, citado: false });
const ARGS_ARQUIVO = [arg('-n'), arg('X'), arg('arquivo.md')];

test('alvo que é arquivo no momento da checagem passa', () => {
  const chamadas = [];
  const statSync = (caminho) => {
    chamadas.push(caminho);
    return { isDirectory: () => false };
  };

  assert.equal(grepPermitido(ARGS_ARQUIVO, false, '/projeto', statSync), true);
  assert.deepEqual(chamadas, [path.resolve('/projeto', 'arquivo.md')]);
});

test('alvo removido entre a checagem e a execução só faz o comando falhar: o hook não revalida nem nega de novo', () => {
  let estado = 'arquivo';
  let consultas = 0;
  const statSync = () => {
    consultas += 1;
    if (estado === 'arquivo') return { isDirectory: () => false };
    throw Object.assign(new Error('ENOENT'), { code: 'ENOENT' });
  };

  assert.equal(grepPermitido(ARGS_ARQUIVO, false, '/projeto', statSync), true);
  estado = 'removido'; // entre a checagem e o grep rodar
  assert.equal(consultas, 1, 'o hook consulta o disco uma vez, na checagem');
});

test('alvo já removido na checagem é bloqueado (comportamento anterior preservado)', () => {
  const statSync = () => {
    throw Object.assign(new Error('ENOENT'), { code: 'ENOENT' });
  };

  assert.equal(grepPermitido(ARGS_ARQUIVO, false, '/projeto', statSync), false);
});

test('alvo que é diretório na checagem é bloqueado', () => {
  const statSync = () => ({ isDirectory: () => true });

  assert.equal(grepPermitido([arg('-n'), arg('X'), arg('specs')], false, '/projeto', statSync), false);
});
