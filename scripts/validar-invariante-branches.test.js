'use strict';
// Suíte do validar-invariante-branches.sh. Roda com: node --test scripts/
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync, spawnSync } = require('node:child_process');

const SCRIPT = path.join(__dirname, 'validar-invariante-branches.sh');

function criarRepositorio() {
  const repositorio = fs.mkdtempSync(path.join(os.tmpdir(), 'invariante-'));
  const git = (...argumentos) => execFileSync('git', argumentos, { cwd: repositorio, stdio: 'pipe' });
  const commitar = (arquivo) => {
    fs.writeFileSync(path.join(repositorio, arquivo), `${arquivo}\n`);
    git('add', arquivo);
    git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', arquivo, '--no-verify');
  };
  const validar = () => spawnSync('bash', [SCRIPT, 'main', 'dev'], { cwd: repositorio, encoding: 'utf8' });
  const limpar = () => fs.rmSync(repositorio, { recursive: true, force: true });
  return { git, commitar, validar, limpar };
}

test('main ancestral de dev passa; commit só em main quebra a invariante', () => {
  const { git, commitar, validar, limpar } = criarRepositorio();
  try {
    git('init', '-q', '-b', 'main');
    commitar('base');
    git('switch', '-q', '-c', 'dev');
    commitar('so-dev');
    const ok = validar();
    assert.equal(ok.status, 0);
    assert.match(ok.stdout, /invariante_branches_ok=true/);

    git('switch', '-q', 'main');
    commitar('so-main');
    const quebrada = validar();
    assert.equal(quebrada.status, 1, 'commit em main que não está em dev bloqueia');
    assert.match(quebrada.stderr, /não é ancestral/);
  } finally {
    limpar();
  }
});
