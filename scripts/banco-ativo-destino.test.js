'use strict';
// Destino do compose nas ferramentas que o leem (implantar.sh, restaurar.sh, backup.sh), nas duas direções da volta (spec 009 R15).
// Matriz banco-ativo x `.env`: a combinação que diverge recusa antes de qualquer Docker de escrita; a que bate passa e chama o
// serviço do banco ativo. O Docker é dublê que só anota as chamadas. Roda com: node --test scripts/
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { unix, lerLinhas, escreverFlock } = require('./ajuda-teste');

const PASTA = __dirname;
const SHA = 'a'.repeat(40);
// Dublê do Docker: anota a chamada e devolve um dado sintético no stdout (o backup exige saída não vazia).
const DUBLE_DOCKER = `#!/usr/bin/env bash
echo "$*" >> "$CHAMADAS"
echo "dados-sinteticos"
exit 0
`;

// Matriz: [banco-ativo gravado (ou null = ausente), linha do `.env` (ou null), mensagem de recusa (ou null = passa)].
const MATRIZ = [
  ['banco', 'PHATI_BANCO_DESTINO=banco', null],
  ['banco', null, null],
  ['banco', 'PHATI_BANCO_DESTINO="banco" # nota', null],
  ['banco_novo', 'PHATI_BANCO_DESTINO=banco_novo', null],
  ['banco_novo', null, null],
  ['banco', 'PHATI_BANCO_DESTINO=banco_novo', /estado de banco divergente: \.env aponta banco_novo, banco-ativo não/],
  ['banco_novo', 'PHATI_BANCO_DESTINO=banco', /estado de banco divergente: \.env aponta banco, banco-ativo banco_novo/],
  ['banco', 'PHATI_BANCO_DESTINO=outro', /estado de banco divergente: \.env aponta outro, banco-ativo banco/],
  ['banco_novo', 'PHATI_BANCO_DESTINO=outro', /estado de banco divergente: \.env aponta outro, banco-ativo banco_novo/],
];

function criarVm(ativo, linhaEnv) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'banco-ativo-destino-'));
  fs.mkdirSync(path.join(dir, 'repo', '.git'), { recursive: true });
  fs.mkdirSync(path.join(dir, 'backups'), { recursive: true });
  fs.writeFileSync(path.join(dir, '.env'), `PHATI_BANCO_NOME=phati\n${linhaEnv ? `${linhaEnv}\n` : ''}`, { mode: 0o600 });
  if (ativo !== null) fs.writeFileSync(path.join(dir, 'banco-ativo'), `${ativo}\n`);
  const dump = path.join(dir, 'backups', 'phati-20261127T000000Z-teste.dump');
  fs.writeFileSync(dump, 'dump-sintetico');
  const dublê = path.join(dir, 'docker-dublê.sh');
  fs.writeFileSync(dublê, DUBLE_DOCKER, { mode: 0o755 });
  const flockDublê = escreverFlock(path.join(dir, 'flock-dublê.sh'));
  const chamadas = path.join(dir, 'chamadas.log');
  return {
    dir,
    dump,
    lerChamadas: () => lerLinhas(chamadas),
    limpar: () => fs.rmSync(dir, { recursive: true, force: true }),
    rodar(script, args, extra = {}) {
      return spawnSync('bash', [unix(path.join(PASTA, script)), ...args], {
        encoding: 'utf8',
        env: {
          ...process.env,
          PHATI_DIR: unix(dir),
          DOCKER: unix(dublê),
          CHAMADAS: unix(chamadas),
          PHATI_FLOCK: unix(flockDublê),
          PHATI_ESPERA: '0',
          PHATI_TENTATIVAS: '2',
          PHATI_BANCO_DESTINO: '',
          PHATI_BANCO_NOME: '',
          COMPOSE_PROFILES: '',
          ...extra,
        },
      });
    },
  };
}

// Cada ferramenta recebe os argumentos do seu uso normal. backup.sh não tem trava própria; implantar.sh e restaurar.sh a têm.
const USO = {
  'backup.sh': (vm) => [],
  'restaurar.sh': (vm) => [vm.dump, 'RESTAURAR'],
  'implantar.sh': () => [SHA],
};

for (const script of Object.keys(USO)) {
  for (const [ativo, linhaEnv, msg] of MATRIZ) {
    const nome = `${script}: banco-ativo=${ativo}, ${linhaEnv ?? '.env sem destino'}`;
    test(`${nome} ${msg ? 'recusa antes de qualquer chamada ao Docker' : 'passa a checagem e usa o serviço ativo'}`, () => {
      const vm = criarVm(ativo, linhaEnv);
      try {
        const r = vm.rodar(script, USO[script](vm));
        if (msg) {
          assert.equal(r.status, 1, r.stdout + r.stderr);
          assert.match(r.stderr, msg);
          assert.deepEqual(vm.lerChamadas(), [], 'chamou o Docker antes de recusar');
        } else {
          assert.doesNotMatch(r.stderr, /estado de banco divergente/, r.stderr);
          if (script === 'backup.sh') {
            assert.equal(r.status, 0, r.stderr);
            assert.ok(vm.lerChamadas().some((l) => l.includes(` exec -T ${ativo} `)), `faltou exec no serviço ${ativo}`);
          }
        }
      } finally {
        vm.limpar();
      }
    });
  }
}

test('backup.sh: destino ambiente banco contra banco-ativo=banco_novo recusa (o ambiente vence o .env também na checagem)', () => {
  const vm = criarVm('banco_novo', null);
  try {
    const r = vm.rodar('backup.sh', [], { PHATI_BANCO_DESTINO: 'banco' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /estado de banco divergente: \.env aponta banco, banco-ativo banco_novo/);
    assert.deepEqual(vm.lerChamadas(), []);
  } finally {
    vm.limpar();
  }
});

test('backup.sh: banco-ativo inválido recusa antes do Docker, nos dois sentidos da volta', () => {
  const vm = criarVm('outro', null);
  try {
    const r = vm.rodar('backup.sh', []);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /banco-ativo tem valor inválido/);
    assert.deepEqual(vm.lerChamadas(), []);
  } finally {
    vm.limpar();
  }
});
