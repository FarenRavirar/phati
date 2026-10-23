const { execFileSync } = require('node:child_process');
const path = require('node:path');
// Caminho relativo ao proprio arquivo: a suite tem de testar o hook versionado
// no repo, nao a copia antiga em ~/.claude/hooks (spec 101, F0.7.2).
const HOOK = path.join(__dirname, 'caveman-resposta-final.js');

/**
 * Roda o hook e devolve `{ code, stderr, stdout }`.
 *
 * `execFileSync` LANCA quando o filho sai diferente de 0, e o canal deste hook
 * e justamente `exit 2` — capturar o erro faz parte do contrato, nao e desvio.
 */
function rodar(entrada) {
  try {
    const stdout = execFileSync('node', [HOOK], {
      input: JSON.stringify(entrada),
      stdio: ['pipe', 'pipe', 'pipe'],
    }).toString();
    return { code: 0, stdout, stderr: '' };
  } catch (erro) {
    return {
      code: erro.status,
      stdout: (erro.stdout ?? '').toString(),
      stderr: (erro.stderr ?? '').toString(),
    };
  }
}

const CASES = [
  [
    'parada normal cobra o ruleset',
    {},
    (r) => r.code === 2 && r.stderr.includes('caveman ultra'),
  ],
  [
    // A trava de laco. Sem ela toda resposta seria bloqueada de novo e o turno
    // nunca encerraria.
    'segunda parada no mesmo turno passa',
    { stop_hook_active: true },
    (r) => r.code === 0 && r.stderr === '',
  ],
  [
    // O CC le `stderr || stdout` para o corpo visivel; o stdout cobre o caminho
    // sincrono de `claude -p`.
    'emite decision block no stdout',
    {},
    (r) => JSON.parse(r.stdout).decision === 'block',
  ],
  [
    // O lembrete tem de nomear o que NAO se comprime, senao ele cobra caveman em
    // aviso de seguranca e em texto que sai do chat.
    'nomeia as excecoes do ruleset',
    {},
    (r) =>
      r.stderr.includes('irreversível') &&
      r.stderr.includes('commit') &&
      r.stderr.includes('negação'),
  ],
  [
    // Pedido do mantenedor em 2026-10-22: ponytail obrigatório, como o caveman.
    'cobra ponytail como obrigatório',
    {},
    (r) => r.stderr.includes('ponytail full') && r.stderr.includes('obrigatórios'),
  ],
  [
    // A mensagem reinjeta a cada parada, entao o teto e curto. Medido em
    // 2026-09-21: a 1a versao tinha 977 chars / 20 linhas de prosa, e o ruleset
    // completo ja chega por `SessionStart` e `UserPromptSubmit` (hooks globais
    // `caveman-activate.js` e `caveman-mode-tracker.js`, este ultimo com 360
    // chars por prompt). Aqui basta o gatilho.
    'cabe em 400 chars',
    {},
    (r) => r.stderr.length > 0 && r.stderr.length <= 400,
  ],
];

let fails = 0;
for (const [name, entrada, ok] of CASES) {
  const r = rodar(entrada);
  let passou = false;
  try {
    passou = ok(r);
  } catch {
    passou = false;
  }
  if (!passou) fails += 1;
  console.log(`${passou ? 'ok   ' : 'FALHA'} ${name} -> exit ${r.code}`);
}
console.log(fails === 0 ? `\n${CASES.length}/${CASES.length} OK` : `\n${fails} FALHA(S)`);
process.exit(fails === 0 ? 0 : 1);
