#!/usr/bin/env node
// Explica, no PreToolUse de Bash, qual regra `deny` de permissions bloqueou o comando.
//
// Decisão: hook PreToolUse lê deny do settings · fonte: https://code.claude.com/docs/en/permissions.md e hooks.md · escalável: regras vêm do settings, sem lista no código · robusto: falha fechada no divisor, arquivo ruim ignorado · dinâmico: reflete qualquer regra nova sem editar o hook
//
// Por que existe: quando o Claude Code nega um Bash pelo `permissions.deny`, o
// agente recebe só "negado" e tende a contornar (renomear, trocar de ferramenta).
// Este hook diz qual regra casou, em qual arquivo, em qual trecho, e como reformular.
//
// Semântica, conforme a doc oficial (seções Wildcard patterns e Compound commands):
//   - `Bash(padrão)`: `*` casa qualquer texto, inclusive espaço e `/`; o padrão casa o
//     texto inteiro (ancorado no início e no fim).
//   - comando composto divide-se em subcomandos por `&&`, `||`, `;`, `|`, `|&`, `&` e
//     nova linha; deny casa se qualquer subcomando casar (também em `$(...)`, subshell, `for`).
//   - `Bash(x:*)` (sufixo legado) equivale a prefixo `x`.
//   - Sem regex vindo do settings: `*` é o único curinga; o resto é literal.
//
// Desvio deliberado: o texto inteiro do comando também é testado, além dos subcomandos.
// Custo: pode negar onde o nativo não negaria (só quando o padrão cruza um separador).
// Ganho: aspas mal lidas pelo divisor nunca escondem a regra (falha fechada).
//
// Só `deny` é lido. `ask` não é negado aqui; o `ask` nativo segue pedindo autorização.
//
// Falha aberta, de propósito: settings ausente, JSON inválido, regra malformada ou erro
// interno saem com 0 sem saída. Isso não afrouxa nada: o `deny` nativo continua valendo;
// este hook só explica o bloqueio que já existe.

'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { lerPayload } = require(path.join(__dirname, 'ler-payload.js'));
const { coletar, infoSpecs, raizDoAlvo, shq } = require(path.join(__dirname, 'branch-gate.js'));

const LIMITE_TRECHO = 200;

// Push para o phati-specs (E031/E038 de .specify/memory/errors.md): o deny nativo casa `git push
// origin main` por prefixo e não sabe o repositório. Quem sabe é o branch-gate (alvo via cd, -C,
// --git-dir). Forma certa: `rtk git -C <phati-specs> push origin main`. Reusa coletar do
// branch-gate, sem parser novo. Decisão: resolve alvo e nega forma errada · fonte: errors.md E031 ·
// escalável: mesmo molde do branch-gate · robusto: alvo indeterminado não nega (falha aberta) ·
// dinâmico: phati-specs vem do symlink `specs` de CLAUDE_PROJECT_DIR, não de caminho fixo.

// `*` é o único curinga. Dois ponteiros: sem regex, sem recursão, sem backtracking exponencial.
function casaCuringa(padrao, texto) {
  let i = 0;
  let j = 0;
  let estrela = -1;
  let marca = 0;
  while (j < texto.length) {
    if (i < padrao.length && padrao[i] === '*') {
      estrela = i;
      marca = j;
      i += 1;
    } else if (i < padrao.length && padrao[i] === texto[j]) {
      i += 1;
      j += 1;
    } else if (estrela !== -1) {
      i = estrela + 1;
      marca += 1;
      j = marca;
    } else {
      return false;
    }
  }
  while (i < padrao.length && padrao[i] === '*') i += 1;
  return i === padrao.length;
}

