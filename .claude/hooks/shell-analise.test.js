#!/usr/bin/env node
// Suite do analisador compartilhado. Cada caso fixa uma forma de shell que escapava dos hooks
// (achados da revisão de 2026-11-27). Sem mock: o percorredor é puro, e `cd` consulta o disco
// de verdade (os diretórios usados existem ou são inventados para o caso de falha).

'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const os = require('node:os');
const path = require('node:path');
const { percorrer, desmontarGit, resolverDir, PROFUNDIDADE_MAX } = require('./shell-analise.js');

const BASE = '/base-inexistente-do-teste';
const TMP = os.tmpdir();

// Lista os comandos simples visitados: { nome, args, cwds, prefixo } ou { prof: true }.
function coletar(texto, cwds = [BASE]) {
  const out = [];
  percorrer(texto, cwds, (c) => {
    out.push(c.profundidade
      ? { prof: true }
      : { nome: c.nome, args: c.palavras.map((p) => p.v), cwds: c.cwds, prefixo: c.prefixo, ...(c.dado ? { dado: true } : {}) });
  });
  return out;
}

const nomes = (texto, cwds) => coletar(texto, cwds).map((c) => c.nome);

// --- Caminho feliz ---

test('comando simples: nome e argumentos desaspeados', () => {
  assert.deepEqual(coletar('git commit -m "x y"'), [
    { nome: 'git', args: ['commit', '-m', 'x y'], cwds: [BASE], prefixo: {} },
  ]);
});

test('escape de espaço dentro de valor: A\\ B vira uma palavra só (achado 18)', () => {
  const [c] = coletar('git -c user.name=A\\ B commit -m x');
  assert.deepEqual(c.args, ['-c', 'user.name=A B', 'commit', '-m', 'x']);
});

test('atribuição inline vai para prefixo, não para o nome', () => {
  const [c] = coletar('PHATI_GATE_BRANCH=0 git commit');
  assert.equal(c.nome, 'git');
  assert.deepEqual(c.prefixo, { PHATI_GATE_BRANCH: '0' });
});

test('cd para diretório existente troca o cwd do comando seguinte', () => {
  assert.deepEqual(nomes(`cd ${TMP} && git commit`), ['git']);
  assert.deepEqual(coletar(`cd ${TMP} && git commit`)[0].cwds, [path.resolve(TMP)]);
});

test('cd -- e cd -P e -L apontam o diretório certo (achado 17)', () => {
  for (const cmd of [`cd -- ${TMP}`, `cd -P ${TMP}`, `cd -L ${TMP}`]) {
    assert.deepEqual(coletar(`${cmd} && git commit`)[0].cwds, [path.resolve(TMP)], cmd);
  }
});

test('env -C muda o diretório do comando (achado 6)', () => {
  assert.deepEqual(coletar(`env -C ${TMP} git commit`)[0].cwds, [path.resolve(TMP)]);
});

test('wrappers e palavras de controle não escondem o comando (achados 4, 5, 6)', () => {
  assert.deepEqual(nomes('if git commit; then :; fi'), ['git', ':']);
  assert.deepEqual(nomes('sudo -u root -E git commit'), ['git']);
  assert.deepEqual(nomes('sudo -- git commit'), ['git']);
  assert.deepEqual(nomes('env -i A=1 git commit'), ['git']);
  assert.deepEqual(nomes('timeout 5 git commit'), ['git']);
  assert.deepEqual(nomes('nice -n 5 git commit'), ['git']);
  assert.deepEqual(nomes('{ git commit; }'), ['git']);
});

test('redirecionamento antes do comando não é o nome (achado 11)', () => {
  assert.deepEqual(nomes('> /dev/null git commit'), ['git']);
  assert.deepEqual(nomes('2>&1 git commit'), ['git']);
  assert.deepEqual(nomes('2>/dev/null git commit'), ['git']);
});

test('shells incluem dash e ksh com -c (achado 12)', () => {
  assert.deepEqual(nomes('dash -c "git commit"'), ['git']);
  assert.deepEqual(nomes('/bin/ksh -c "git commit"'), ['git']);
});

test('desmontarGit separa globais, subcomando e resto (achados 1 e 18)', () => {
  const palavras = ['-C', '.', '-c', 'a=b', '--git-dir=/g', '--no-pager', 'commit', '-m', 'x']
    .map((v) => ({ v, din: false }));
  const g = desmontarGit(palavras);
  assert.equal(g.sub, 'commit');
  assert.deepEqual(g.globais.map((x) => x.opcao), ['-C', '-c', '--git-dir']);
  assert.deepEqual(g.resto.map((p) => p.v), ['-m', 'x']);
});

