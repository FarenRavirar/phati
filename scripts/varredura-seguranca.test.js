'use strict';
// Contrato da varredura de segurança: CodeQL, Dependabot e actions fixadas por SHA.
// Roda com: node --test scripts/
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const RAIZ = path.join(__dirname, '..');
const ler = (...partes) => fs.readFileSync(path.join(RAIZ, ...partes), 'utf8').replace(/\r\n/g, '\n');

test('todo `uses:` dos workflows é fixado por SHA de 40 caracteres', () => {
  const pasta = path.join(RAIZ, '.github', 'workflows');
  const nomes = fs.readdirSync(pasta).filter((n) => /\.ya?ml$/.test(n));
  assert.ok(nomes.length > 0);
  for (const nome of nomes) {
    const usos = ler('.github', 'workflows', nome).match(/^\s*(?:- )?uses: .+$/gm) ?? [];
    for (const uso of usos) {
      assert.match(uso, /@[0-9a-f]{40}( #.*)?$/, `${nome}: ${uso.trim()} sem SHA`);
    }
  }
});

test('CodeQL: python, javascript-typescript e actions, escrita só em security-events no job', () => {
  const texto = ler('.github', 'workflows', 'codeql.yml');
  for (const linguagem of ['python', 'javascript-typescript', 'actions']) {
    assert.match(texto, new RegExp(`^ {10}- ${linguagem}$`, 'm'), `falta ${linguagem}`);
  }
  assert.match(texto, /^permissions:\n {2}contents: read\n/m, 'permissão global só de leitura');
  assert.match(texto, /security-events: write/);
  assert.equal((texto.match(/: write/g) ?? []).length, 1, 'única permissão de escrita é security-events');
  assert.match(texto, /build-mode: none/);
});

test('Dependabot: github-actions, pip, docker e docker-compose, todos semanais', () => {
  const texto = ler('.github', 'dependabot.yml');
  for (const ecossistema of ['github-actions', 'pip', 'docker', 'docker-compose']) {
    assert.match(texto, new RegExp(`package-ecosystem: ${ecossistema}$`, 'm'), `falta ${ecossistema}`);
  }
  assert.equal((texto.match(/interval: weekly/g) ?? []).length, 4);
  assert.doesNotMatch(texto, /auto-?merge/i, 'Dependabot só abre PR; nunca mergeia');
});