// Divide o comando em subcomandos. Separadores valem só fora de aspas simples. Dentro de
// aspas duplas, `$(` e crase executam de verdade, então também dividem.
function subcomandos(comando) {
  const partes = [];
  let atual = '';
  let aspas = null;
  const corta = () => {
    partes.push(atual);
    atual = '';
  };
  for (let i = 0; i < comando.length; i += 1) {
    const c = comando[i];
    const prox = comando[i + 1];
    if (aspas === "'") {
      if (c === "'") aspas = null;
      atual += c;
      continue;
    }
    if (c === '\\') {
      atual += c + (prox ?? '');
      i += 1;
      continue;
    }
    if (c === '`' || (c === '$' && prox === '(')) {
      corta();
      if (c === '$') i += 1;
      continue;
    }
    if (aspas === '"') {
      if (c === '"') aspas = null;
      atual += c;
      continue;
    }
    if (c === '"' || c === "'") {
      aspas = c;
      atual += c;
      continue;
    }
    if ((c === '&' && prox === '&') || (c === '|' && prox === '|')) {
      corta();
      i += 1;
      continue;
    }
    if (';|&\n()'.includes(c)) {
      corta();
      continue;
    }
    atual += c;
  }
  corta();
  return partes.map((p) => p.trim()).filter(Boolean);
}

// Só `Bash(...)` e `Bash` interessam a este hook. Outras ferramentas e formas malformadas
// devolvem null e são ignoradas.
function parseRegra(texto) {
  if (typeof texto !== 'string') return null;
  const t = texto.trim();
  if (t === 'Bash') return { texto: t, padrao: '*' };
  if (!t.startsWith('Bash(') || !t.endsWith(')')) return null;
  let padrao = t.slice(5, -1);
  if (!padrao) return null;
  if (padrao.endsWith(':*')) padrao = `${padrao.slice(0, -2)}*`;
  return { texto: t, padrao };
}

// Primeira regra `deny` que casa algum subcomando ou o comando inteiro.
// `fontes`: [{ arquivo, deny }], na ordem de precedência de leitura.
function avaliar(comando, fontes) {
  const candidatos = [...new Set([...subcomandos(comando), comando.trim()])];
  for (const fonte of fontes) {
    for (const bruto of fonte.deny) {
      const regra = parseRegra(bruto);
      if (!regra) continue;
      const trecho = candidatos.find((c) => casaCuringa(regra.padrao, c));
      if (trecho !== undefined) return { regra: regra.texto, arquivo: fonte.arquivo, trecho };
    }
  }
  return null;
}

function projetoDir() {
  return process.env.CLAUDE_PROJECT_DIR || path.resolve(__dirname, '..', '..');
}

// Ausente ou inválido vira lista vazia: arquivo ruim é ignorado, nunca derruba o fluxo.
function lerDeny(caminho) {
  try {
    const deny = JSON.parse(fs.readFileSync(caminho, 'utf8'))?.permissions?.deny;
    return Array.isArray(deny) ? deny : [];
  } catch {
    return [];
  }
}

function rotular(caminho, projeto, home) {
  if (caminho.startsWith(projeto + path.sep)) return path.relative(projeto, caminho);
  if (caminho.startsWith(home + path.sep)) return `~/${path.relative(home, caminho)}`;
  return caminho;
}

function carregarFontes(projeto = projetoDir(), home = os.homedir()) {
  const caminhos = [
    path.join(projeto, '.claude', 'settings.json'),
    path.join(projeto, '.claude', 'settings.local.json'),
    path.join(home, '.claude', 'settings.json'),
  ];
  return caminhos.map((c) => ({ arquivo: rotular(c, projeto, home), deny: lerDeny(c) }));
}

function trunca(texto) {
  return texto.length > LIMITE_TRECHO ? `${texto.slice(0, LIMITE_TRECHO)}...` : texto;
}

function mensagem(achado) {
  return [
    `[regra-negada-explicada] Bloqueado pela regra deny \`${achado.regra}\` de ${achado.arquivo}.`,
    `Trecho que casou: \`${trunca(achado.trecho)}\`.`,
    'Reformule: renomeie arquivo ou argumento sem o termo; use Write/Read em vez de mv/cp; um comando simples por chamada.',
  ].join('\n');
}

// Push com alvo phati-specs: o comando certo é o único que o mantenedor copia.
const comandoCerto = (top) => `rtk git -C ${shq(top)} push origin main`;

function mensagemPushSpecs(achado, top) {
  return [
    `[regra-negada-explicada] Bloqueado pela regra deny \`${achado.regra}\` de ${achado.arquivo}.`,
    `Trecho que casou: \`${trunca(achado.trecho)}\`. Alvo: phati-specs.`,
    `Comando certo: \`${comandoCerto(top)}\`. Exige autorização do mantenedor, por ação.`,
  ].join('\n');
}

