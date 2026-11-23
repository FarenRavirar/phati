#!/usr/bin/env node
// Suíte do regra-negada-explicada. Roda com: node --test .claude/hooks/regra-negada-explicada.test.js
//
// Metade negativa é obrigatória: um hook que nega comando legítimo, ou que
// explica a regra errada, é desligado na primeira vez que atrapalha. Os casos
// "sem saída" importam tanto quanto os "deny": cada um é um modo de falha em que o
// hook atrapalharia trabalho ou mentiria sobre qual regra casou.

'use strict';

const { test, describe, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOK = path.join(__dirname, 'regra-negada-explicada.js');
const { avaliar, subcomandos, casaCuringa, parseRegra } = require(HOOK);

// Raiz temporária com `projeto/.claude/` e `home/.claude/` de fixture. O hook lê
// CLAUDE_PROJECT_DIR e HOME; o teste aponta os dois para a fixture, para não depender
// do settings real da máquina.
let RAIZ;
before(() => {
  RAIZ = fs.mkdtempSync(path.join(os.tmpdir(), 'regra-negada-'));
});
after(() => {
  fs.rmSync(RAIZ, { recursive: true, force: true });
});

let contador = 0;
// `arquivos` mapeia nome dentro de `.claude/` para conteúdo (string bruta, para aceitar JSON inválido).
function montar({ projeto = {}, home = {} } = {}) {
  contador += 1;
  const base = path.join(RAIZ, `caso-${contador}`);
  const dirProjeto = path.join(base, 'projeto');
  const dirHome = path.join(base, 'home');
  for (const [dir, arquivos] of [[dirProjeto, projeto], [dirHome, home]]) {
    fs.mkdirSync(path.join(dir, '.claude'), { recursive: true });
    for (const [nome, conteudo] of Object.entries(arquivos)) {
      fs.writeFileSync(path.join(dir, '.claude', nome), conteudo);
    }
  }
  return { projeto: dirProjeto, home: dirHome };
}

const negar = (deny) => JSON.stringify({ permissions: { deny } });

// Roda o hook como o Claude Code o roda: payload no stdin, saída em stdout, rc.
function rodar(payload, { projeto, home }) {
  const env = { ...process.env, CLAUDE_PROJECT_DIR: projeto, HOME: home };
  const r = spawnSync('node', [HOOK], {
    input: typeof payload === 'string' ? payload : JSON.stringify(payload),
    encoding: 'utf8',
    env,
  });
  return { rc: r.status, saida: r.stdout };
}

const bash = (command) => ({ hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command } });

// Atalho: settings do projeto com `deny`; resultado já parseado (ou null se não negou).
function negacao(command, deny, extra = {}) {
  const amb = montar({ projeto: { 'settings.json': negar(deny), ...extra.projeto }, home: extra.home });
  const r = rodar(bash(command), amb);
  assert.equal(r.rc, 0, 'hook deve sair com 0 sempre');
  return r.saida.trim() ? JSON.parse(r.saida).hookSpecificOutput : null;
}

describe('casaCuringa (padrão Bash(...) do settings)', () => {
  test('* casa qualquer texto, inclusive espaço e /', () => {
    assert.equal(casaCuringa('*reboot*', 'rtk bash /x/a-reboot.sh'), true);
    assert.equal(casaCuringa('rtk bash *', 'rtk bash /x/y z'), true);
  });
  test('sem * o padrão exige igualdade total (ancorado no início e no fim)', () => {
    assert.equal(casaCuringa('ls', 'ls'), true);
    assert.equal(casaCuringa('ls', 'ls -la'), false);
    assert.equal(casaCuringa('ls', 'pls'), false);
    assert.equal(casaCuringa('reboot', 'rtk reboot'), false);
  });
  test('caracteres de regex no settings são literais (a.b não casa axb)', () => {
    assert.equal(casaCuringa('a.b*', 'axb'), false);
    assert.equal(casaCuringa('a.b*', 'a.bc'), true);
    assert.equal(casaCuringa('(x|y)+*', '(x|y)+z'), true);
    assert.equal(casaCuringa('(x|y)+*', 'x'), false);
    assert.equal(casaCuringa('a?b[c]', 'a?b[c]'), true);
    assert.equal(casaCuringa('a?b[c]', 'axbc'), false);
  });
  test('vazio casa só vazio', () => {
    assert.equal(casaCuringa('', ''), true);
    assert.equal(casaCuringa('', 'a'), false);
  });
});

