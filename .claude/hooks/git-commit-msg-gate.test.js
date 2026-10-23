const { execFileSync } = require('node:child_process');
const path = require('node:path');
// Caminho relativo ao proprio arquivo: a suite tem de testar o hook versionado
// no repo, nao a copia antiga em ~/.claude/hooks (spec 101, F0.7.2).
const HOOK = path.join(__dirname, 'git-commit-msg-gate.js');

const CASES = [
  ['incidente herestring', "git commit -m @'\nfix: t\n'@", 'BLOQUEIA'],
  ['heredoc correto', "git commit -F - <<'EOF'\nfix: t\nEOF", 'PASSA'],
  ['amend', 'git commit --amend -m x', 'BLOQUEIA'],
  ['amend depois de &&', 'cd /x && git commit --amend', 'BLOQUEIA'],
  ['commit -m simples', 'git commit -m "fix: algo"', 'PASSA'],
  ['git status', 'git status', 'PASSA'],
  // Falso-positivo real observado 2026-07-29: buscar a regra no doc disparava a regra.
  ['rg buscando amend', 'rtk rg "git commit --amend" AGENTS.md -n', 'PASSA'],
  ['grep buscando herestring', 'grep -n "git commit -m @" AGENTS.md', 'PASSA'],
  ['echo mencionando commit', 'echo "use git commit --amend nunca"', 'PASSA'],
];

let fails = 0;
for (const [name, command, expected] of CASES) {
  const out = execFileSync('node', [HOOK], { input: JSON.stringify({ tool_input: { command } }) }).toString();
  const got = out.trim() ? 'BLOQUEIA' : 'PASSA';
  const ok = got === expected;
  if (!ok) fails += 1;
  console.log(`${ok ? 'ok   ' : 'FALHA'} ${name} -> ${got}${ok ? '' : ` (esperado ${expected})`}`);
}
console.log(fails === 0 ? `\n${CASES.length}/${CASES.length} OK` : `\n${fails} FALHA(S)`);
process.exit(fails === 0 ? 0 : 1);