// Alvo phati-dev ou indeterminado: nenhum contorno, só o caminho oficial de main.
function mensagemPushMain(achado) {
  return [
    `[regra-negada-explicada] Bloqueado pela regra deny \`${achado.regra}\` de ${achado.arquivo}.`,
    `Trecho que casou: \`${trunca(achado.trecho)}\`.`,
    'main só avança pelo workflow promover-dev-para-main (AGENTS.md §Git); push direto em main não existe.',
  ].join('\n');
}

function mensagemPushErrado(comando, top) {
  return [
    '[regra-negada-explicada] Push no phati-specs fora da forma certa.',
    `Trecho: \`${trunca(comando.trim())}\`.`,
    `Comando certo: \`${comandoCerto(top)}\`. phati-specs só recebe push de main (AGENTS.md §Git), com autorização do mantenedor, por ação.`,
  ].join('\n');
}

// Pushes do comando com alvo resolvido. Sem `push` no texto, nem analisa.
function pushesDoComando(comando, cwd) {
  if (!/\bpush\b/.test(comando)) return [];
  return coletar(comando, cwd, 'push').achados.filter((a) => !a.profundidade);
}

const textoResto = (p) => p.resto.map((x) => x.v);
const ehPushMain = (p) => textoResto(p)[0] === 'origin' && /^main/.test(textoResto(p)[1] ?? '');
// Forma certa: `-C` explícito e exatamente `origin main`, sem valor dinâmico.
const ehFormaCerta = (p) => p.globais.some((g) => g.opcao === '-C')
  && p.resto.every((x) => !x.din)
  && textoResto(p).join(' ') === 'origin main';

// Alvo é o phati-specs? Sem o symlink `specs`, nunca. Com --git-dir, o repositório é o próprio
// caminho (o cwd vira work tree e não conta, medido no teste). Sem ele, o topo lido pelo git.
function ehSpecs(p, specs) {
  if (!specs || p.indeterminado) return false;
  if (p.gitDir) return dentroDoSpecs(p.gitDir, specs);
  const top = raizDoAlvo(p);
  if (top) return top === specs.top;
  return p.workTree ? dentroDoSpecs(p.workTree, specs) : false;
}

function dentroDoSpecs(caminho, specs) {
  try {
    const real = fs.realpathSync(caminho);
    return real === specs.top || real.startsWith(specs.top + path.sep);
  } catch {
    return false;
  }
}

function saida(motivo) {
  return {
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: motivo,
    },
  };
}

// Devolve o objeto de saída ou null (sem saída = fluxo normal).
function decidir(raw) {
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    return null;
  }
  if (payload?.tool_name !== 'Bash') return null;
  const comando = payload?.tool_input?.command;
  if (typeof comando !== 'string' || !comando.trim()) return null;
  const cwd = typeof payload.cwd === 'string' && payload.cwd ? payload.cwd : process.cwd();
  const pushes = pushesDoComando(comando, cwd);
  // Só comando com push paga o `git rev-parse` do phati-specs; os demais seguem sem custo extra.
  const specs = pushes.length ? infoSpecs(process.env) : null;
  const achado = avaliar(comando, carregarFontes());
  if (achado) {
    const mainDoSpecs = pushes.find((p) => ehPushMain(p) && ehSpecs(p, specs));
    if (mainDoSpecs) return saida(mensagemPushSpecs(achado, specs.top));
    if (pushes.some(ehPushMain)) return saida(mensagemPushMain(achado));
    return saida(mensagem(achado));
  }
  // Sem deny nativo: push ao phati-specs na forma errada (ex.: `cd ../phati-specs && git push`).
  if (pushes.some((p) => ehSpecs(p, specs) && !ehFormaCerta(p))) return saida(mensagemPushErrado(comando, specs.top));
  return null;
}

if (require.main === module) {
  lerPayload((raw) => {
    let saida = null;
    try {
      saida = decidir(raw);
    } catch {
      saida = null; // falha aberta: o deny nativo continua valendo
    }
    if (saida) console.log(JSON.stringify(saida));
    process.exit(0);
  });
}

module.exports = { avaliar, subcomandos, casaCuringa, parseRegra, carregarFontes, decidir };