describe('subcomandos (divisor respeitando aspas)', () => {
  test('divide por && || ; | |& & e nova linha', () => {
    assert.deepEqual(subcomandos('a && b || c; d | e |& f & g\nh'), ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']);
  });
  test('não divide dentro de aspas simples nem duplas', () => {
    assert.deepEqual(subcomandos("echo 'a; b' && c"), ["echo 'a; b'", 'c']);
    assert.deepEqual(subcomandos('echo "a; b" ; c'), ['echo "a; b"', 'c']);
  });
  test('substituição $( ) e crase dividem mesmo dentro de aspas duplas (executam)', () => {
    const partes = subcomandos('echo "$(reboot)"');
    assert.ok(partes.length >= 2, `não dividiu: ${JSON.stringify(partes)}`);
    assert.ok(partes.some((p) => p.includes('reboot')), `partes: ${JSON.stringify(partes)}`);
    assert.ok(subcomandos('echo `reboot`').some((p) => p.includes('reboot')));
  });
  test('aspas não fechadas não lançam erro e devolvem algo', () => {
    assert.doesNotThrow(() => subcomandos('echo "abc; reboot'));
    assert.ok(subcomandos('echo "abc; reboot').length >= 1);
  });
  test('barra invertida escapa o separador fora de aspas', () => {
    assert.deepEqual(subcomandos('echo a\\;b'), ['echo a\\;b']);
  });
});

describe('parseRegra', () => {
  test('Bash(padrão) vira o padrão; Bash puro casa tudo', () => {
    assert.deepEqual(parseRegra('Bash(*reboot*)'), { texto: 'Bash(*reboot*)', padrao: '*reboot*' });
    assert.deepEqual(parseRegra('Bash'), { texto: 'Bash', padrao: '*' });
  });
  test('sufixo legado :* vira prefixo', () => {
    assert.equal(parseRegra('Bash(ssh maruko:*)').padrao, 'ssh maruko*');
  });
  test('regra de outra ferramenta, malformada ou não-texto devolve null', () => {
    assert.equal(parseRegra('Read(**/.env)'), null);
    assert.equal(parseRegra('Bash('), null);
    assert.equal(parseRegra('Bash()'), null);
    assert.equal(parseRegra('Bash(x'), null);
    assert.equal(parseRegra(42), null);
    assert.equal(parseRegra(null), null);
  });
});

describe('avaliar (qual regra deny casa)', () => {
  const fonte = (deny) => [{ arquivo: '.claude/settings.json', deny }];

  test('comando sem regra: sem achado', () => {
    assert.equal(avaliar('ls -la', fonte(['Bash(*reboot*)'])), null);
  });
  test('comando composto: a regra casa o subcomando e o trecho é ele', () => {
    const a = avaliar('ls; rtk bash /x/reboot.sh', fonte(['Bash(*reboot*)']));
    assert.equal(a.trecho, 'rtk bash /x/reboot.sh');
  });
  test('regra que cruza separador casa o comando inteiro (mais negação, nunca menos)', () => {
    const a = avaliar('ls; reboot', fonte(['Bash(*; reboot*)']));
    assert.equal(a.trecho, 'ls; reboot');
  });
  test('padrão sem * exige o trecho inteiro: Bash(ls) não casa ls -la nem rtk ls', () => {
    assert.equal(avaliar('ls -la', fonte(['Bash(ls)'])), null);
    assert.equal(avaliar('rtk ls', fonte(['Bash(ls)'])), null);
    assert.equal(avaliar('ls', fonte(['Bash(ls)'])).trecho, 'ls');
  });
  test('lista vazia de regras: sem achado', () => {
    assert.equal(avaliar('reboot', []), null);
  });
});

describe('hook (processo, contrato de stdin/stdout)', () => {
  test('feliz: comando sem regra casada não gera saída e sai com 0', () => {
    const amb = montar({ projeto: { 'settings.json': negar(['Bash(*reboot*)']) } });
    const r = rodar(bash('ls -la'), amb);
    assert.equal(r.rc, 0);
    assert.equal(r.saida, '');
  });

  test('rtk bash /x/a-reboot.sh com deny *reboot*: deny com regra, arquivo e trecho no motivo', () => {
    const h = negacao('rtk bash /x/a-reboot.sh', ['Bash(*reboot*)']);
    assert.equal(h.hookEventName, 'PreToolUse');
    assert.equal(h.permissionDecision, 'deny');
    assert.match(h.permissionDecisionReason, /Bash\(\*reboot\*\)/);
    assert.match(h.permissionDecisionReason, /\.claude\/settings\.json/);
    assert.match(h.permissionDecisionReason, /rtk bash \/x\/a-reboot\.sh/);
    assert.match(h.permissionDecisionReason, /Write\/Read/);
  });

  test('composto ls; rtk bash /x/reboot.sh', () => {
    const h = negacao('ls; rtk bash /x/reboot.sh', ['Bash(*reboot*)']);
    assert.match(h.permissionDecisionReason, /rtk bash \/x\/reboot\.sh/);
  });

  test('atribuição inicial VAR=1; rtk bash a-reboot.sh ainda casa', () => {
    const h = negacao('VAR=1; rtk bash a-reboot.sh', ['Bash(*reboot*)']);
    assert.match(h.permissionDecisionReason, /rtk bash a-reboot\.sh/);
  });

  test("bash -lc 'reboot' casa pelo texto da chamada", () => {
    const h = negacao("bash -lc 'reboot'", ['Bash(*reboot*)']);
    assert.equal(h.permissionDecision, 'deny');
  });

  test('sufixo :* funciona como prefixo', () => {
    assert.equal(negacao('ssh maruko docker ps', ['Bash(ssh maruko:*)']).permissionDecision, 'deny');
    assert.equal(negacao('ssh maruko', ['Bash(ssh maruko:*)']).permissionDecision, 'deny');
    assert.equal(negacao('ssh outro-host docker ps', ['Bash(ssh maruko:*)']), null);
  });

  test('settings ausente em ambos os lugares: sem saída, rc 0', () => {
    const amb = montar({});
    const r = rodar(bash('reboot'), amb);
    assert.equal(r.rc, 0);
    assert.equal(r.saida, '');
  });

  test('JSON inválido no projeto é ignorado; deny válido no home ainda casa e é citado', () => {
    const amb = montar({
      projeto: { 'settings.json': '{ isto não é json' },
      home: { 'settings.json': negar(['Bash(*reboot*)']) },
    });
    const r = rodar(bash('reboot'), amb);
    assert.equal(r.rc, 0);
    const h = JSON.parse(r.saida).hookSpecificOutput;
    assert.match(h.permissionDecisionReason, /~\/\.claude\/settings\.json/);
  });

  test('regra malformada é ignorada; a válida ao lado ainda casa', () => {
    const h = negacao('reboot', ['Bash(', 42, 'Bash(*reboot*)']);
    assert.match(h.permissionDecisionReason, /Bash\(\*reboot\*\)/);
  });

  test('só regra malformada: sem saída, rc 0', () => {
    const amb = montar({ projeto: { 'settings.json': negar(['Bash(', 'Bash()', 7]) } });
    const r = rodar(bash('reboot'), amb);
    assert.equal(r.rc, 0);
    assert.equal(r.saida, '');
  });

  test('valor com caractere de regex não casa de forma regex (a.b* não casa axb)', () => {
    assert.equal(negacao('axb', ['Bash(a.b*)']), null);
    assert.equal(negacao('a.bc', ['Bash(a.b*)']).permissionDecision, 'deny');
  });

  test('comando vazio ou só espaço: sem saída, rc 0', () => {
    const amb = montar({ projeto: { 'settings.json': negar(['Bash(*)']) } });
    assert.equal(rodar(bash(''), amb).saida, '');
    assert.equal(rodar(bash('   '), amb).saida, '');
    assert.equal(rodar({ tool_name: 'Bash', tool_input: {} }, amb).saida, '');
  });

  test('payload não-Bash: sem saída mesmo com o termo proibido no input', () => {
    const amb = montar({ projeto: { 'settings.json': negar(['Bash(*reboot*)']) } });
    const r = rodar({ tool_name: 'Read', tool_input: { command: 'reboot' } }, amb);
    assert.equal(r.rc, 0);
    assert.equal(r.saida, '');
  });

  test('payload ilegível (não é JSON): sai com 0 sem saída', () => {
    const amb = montar({ projeto: { 'settings.json': negar(['Bash(*reboot*)']) } });
    const r = rodar('isto não é json', amb);
    assert.equal(r.rc, 0);
    assert.equal(r.saida, '');
  });

  test('ask não é negado por este hook', () => {
    const amb = montar({ projeto: { 'settings.json': JSON.stringify({ permissions: { ask: ['Bash(git commit:*)'] } }) } });
    const r = rodar(bash('git commit -m x'), amb);
    assert.equal(r.rc, 0);
    assert.equal(r.saida, '');
  });

  test('regra de Read no deny não casa Bash', () => {
    assert.equal(negacao('cat .env', ['Read(**/.env)']), null);
  });

  test('regra no settings.local.json: o motivo cita esse arquivo', () => {
    const amb = montar({
      projeto: { 'settings.json': negar([]), 'settings.local.json': negar(['Bash(*foo*)']) },
    });
    const r = rodar(bash('rtk bash foo.sh'), amb);
    assert.match(JSON.parse(r.saida).hookSpecificOutput.permissionDecisionReason, /\.claude\/settings\.local\.json/);
  });

  test('aspas não fechadas: o comando inteiro ainda é testado (falha fechada)', () => {
    const h = negacao('echo "abc; reboot', ['Bash(*reboot*)']);
    assert.equal(h.permissionDecision, 'deny');
  });
});
