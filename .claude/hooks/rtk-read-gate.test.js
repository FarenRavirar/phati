// Suíte do rtk-read-gate. Escrita em 2026-09-10 (spec 101, F0.7.3): o hook
// existia desde o início sem teste nenhum — a spec afirmava "4 de 4 hooks com
// suíte" e a medição devolveu 3 de 4.
//
// Um gate sem teste é pior que ausente: ninguém sabe se ele reprova o que
// deveria (e aí não protege nada) ou se reprova demais (e aí é desligado na
// primeira vez que atrapalha). Por isso a suíte cobre os dois lados.
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOK = path.join(__dirname, 'rtk-read-gate.js');

// Fixtures reais: o hook lê o arquivo do disco para contar linhas, então não
// dá para simular só com o nome.
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'rtk-read-gate-'));
const write = (nome, linhas) => {
  const p = path.join(TMP, nome);
  fs.writeFileSync(p, 'x\n'.repeat(linhas));
  return p;
};

const PEQUENO = write('pequeno.ts', 10);
const LIMITE = write('limite.ts', 600);        // exatamente no limite: passa
const ACIMA = write('grande.ts', 601);         // um a mais: bloqueia
const ENORME = write('enorme.md', 5000);
const LOCKFILE = write('pnpm-lock.yaml', 50);  // pequeno de propósito: o nome é que manda
const IMAGEM = write('diagrama.svg', 2000);    // extensão isenta
const INEXISTENTE = path.join(TMP, 'nao-existe.ts');

const CASES = [
  // --- deve BLOQUEAR (o gate serve para alguma coisa) ---
  ['arquivo acima do limite', { file_path: ACIMA }, 'BLOQUEIA'],
  ['arquivo muito grande', { file_path: ENORME }, 'BLOQUEIA'],
  ['lockfile, mesmo pequeno', { file_path: LOCKFILE }, 'BLOQUEIA'],

  // --- deve PASSAR (o gate não é hostil) ---
  ['arquivo pequeno', { file_path: PEQUENO }, 'PASSA'],
  ['exatamente no limite (600)', { file_path: LIMITE }, 'PASSA'],
  ['grande, mas com offset', { file_path: ACIMA, offset: 100 }, 'PASSA'],
  ['grande, mas com limit', { file_path: ACIMA, limit: 50 }, 'PASSA'],
  ['grande, com offset e limit', { file_path: ACIMA, offset: 10, limit: 20 }, 'PASSA'],
  ['extensão isenta (.svg)', { file_path: IMAGEM }, 'PASSA'],
  ['arquivo inexistente (deixa o Read dar o erro real)', { file_path: INEXISTENTE }, 'PASSA'],
  ['sem file_path', {}, 'PASSA'],
];

let fails = 0;
for (const [name, toolInput, expected] of CASES) {
  const out = execFileSync('node', [HOOK], {
    input: JSON.stringify({ tool_input: toolInput }),
  }).toString();
  const got = out.trim() ? 'BLOQUEIA' : 'PASSA';
  const ok = got === expected;
  if (!ok) fails += 1;
  console.log(`${ok ? 'ok   ' : 'FALHA'} ${name} -> ${got}${ok ? '' : ` (esperado ${expected})`}`);
}

// Entrada malformada não pode derrubar o turno do agente.
try {
  execFileSync('node', [HOOK], { input: '{nao é json' });
  console.log('ok    entrada malformada não atrapalha o trabalho');
} catch {
  fails += 1;
  console.log('FALHA entrada malformada derrubou o hook');
}

// O motivo do deny precisa ensinar a saída, não só barrar.
const motivo = JSON.parse(
  execFileSync('node', [HOOK], { input: JSON.stringify({ tool_input: { file_path: ACIMA } }) }).toString(),
).hookSpecificOutput.permissionDecisionReason;
if (motivo.includes('rtk read') && motivo.includes('offset')) {
  console.log('ok    motivo do deny traz o comando pronto');
} else {
  fails += 1;
  console.log('FALHA motivo do deny não ensina a saída');
}

fs.rmSync(TMP, { recursive: true, force: true });

const total = CASES.length + 2;
console.log(fails === 0 ? `\n${total}/${total} OK` : `\n${fails} FALHA(S)`);
process.exit(fails === 0 ? 0 : 1);
