#!/usr/bin/env node
// rtk-enforce — PreToolUse(Bash): BLOQUEIA comando cru que o `rtk hook claude`
// deixa passar sem reescrever.
//
// Por que existe: o hook oficial do rtk reescreve a maior parte dos comandos
// (cat/grep/git/tsc/vitest/npx...), mas tem lacunas reais — medidas com
// `rtk hook check` em 2026-07-27, rtk 0.44.0 (remedido em 2026-10-28, rtk 1.1.0:
// mesmas lacunas: pnpm test/build/verify:api/--filter, sed -n e head -c):
//
//   pnpm verify:api          -> No rewrite       <-- lacuna
//   pnpm test                -> No rewrite       <-- lacuna
//   pnpm --filter x test     -> No rewrite       <-- lacuna
//   pnpm run build           -> rtk pnpm run build   (ok)
//   npx vitest run           -> rtk vitest           (ok)
//
// O padrão da falha é `pnpm <script>` sem o `run` explícito. Como o rtk NÃO
// tem modo bloqueante (só reescrita transparente + `exclude_commands` para
// opt-out), a barreira precisa vir do lado do Claude Code, que aceita
// `permissionDecision: "deny"` no PreToolUse.
//
// Por que BLOQUEAR e não reescrever: reescrever silenciosamente esconde o erro
// e o agente nunca aprende o padrão. Um deny devolve o motivo ao agente, que
// reemite o comando certo no mesmo turno — e o incidente fica visível.
//
// Ordem importa: este hook roda DEPOIS do `rtk hook claude` no array de hooks,
// então só vê comando que o rtk já decidiu não reescrever.


const { lerPayload } = require(require('node:path').join(__dirname, 'ler-payload.js'));
const fs = require('node:fs');
const CWD_MARKER = /(^|\s)(cd\s+\S+\s*&&\s*)?/;

// Segmento `rtk grep ...` sem -r passa só se todo alvo é arquivo existente (um
// ou vários). Diretório, alvo inexistente ou nenhum alvo -> não passa (deny),
// salvo nenhum alvo com entrada de pipe (`cmd | rtk grep -n X`): grep lê o stdin.
// Alvo relativo resolve no diretório efetivo do comando: o do hook, movido só por
// `cd <literal>` encadeado por `&&`. Qualquer outro caso deixa o diretório
// desconhecido e alvo relativo bloqueia (comportamento anterior).
// shortcut: não interpreta `$(...)`, crase, subshell `( )` nem `cd` dentro delas;
// subir se algum caso real aparecer.
const path = require('node:path');
const FLAGS_CURTAS_COM_VALOR = new Set(['e', 'f', 'A', 'B', 'C', 'm', 'd', 'D']);
const FLAGS_LONGAS_COM_VALOR = new Set([
  '--regexp', '--file', '--after-context', '--before-context', '--context', '--max-count',
  '--directories', '--devices', '--label', '--include', '--exclude', '--exclude-from',
  '--exclude-dir', '--binary-files',
]);

// Separa o comando em segmentos (`;`, `&`, `&&`, `|`, `||`, `|&`) fora de aspas e
// de escape. `&` ligado a redirecionamento (`2>&1`, `&>arq`) não separa.
function segmentar(cmd) {
  const segs = [];
  let inicio = 0;
  let sepAnterior = '';
  let aspa = null;
  for (let i = 0; i < cmd.length; i++) {
    const c = cmd[i];
    if (aspa) {
      if (c === aspa) aspa = null;
      else if (c === '\\' && aspa === '"') i++;
      continue;
    }
    if (c === '\\') { i++; continue; }
    if (c === '"' || c === "'") { aspa = c; continue; }
    if (c !== ';' && c !== '&' && c !== '|') continue;
    if (c === '&' && (cmd[i - 1] === '>' || cmd[i - 1] === '<' || cmd[i + 1] === '>')) continue;
    let j = i;
    while (j < cmd.length && ';&|'.includes(cmd[j])) j++;
    segs.push({ texto: cmd.slice(inicio, i), sep: sepAnterior, inicio, fim: i });
    sepAnterior = cmd.slice(i, j);
    inicio = j;
    i = j - 1;
  }
  segs.push({ texto: cmd.slice(inicio), sep: sepAnterior, inicio, fim: cmd.length });
  return segs;
}

