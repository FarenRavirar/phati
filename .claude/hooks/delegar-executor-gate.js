#!/usr/bin/env node
// delegar-executor-gate — PreToolUse(Edit|Write|NotebookEdit): na sessão principal,
// nega edição de código e manda o trabalho ao subagente `executor`.
//
// Por que existe: regra escrita em contexto é esquecida; o hook é determinístico.
// A sessão principal planeja, delega e confere a saída; quem edita é o executor.
//
// Como o subagente é reconhecido: a doc oficial de hooks (code.claude.com/docs/en/hooks,
// consultada em 2026-11-15) diz que o payload de PreToolUse dentro de subagente traz
// `agent_id` (e `agent_type`). Na sessão principal `agent_id` não vem. Por isso o
// veredito usa só `agent_id`, não `agent_type` (que também existe com `--agent`).
//
// Escapes legítimos:
//   - chamada com `agent_id` (subagente, p.ex. o executor) passa.
//   - caminho fora do projeto, extensão que não é código, ou pasta de texto/config
//     (`specs/`, `.specify/`, `sessoes/`, `docs/`, `.claude/`, `.agents/`) passa.
// shortcut: "código" = extensão da lista + pasta servidor/navegador/scripts/testes.
// Notebook (.ipynb) e arquivo de código fora dessas pastas passam; subir a lista se
// isso virar brecha.

const path = require('node:path');
const { lerPayload } = require(path.join(__dirname, 'ler-payload.js'));

const FERRAMENTAS = new Set(['Edit', 'Write', 'NotebookEdit']);
const EXTENSOES_CODIGO = new Set(['.py', '.js', '.ts', '.html', '.css', '.json', '.yaml', '.yml', '.sql', '.sh']);
const PASTAS_CODIGO = new Set(['servidor', 'navegador', 'scripts', 'testes', 'tests']);
const PASTAS_LIVRES = new Set(['specs', '.specify', 'sessoes', 'docs', '.claude', '.agents']);

function decidir(entrada, raiz) {
  if (!entrada || typeof entrada !== 'object') return null;
  if (entrada.agent_id) return null;
  if (!FERRAMENTAS.has(entrada.tool_name)) return null;

  const input = entrada.tool_input;
  const alvo = input && typeof input === 'object' ? (input.file_path ?? input.notebook_path) : undefined;
  if (typeof alvo !== 'string' || alvo === '') return null;

  const base = raiz || entrada.cwd || process.cwd();
  const rel = path.relative(base, path.resolve(base, alvo));
  if (rel === '' || rel.startsWith('..') || path.isAbsolute(rel)) return null;

  const partes = rel.split(/[\\/]+/);
  if (partes.some((p) => PASTAS_LIVRES.has(p))) return null;
  if (!EXTENSOES_CODIGO.has(path.extname(rel).toLowerCase())) return null;
  if (!partes.some((p) => PASTAS_CODIGO.has(p))) return null;

  return (
    `[delegar-executor-gate] ${entrada.tool_name} em código (${rel.split(path.sep).join('/')}) na sessão principal. `
    + 'Delegue ao executor (Agent subagent_type=executor) com objetivo, arquivos, '
    + 'comando de verificação e limites. A sessão principal só planeja e confere a saída.'
  );
}

module.exports = { decidir };

if (require.main === module) {
  lerPayload((raw) => {
    let entrada;
    try {
      entrada = JSON.parse(raw);
    } catch {
      process.exit(0); // payload malformado não derruba o turno
    }
    const motivo = decidir(entrada, process.env.CLAUDE_PROJECT_DIR);
    if (motivo) {
      console.log(JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'deny',
          permissionDecisionReason: motivo,
        },
      }));
    }
    process.exit(0);
  });
}