test('resolverDir: relativo, absoluto, til e variável', () => {
  assert.equal(resolverDir({ v: 'a' }, '/b'), path.resolve('/b', 'a'));
  assert.equal(resolverDir({ v: '/abs' }, null), path.resolve('/abs'));
  assert.equal(resolverDir({ v: '~/x' }, null), path.join(os.homedir(), 'x'));
});

// --- Caminho infeliz e borda ---

test('cd que pode falhar mantém o original e um candidato desconhecido (achado 3)', () => {
  assert.deepEqual(coletar('cd /nao-existe-xyz; git commit')[0].cwds, [BASE, null]);
  assert.deepEqual(coletar('cd /nao-existe-xyz || git commit')[0].cwds, [BASE, null]);
});

test('cd - e cd com variável deixam o cwd desconhecido (achados 2 e 17)', () => {
  assert.deepEqual(coletar('cd - && git commit')[0].cwds, [null]);
  assert.deepEqual(coletar('cd "$X" && git commit')[0].cwds, [null]);
});

test('cd dentro de subshell, pipeline ou & não vaza para o comando seguinte (achado 7)', () => {
  assert.deepEqual(coletar(`(cd ${TMP}); git commit`)[0].cwds, [BASE]);
  assert.deepEqual(coletar(`cd ${TMP} | cat; git commit`)[0].cwds, [BASE]);
  assert.deepEqual(coletar(`cd ${TMP} & git commit`)[0].cwds, [BASE]);
  assert.deepEqual(coletar(`(cd ${TMP}; git commit)`)[0].cwds, [path.resolve(TMP)]);
});

test('substituição é avaliada com o cwd do ponto onde ocorre (achado 8)', () => {
  assert.deepEqual(coletar(`echo "$(git commit)"; cd ${TMP}`)[0].cwds, [BASE]);
  assert.deepEqual(coletar(`cd ${TMP}; echo "$(git commit)"`)[0].cwds, [path.resolve(TMP)]);
});

test('")" entre aspas dentro de $( ) não fecha a substituição (achado 9)', () => {
  assert.deepEqual(coletar('echo $(echo ")"; git commit -m x)').map((c) => c.nome), ['echo', 'git', 'echo']);
});

test('substituição sem fechamento vai até o fim do texto e ainda é analisada', () => {
  assert.deepEqual(nomes('echo $(git commit'), ['git', 'echo']);
});

// `git commit` dentro de `d` níveis de $( ).
const aninhado = (d) => `echo ${'$(echo '.repeat(d - 1)}$(git commit)${')'.repeat(d - 1)}`;

test('profundidade no limite ainda visita o commit; além do limite vira visita de profundidade (achado 10)', () => {
  assert.ok(coletar(aninhado(PROFUNDIDADE_MAX)).some((c) => c.nome === 'git'), 'no limite, o commit é visto');
  const alem = coletar(aninhado(PROFUNDIDADE_MAX + 1));
  assert.ok(alem.some((c) => c.prof === true), 'além do limite, visita de profundidade');
  assert.ok(!alem.some((c) => c.nome === 'git'), 'o commit além do limite não é omitido em silêncio');
});

test('corpo de heredoc não é comando (achado 19)', () => {
  assert.deepEqual(nomes("git commit -F - <<'FIM'\ngit push --force\nFIM"), ['git']);
  assert.deepEqual(nomes("cat <<'FIM'\ngit commit -m x\nFIM"), ['cat']);
});

test('heredoc alimentando shell é analisado como código (achado 19)', () => {
  assert.deepEqual(nomes("bash <<'FIM'\ngit commit -m x\nFIM"), ['git']);
});

test('echo e grep são dado: o texto não vira comando, mas substituição dentro deles é análise', () => {
  assert.deepEqual(coletar('echo "git commit é o assunto"'), [
    { nome: 'echo', args: ['git commit é o assunto'], cwds: [BASE], prefixo: {}, dado: true },
  ]);
  assert.deepEqual(nomes('rtk rg "git commit" docs'), ['rg']);
  // Substituição é analisada antes do comando que a contém.
  assert.deepEqual(nomes('echo "$(git commit)"'), ['git', 'echo']);
});

test('argumento não citado de echo continua visível ao visitante como texto (sem relaxar o ask antigo)', () => {
  const [c] = coletar('echo git commit -m x');
  assert.equal(c.dado, true);
  assert.deepEqual(c.args, ['git', 'commit', '-m', 'x']);
});

test('entrada vazia ou só de operadores não visita nada', () => {
  assert.deepEqual(coletar(''), []);
  assert.deepEqual(coletar(' ; && || '), []);
});

test('aspa não fechada não derruba a análise', () => {
  assert.deepEqual(nomes('git commit -m "x'), ['git']);
});