// Tokeniza como o shell: aspa e escape viram texto literal. `citado` marca token
// com aspa (`"-r"` é padrão, não opção).
function tokenizar(texto) {
  const tokens = [];
  let atual = null;
  let citado = false;
  let aspa = null;
  for (let i = 0; i < texto.length; i++) {
    const c = texto[i];
    if (aspa) {
      if (c === aspa) aspa = null;
      else if (c === '\\' && aspa === '"' && i + 1 < texto.length) atual += texto[++i];
      else atual += c;
      continue;
    }
    if (c === '"' || c === "'") { aspa = c; citado = true; atual = atual ?? ''; continue; }
    if (c === '\\' && i + 1 < texto.length) { atual = (atual ?? '') + texto[++i]; citado = true; continue; }
    if (/\s/.test(c)) {
      if (atual !== null) tokens.push({ valor: atual, citado });
      atual = null;
      citado = false;
      continue;
    }
    atual = (atual ?? '') + c;
  }
  if (atual !== null) tokens.push({ valor: atual, citado });
  return tokens;
}

// Redirecionamento (`2>&1`, `>arq`, `> arq`) não é argumento do grep.
function semRedirecionamento(tokens) {
  const saida = [];
  for (let i = 0; i < tokens.length; i++) {
    const { valor, citado } = tokens[i];
    if (!citado && /^(&|\d*)[<>]/.test(valor)) {
      if (/^(&|\d*)[<>]+&?$/.test(valor)) i++; // `> arq`: o alvo vem no próximo token
      continue;
    }
    saida.push(tokens[i]);
  }
  return saida;
}

// Interpreta as opções como o grep: curta com valor consome o resto do grupo
// (`-A3`, `-ePAT`) ou o próximo token (`-A 3`); longa com valor consome o próximo
// só sem `=`. Após `--`, tudo é posicional. Sem -e/-f, o primeiro posicional é padrão.
function analisarGrep(args) {
  let recursivo = false;
  let temPadrao = false;
  let fimOpcoes = false;
  const posicionais = [];
  for (let i = 0; i < args.length; i++) {
    const { valor, citado } = args[i];
    if (fimOpcoes || citado || !valor.startsWith('-') || valor === '-') { posicionais.push(valor); continue; }
    if (valor === '--') { fimOpcoes = true; continue; }
    if (valor.startsWith('--')) {
      const nome = valor.split('=')[0];
      if (nome === '--recursive' || nome === '--dereference-recursive') recursivo = true;
      if (nome === '--regexp' || nome === '--file') temPadrao = true;
      if (!valor.includes('=') && FLAGS_LONGAS_COM_VALOR.has(nome)) i++;
      continue;
    }
    for (let j = 1; j < valor.length; j++) {
      const letra = valor[j];
      if (letra === 'r' || letra === 'R') recursivo = true;
      if (letra === 'e' || letra === 'f') temPadrao = true;
      if (FLAGS_CURTAS_COM_VALOR.has(letra)) {
        if (j === valor.length - 1) i++;
        break;
      }
    }
  }
  return { recursivo, temPadrao, posicionais };
}

// `dir` é o diretório efetivo do comando, ou null se desconhecido.
// CHECAGEM DE HIGIENE, NÃO DE SEGURANÇA: o alvo é olhado no disco no momento deste hook, e o grep só roda depois.
// Se o alvo sumir ou virar diretório entre as duas coisas, o próprio grep falha (erro, não saída errada). O hook não
// revalida na execução e a regra não muda por isso: sem `--` antes dos alvos na sugestão. Teste: "alvo removido entre
// a checagem e a execução só faz o comando falhar".
function grepPermitido(args, recebePipe, dir, statSync = fs.statSync) {
  const { recursivo, temPadrao, posicionais } = analisarGrep(args);
  if (recursivo) return true;
  const alvos = (temPadrao ? posicionais : posicionais.slice(1)).filter((a) => a !== '-');
  if (alvos.length === 0) return recebePipe;
  return alvos.every((alvo) => {
    if (dir === null && !path.isAbsolute(alvo)) return false;
    try {
      return !statSync(path.resolve(dir ?? '', alvo)).isDirectory();
    } catch {
      return false; // inexistente: bloqueia, como antes
    }
  });
}

