#!/usr/bin/env node
// rtk-read-gate — PreToolUse(Read): bloqueia leitura INTEGRAL de arquivo grande.
//
// Por que existe: o hook do rtk só intercepta o tool Bash. `Read`, `Grep` e
// `Glob` são tools nativos do Claude Code e passam por fora dele — é por isso
// que "esqueci de usar rtk read" não é pego por nada hoje, e vira o modo de
// falha mais frequente.
//
// AGENTS.md (§Diagnóstico local / §rtk): "rtk read <arquivo> (nunca cat/Read
// direto pra arquivo grande sem justificar)". A palavra operante é GRANDE:
// bloquear todo Read seria hostil e inútil (arquivo pequeno é mais barato ler
// direto do que passar pelo proxy). O gate mira o caso caro.
//
// Como escapar legitimamente, sem desligar nada:
//   - passar `offset`/`limit`  -> leitura parcial, é justamente o comportamento
//     desejado num arquivo grande; o gate deixa passar.
//   - `rtk read <arquivo>` via Bash -> saída filtrada, o caminho canônico.
// Um Read integral de arquivo grande não tem escapatória silenciosa: é bloqueado
// com o comando pronto no motivo.


const { lerPayload } = require(require('node:path').join(__dirname, 'ler-payload.js'));
const fs = require('node:fs');
const path = require('node:path');

// Limiar em linhas. Abaixo disso o proxy não paga o próprio custo.
const MAX_LINES = 600;

// Extensões que o rtk read não comprime melhor que a leitura nativa, ou onde
// a leitura integral é o ponto (imagem, PDF, notebook são tratados à parte pelo
// próprio Read).
const SKIP_EXT = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.pdf', '.ipynb', '.lock']);

lerPayload((raw) => {
  let input;
  try {
    input = JSON.parse(raw)?.tool_input ?? {};
  } catch {
    process.exit(0);
  }

  const filePath = input.file_path;
  if (!filePath) process.exit(0);

  // Leitura já delimitada: é exatamente o que se quer num arquivo grande.
  if (input.offset !== undefined || input.limit !== undefined) process.exit(0);

  if (SKIP_EXT.has(path.extname(filePath).toLowerCase())) process.exit(0);

  // Lockfile é sempre enorme e nunca se lê inteiro de propósito — bloquear é o
  // comportamento correto, mas a mensagem genérica ("use rtk read") é péssima
  // aqui: ninguém quer a saída filtrada de um lockfile, quer uma linha dele.
  if (/^(pnpm-lock\.yaml|package-lock\.json|yarn\.lock|Cargo\.lock|poetry\.lock)$/i.test(path.basename(filePath))) {
    console.log(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason:
          `[rtk-read-gate] ${path.basename(filePath)} é lockfile — nunca se lê inteiro.\n`
          + `Buscar o pacote específico: rtk rg "<pacote>" "${filePath}"`,
      },
    }));
    process.exit(0);
  }

  let lines;
  try {
    const stat = fs.statSync(filePath);
    if (!stat.isFile()) process.exit(0);
    // Conta linhas sem carregar tudo em memória de uma vez só para arquivos
    // absurdos: acima de 5 MB já bloqueia sem contar.
    if (stat.size > 5 * 1024 * 1024) {
      lines = Infinity;
    } else {
      // Off-by-one achado pela suíte (2026-09-10, spec 101 F0.7.3): arquivo
      // terminado em newline — praticamente todos — produz um elemento vazio
      // no fim do split, então 600 linhas de conteúdo contavam 601 e o limite
      // efetivo era 599, não o MAX_LINES anunciado. Descartar o vazio final.
      const parts = fs.readFileSync(filePath, 'utf8').split('\n');
      if (parts[parts.length - 1] === '') parts.pop();
      lines = parts.length;
    }
  } catch {
    process.exit(0); // arquivo inexistente/binário: deixa o Read dar o erro real
  }

  if (lines <= MAX_LINES) process.exit(0);

  const shown = lines === Infinity ? '>5MB' : `${lines} linhas`;
  console.log(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason:
        `[rtk-read-gate] ${path.basename(filePath)} tem ${shown} — acima do limite de ${MAX_LINES}.\n`
        + `AGENTS.md: "nunca cat/Read direto pra arquivo grande sem justificar".\n\n`
        + `Escolha uma:\n`
        + `  1. Saída filtrada:  rtk read "${filePath}"\n`
        + `  2. Trecho específico: Read com offset/limit (passa direto por este gate)\n`
        + `  3. Buscar o símbolo: LSP (goToDefinition/findReferences) ou rtk rg`,
    },
  }));
  process.exit(0);
});