// Avalia cada segmento `rtk grep`. Diretório começa no do hook e só muda por
// `cd <literal>` encadeado por `&&`; depois de qualquer outro separador com cd
// visto antes, fica null.
function avaliarGrep(cmd) {
  const resultado = [];
  let dir = process.cwd();
  let cdVisto = false;
  for (const seg of segmentar(cmd)) {
    const tokens = semRedirecionamento(tokenizar(seg.texto));
    const encadeado = seg.sep === '' || seg.sep === '&&';
    if (tokens[0]?.valor === 'cd' && !tokens[0].citado) {
      cdVisto = true;
      const alvo = tokens[1]?.valor;
      const literal = encadeado && dir !== null && tokens.length === 2
        && alvo && alvo !== '-' && !/[$`~*?[]/.test(alvo);
      dir = literal ? path.resolve(dir, alvo) : null;
    } else if (cdVisto && !encadeado) {
      dir = null;
    }
    if (tokens[0]?.valor === 'rtk' && tokens[1]?.valor === 'grep') {
      const negado = !grepPermitido(tokens.slice(2), /^\|&?$/.test(seg.sep), dir);
      resultado.push({ ...seg, negado });
    }
  }
  return resultado;
}

// Cada regra: se `test` casa e `allow` não casa, bloqueia com `fix`.
// ORDEM IMPORTA — a primeira que casar decide. `pnpm-filter` vem antes de
// `pnpm-script-sem-run` porque `--filter` também casa o padrão genérico, e a
// regra genérica produziria `rtk pnpm run --filter x test` (ordem inválida).
const RULES = [
  {
    // Medido em 2026-08-07 com `rtk hook check` (rtk 0.44.0): `cat`, `head` e
    // `tail` SÃO reescritos pela camada 1 (viram `rtk read` com --max-lines /
    // --tail-lines), mas `sed -n 'N,Mp'` e `awk 'NR<N'` devolvem "No rewrite".
    // Mesma intenção — ler um trecho —, mesma economia perdida, e nenhuma
    // barreira nas duas camadas.
    //
    // Não é hipótese: nesta sessão o agente usou `sed -n` 4x para ler trecho de
    // workflow e de compose, sem que nada reclamasse. `head`/`tail` no mesmo
    // lugar teriam sido reescritos sozinhos.
    //
    // Só bloqueia a forma de LEITURA de arquivo (`-n 'N,Mp' arquivo`). `sed`
    // como filtro de pipe (`... | sed 's/x/y/'`) é transformação de texto, não
    // leitura, e continua livre — foi assim que a saída de `.env` da VM foi
    // filtrada para não imprimir segredo.
    name: 'leitura-parcial-crua',
    test: /(^|[;&|]\s*)(sed\s+-n\s+["']?\d+\s*,\s*\d+p|awk\s+["']NR\s*[<>=]|head\s+-c\s*\d+\s+[^|;&]*[./\\])/,
    // Já vindo de um pipe não é leitura de arquivo. `rtk` na frente também passa.
    allow: /(\|\s*(sed|awk)\b)|(^|[;&|]\s*)rtk\s+/,
    fix: (cmd) => {
      // Extrai o alvo: último token que parece caminho de arquivo.
      const file = cmd.trim().split(/\s+/).filter((t) => /[./\\]/.test(t) && !/^["']/.test(t)).pop();
      const target = file || '<arquivo>';
      const range = /-n\s+["']?(\d+)\s*,\s*(\d+)p/.exec(cmd);
      if (range) {
        const offset = Number(range[1]);
        const limit = Number(range[2]) - offset + 1;
        return `Read(file_path="${target}", offset=${offset}, limit=${limit})   # ou: rtk read "${target}"`;
      }
      return `rtk read "${target}"`;
    },
    why: '`sed -n`/`awk NR` para ler trecho não é reescrito pela camada 1 (medido: "No rewrite"), ao contrário de head/tail.',
  },
  {
    // DEB-088-01: `rtk lint` tenta parsear JSON do ESLint e o turbo nao entrega
    // esse formato -> "ESLint output (JSON parse failed: EOF while parsing a
    // value at line 1 column 0)". Mesmo problema em `rtk tsc`. O contorno NAO e
    // cair pro `pnpm` cru (perde a compressao inteira): e `rtk pnpm run <script>`,
    // que funciona (23/23 medido em 2026-07-27).
    name: 'rtk-subcomando-quebrado-no-turbo',
    // SÓ na raiz do monorepo, onde o script passa pelo turbo. Dentro de um app
    // (`cd apps/x && rtk tsc -p tsconfig.json`) o binário roda direto e funciona
    // — bloquear ali seria falso-positivo, e a sugestão sairia sem sentido
    // (`rtk pnpm run build --noEmit -p tsconfig.json`).
    test: /(^|[;&|]\s*)rtk\s+(lint|tsc)\s*(2>&1|\||;|$)/,
    allow: /(^|[;&|]\s*)cd\s+\S*apps[\\/]/,
    fix: (cmd) => cmd.replace(
      /(^|[;&|]\s*)rtk\s+(lint|tsc)\b/,
      (_m, pre, sub) => `${pre}rtk pnpm run ${sub === 'lint' ? 'lint' : 'build'}`,
    ),
    why: 'rtk lint/rtk tsc na RAIZ falham no monorepo turbo com "JSON parse failed" (DEB-088-01).',
  },
  {
    // Lint/build/test/verify SEMPRE passam pelo proxy. Sem esta regra, `pnpm run
    // lint` era aceito cru pelo hook do rtk (que so reescreve o que reconhece) e
    // a compressao se perdia justamente nos comandos de saida mais longa.
    name: 'script-pesado-sem-rtk',
    test: /(^|[;&|]\s*)pnpm\s+run\s+(lint|build|test|typecheck|verify:api)\b/,
    allow: /(^|[;&|]\s*)rtk\s+pnpm\s+run\s+/,
    fix: (cmd) => cmd.replace(/(^|[;&|]\s*)pnpm\s+run\s+/, '$1rtk pnpm run '),
    why: 'lint/build/test/verify tem saida longa — sempre via `rtk pnpm run <script>`.',
  },
  {
    name: 'pnpm-filter',
    test: /(^|[;&|]\s*)pnpm\s+--filter\b/,
    allow: /(^|[;&|]\s*)rtk\s+pnpm\s+--filter\b/,
    fix: (cmd) => cmd.replace(/(^|[;&|]\s*)pnpm\s+--filter\b/, '$1rtk pnpm --filter'),
    why: '`pnpm --filter <pkg> <script>` não é reescrito pelo hook do rtk.',
  },
  {
    name: 'pnpm-script-sem-run',
    // `pnpm <algo>` onde <algo> não é subcomando nativo nem `run`.
    test: /(^|[;&|]\s*)pnpm\s+/,
    allow: /(^|[;&|]\s*)(rtk\s+)?pnpm\s+(run|install|add|remove|exec|dlx|why|list|ls|outdated|update|link|store|config|create|init|publish|pack|audit|licenses|rebuild|prune|patch|deploy|setup|env|bin|root|-v|--version|-h|--help)\b/,
    fix: (cmd) => cmd.replace(/(^|[;&|]\s*)pnpm\s+/, '$1rtk pnpm run '),
    why: 'pnpm <script> sem `run` não é reescrito pelo hook do rtk (lacuna medida em rtk 0.44.0).',
  },
  {
    // Spec 101 F3.0: era pegadinha documentada no AGENTS.md, agora é gate.
    // Regra que depende de o agente lembrar falha; medido nesta base.
    name: 'rtk-grep-em-diretorio',
    // `rtk grep <padrão> <dir>` sem -r/-R: o `grep` do rtk é proxy pro grep
    // NATIVO, não pro ripgrep. Medido: `rtk grep "AGENTS" specs` devolve
    // "grep: specs: Is a directory" e a busca não acontece.
    test: /(^|[;&|]\s*)rtk\s+grep\s+/,
    // Bloqueia quando algum alvo é diretório (ou não há alvo, ou o alvo não
    // existe — mantém o comportamento anterior). Um ou vários arquivos existentes
    // passam: `rtk grep -n X arquivo.md outro.md` é uso legítimo. Função, não
    // regex, porque a decisão depende do disco. Cada segmento é avaliado e a
    // sugestão reescreve só os segmentos negados.
    allow: (cmd) => avaliarGrep(cmd).every((g) => !g.negado),
    fix: (cmd) => avaliarGrep(cmd)
      .filter((g) => g.negado)
      .reverse()
      .reduce((saida, g) => saida.slice(0, g.inicio)
        + g.texto.replace(/^(\s*)rtk\s+grep\b/, '$1rtk rg')
        + saida.slice(g.fim), cmd),
    why: '`rtk grep` é proxy pro grep nativo (não ripgrep): sem `-r` falha em diretório com "Is a directory". `rtk rg` faz busca recursiva.',
  },
  {
    name: 'rtk-diff-solto',
    // `rtk diff <arquivo>` não é o uso certo — o subcomando de diff do git
    // é `rtk git diff`. AGENTS.md §rtk registra a pegadinha desde 2026-07.
    test: /(^|[;&|]\s*)rtk\s+diff\b/,
    allow: /(^|[;&|]\s*)rtk\s+git\s+diff\b/,
    fix: (cmd) => cmd.replace(/(^|[;&|]\s*)rtk\s+diff\b/, '$1rtk git diff'),
    why: '`rtk diff` solto não é o uso certo; o diff do git é `rtk git diff <arquivo>`.',
  },
];

if (require.main === module) lerPayload((raw) => {
  let command = '';
  try {
    command = JSON.parse(raw)?.tool_input?.command ?? '';
  } catch {
    process.exit(0); // payload ilegível nunca bloqueia trabalho
  }
  if (!command) process.exit(0);

  for (const rule of RULES) {
    if (!rule.test.test(command)) continue;
    const permitido = typeof rule.allow === 'function' ? rule.allow(command) : rule.allow.test(command);
    if (permitido) continue;

    const suggestion = rule.fix(command);
    console.log(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason:
          `[rtk-enforce/${rule.name}] ${rule.why}\n`
          + `AGENTS.md exige rtk no lugar do comando cru equivalente.\n\n`
          + `Reemita como:\n  ${suggestion}`,
      },
    }));
    process.exit(0);
  }

  process.exit(0);
});

module.exports = { grepPermitido };
