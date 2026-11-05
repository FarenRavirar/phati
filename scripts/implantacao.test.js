'use strict';
// Suíte dos scripts de implantação (spec 006): implantar, restaurar, guarda do workflow e smoke externo.
// Roda com: node --test scripts/
// O Docker é trocado por um dublê que só anota as chamadas; o que se prova aqui é a ordem dos passos e as recusas.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { execFile, execFileSync, spawn, spawnSync } = require('node:child_process');
const { promisify } = require('node:util');

const ASSINCRONO = promisify(execFile);
const PASTA = __dirname;
const IMPLANTAR = path.join(PASTA, 'implantar.sh');
const RESTAURAR = path.join(PASTA, 'restaurar.sh');
const BACKUP = path.join(PASTA, 'backup.sh');
const GUARDAR = path.join(PASTA, 'guardar-implantacao.sh');
const SMOKE = path.join(PASTA, 'smoke-implantacao.sh');
const unix = (caminho) => caminho.replace(/\\/g, '/');
const SHA_RUIM = 'não-é-sha';

const git = (diretorio, ...argumentos) =>
  execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', ...argumentos], { cwd: diretorio, stdio: 'pipe', encoding: 'utf8' }).trim();

// VM de mentira: remoto com `main`, clone em `repo/` (com a pasta `servidor/`), `.env` e um `docker` que anota e responde.
function criarVm({ comEnv = true } = {}) {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), 'implantacao-'));
  const remoto = path.join(raiz, 'remoto.git');
  const vm = path.join(raiz, 'vm');
  const repo = path.join(vm, 'repo');
  const trabalho = path.join(raiz, 'trabalho');
  execFileSync('git', ['init', '-q', '--bare', '-b', 'main', remoto]);
  execFileSync('git', ['clone', '-q', remoto, trabalho], { stdio: 'pipe' });
  fs.mkdirSync(path.join(trabalho, 'servidor'));
  fs.writeFileSync(path.join(trabalho, 'servidor', 'arquivo'), 'a\n');
  git(trabalho, 'add', '.');
  git(trabalho, 'commit', '-q', '-m', 'um');
  git(trabalho, 'branch', '-M', 'main');
  git(trabalho, 'push', '-q', 'origin', 'main');
  const promovido = git(trabalho, 'rev-parse', 'HEAD');
  git(trabalho, 'switch', '-q', '-c', 'fora');
  fs.writeFileSync(path.join(trabalho, 'servidor', 'outro'), 'b\n');
  git(trabalho, 'add', '.');
  git(trabalho, 'commit', '-q', '-m', 'fora de main');
  git(trabalho, 'push', '-q', 'origin', 'fora');
  const foraDeMain = git(trabalho, 'rev-parse', 'HEAD');
  fs.mkdirSync(vm);
  execFileSync('git', ['clone', '-q', remoto, repo], { stdio: 'pipe' });
  if (comEnv) fs.writeFileSync(path.join(vm, '.env'), 'PHATI_X=1\n');
  const chamadas = path.join(raiz, 'chamadas.log');
  const dublê = path.join(raiz, 'docker-dubles.sh');
  fs.writeFileSync(
    dublê,
    [
      '#!/usr/bin/env bash',
      'echo "$*" >> "$CHAMADAS"',
      'case "$*" in',
      '  *" build"*) [[ "${DUBLE_BUILD_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"up -d --no-deps app"*) [[ "${DUBLE_APP_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"exec -T banco"*pg_restore*) [[ "${DUBLE_RESTAURA_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"ps -q banco"*) [[ "${DUBLE_BANCO:-1}" == 1 ]] && echo banco1 ;;',
      '  *"ps -q app"*) echo app1 ;;',
      '  *"exec -T banco"*pg_dump*) echo "dados-do-banco" ;;',
      '  inspect*) echo "${DUBLE_SAUDE:-healthy}" ;;',
      '  "volume inspect"*) [[ "${DUBLE_VOLUME:-0}" == 1 ]] || exit 1 ;;',
      'esac',
      'exit 0',
      '',
    ].join('\n'),
    { mode: 0o755 },
  );
  // `flock` de mentira, com a mesma linha de comando (`-w T -E N arquivo comando...`): "ocupado" é o arquivo `<trava>.ocupado`.
  // O `flock` de verdade tem o passo próprio do CI (`trava-flock.test.sh`); aqui se prova o que o script faz com ele.
  const flockChamadas = path.join(raiz, 'flock.log');
  const flockDuble = path.join(raiz, 'flock-dubles.sh');
  fs.writeFileSync(
    flockDuble,
    [
      '#!/usr/bin/env bash',
      'echo "$*" >> "$FLOCK_CHAMADAS"',
      't=0; e=1',
      'while [[ "${1:-}" == -* ]]; do case "$1" in -w) t="$2"; shift 2 ;; -E) e="$2"; shift 2 ;; *) shift ;; esac; done',
      'arquivo="$1"; shift',
      'if [[ -e "$arquivo.ocupado" ]]; then sleep "$t"; exit "$e"; fi',
      'exec "$@"',
      '',
    ].join('\n'),
    { mode: 0o755 },
  );
  const ambiente = {
    ...process.env,
    PHATI_DIR: unix(vm),
    DOCKER: unix(dublê),
    PHATI_FLOCK: unix(flockDuble),
    FLOCK_CHAMADAS: unix(flockChamadas),
    CHAMADAS: unix(chamadas),
    PHATI_ESPERA: '0',
    PHATI_TENTATIVAS: '2',
  };
  const rodar = (script, argumentos, extra = {}) =>
    spawnSync('bash', [unix(script), ...argumentos], { env: { ...ambiente, ...extra }, encoding: 'utf8' });
  const lerChamadas = () => (fs.existsSync(chamadas) ? fs.readFileSync(chamadas, 'utf8').split('\n').filter(Boolean) : []);
  const indice = (trecho) => lerChamadas().findIndex((linha) => linha.includes(trecho));
  const lerFlock = () => (fs.existsSync(flockChamadas) ? fs.readFileSync(flockChamadas, 'utf8').split('\n').filter(Boolean) : []);
  const registro = () => {
    const arquivo = path.join(vm, 'implantacoes.log');
    return fs.existsSync(arquivo) ? fs.readFileSync(arquivo, 'utf8') : '';
  };
  const limpar = () => fs.rmSync(raiz, { recursive: true, force: true });
  return { vm, repo, promovido, foraDeMain, rodar, lerChamadas, lerFlock, indice, registro, limpar };
}

test('implantar recusa SHA mal formado, opção estranha e injeção de comando, sem chamar o Docker', () => {
  const v = criarVm();
  try {
    for (const ruim of [SHA_RUIM, 'abc', `${'a'.repeat(40)}; rm -rf /`, 'A'.repeat(40)]) {
      const r = v.rodar(IMPLANTAR, [ruim]);
      assert.equal(r.status, 1, ruim);
      assert.match(r.stderr, /SHA completo/);
    }
    const opcao = v.rodar(IMPLANTAR, [v.promovido, '--apagar-tudo']);
    assert.equal(opcao.status, 1);
    assert.match(opcao.stderr, /só --sem-migracao/);
    assert.deepEqual(v.lerChamadas(), []);
  } finally {
    v.limpar();
  }
});

test('implantar lê o pedido de SSH_ORIGINAL_COMMAND e recusa o que não for SHA', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [], { SSH_ORIGINAL_COMMAND: 'bash -c "id"' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /SHA completo/);
    const vazio = v.rodar(IMPLANTAR, [], { SSH_ORIGINAL_COMMAND: '' });
    assert.equal(vazio.status, 1);
    const ok = v.rodar(IMPLANTAR, [], { SSH_ORIGINAL_COMMAND: v.promovido, PHATI_REF: 'origin/main' });
    assert.equal(ok.status, 0, ok.stderr);
    assert.match(ok.stdout, /implantado=/);
  } finally {
    v.limpar();
  }
});

test('implantar recusa execução sem .env, sem clone e SHA que não está em main', () => {
  const semEnv = criarVm({ comEnv: false });
  try {
    const r = semEnv.rodar(IMPLANTAR, [semEnv.promovido]);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /\.env ausente/);
  } finally {
    semEnv.limpar();
  }
  const v = criarVm();
  try {
    const fora = v.rodar(IMPLANTAR, [v.foraDeMain]);
    assert.equal(fora.status, 1);
    assert.match(fora.stderr, /não é ancestral de origin\/main/);
    assert.deepEqual(v.lerChamadas(), [], 'nada de Docker antes de conferir o SHA');
    assert.match(v.registro(), /FALHOU/);
    const inexistente = v.rodar(IMPLANTAR, ['f'.repeat(40)]);
    assert.equal(inexistente.status, 1);
    assert.match(inexistente.stderr, /não existe/);
  } finally {
    v.limpar();
  }
});

test('implantar: backup, build, parar o app, migrar, estáticos, app e só então nginx e túnel, nessa ordem', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 0, r.stderr);
    const ordem = ['pg_dump', ' build', 'stop app', 'run --rm migracao', 'run --rm --no-deps estaticos', 'up -d --no-deps app', 'up -d --no-deps --force-recreate nginx', 'up -d --no-deps cloudflared'].map((t) => v.indice(t));
    assert.ok(ordem.every((i) => i >= 0), `faltou passo: ${ordem}`);
    assert.deepEqual([...ordem].sort((a, b) => a - b), ordem, 'passos fora de ordem');
    const dumps = fs.readdirSync(path.join(v.vm, 'backups'));
    assert.equal(dumps.length, 1);
    assert.match(fs.readFileSync(path.join(v.vm, 'backups', dumps[0]), 'utf8'), /dados-do-banco/);
    // O dump tem dado de cliente: só o dono lê. No Windows o sistema de arquivos não guarda esses bits.
    if (process.platform !== 'win32') assert.equal(fs.statSync(path.join(v.vm, 'backups', dumps[0])).mode & 0o777, 0o600);
    assert.match(v.registro(), /OK/);
    assert.equal(git(v.repo, 'rev-parse', 'HEAD'), v.promovido);
  } finally {
    v.limpar();
  }
});

test('implantar com o banco parado mas com volume é instalação existente: sobe o banco e faz o backup antes de migrar', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_BANCO: '0', DUBLE_VOLUME: '1' });
    assert.equal(r.status, 0, r.stderr);
    const ordem = ['up -d --wait banco', 'pg_dump', 'run --rm migracao'].map((t) => v.indice(t));
    assert.ok(ordem.every((i) => i >= 0), `faltou passo: ${ordem}`);
    assert.deepEqual([...ordem].sort((a, b) => a - b), ordem, 'o backup tem de vir antes da migração');
    assert.equal(fs.readdirSync(path.join(v.vm, 'backups')).length, 1);
  } finally {
    v.limpar();
  }
});

test('implantar sem banco nem volume é a primeira implantação: sem backup, e segue', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_BANCO: '0', DUBLE_VOLUME: '0' });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.indice('pg_dump'), -1);
    assert.equal(fs.existsSync(path.join(v.vm, 'backups')), false);
  } finally {
    v.limpar();
  }
});

test('implantar --sem-migracao (rollback de código) não roda a migração', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido, '--sem-migracao']);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.indice('run --rm migracao'), -1);
    assert.ok(v.indice('up -d --no-deps app') > 0);
  } finally {
    v.limpar();
  }
});

test('implantar: app que não fica saudável para antes do nginx e do túnel e registra a falha', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_SAUDE: 'unhealthy' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /não ficou saudável/);
    assert.match(r.stderr, /app pode estar parado/);
    assert.equal(v.indice('cloudflared'), -1);
    assert.equal(v.indice('--force-recreate nginx'), -1);
    assert.match(v.registro(), /FALHOU/);
  } finally {
    v.limpar();
  }
});

test('implantar: falha antes de parar o app (build) não avisa de app parado nem toca o banco', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_BUILD_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /falhou no passo: build/);
    assert.doesNotMatch(r.stderr, /app pode estar parado/);
    assert.equal(v.indice('stop app'), -1);
  } finally {
    v.limpar();
  }
});

test('implantar: backup vazio é falha e a migração não roda', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(
      path.join(path.dirname(v.vm), 'docker-dubles.sh'),
      '#!/usr/bin/env bash\necho "$*" >> "$CHAMADAS"\ncase "$*" in *"ps -q banco"*) echo banco1;; esac\nexit 0\n',
      { mode: 0o755 },
    );
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /backup vazio/);
    assert.equal(v.indice('run --rm migracao'), -1);
  } finally {
    v.limpar();
  }
});

test('backup.sh grava o dump com modo 0600 e o rótulo no nome, e guarda só 14', () => {
  const v = criarVm();
  try {
    const pasta = path.join(v.vm, 'backups');
    fs.mkdirSync(pasta);
    for (let i = 0; i < 15; i++) {
      const arquivo = path.join(pasta, `phati-antigo-${String(i).padStart(2, '0')}.dump`);
      fs.writeFileSync(arquivo, 'dados');
      const data = new Date(Date.now() - (30 - i) * 86400000);
      fs.utimesSync(arquivo, data, data);
    }
    const r = v.rodar(BACKUP, []);
    assert.equal(r.status, 0, r.stderr);
    const novo = r.stdout.trim();
    assert.match(path.basename(novo), /^phati-\d{8}T\d{6}Z-cron\.dump$/);
    assert.match(fs.readFileSync(novo, 'utf8'), /dados-do-banco/);
    if (process.platform !== 'win32') assert.equal(fs.statSync(novo).mode & 0o777, 0o600);
    assert.equal(fs.readdirSync(pasta).length, 14);
    assert.ok(!fs.existsSync(path.join(pasta, 'phati-antigo-00.dump')), 'o mais velho sai');
    assert.match(v.lerChamadas().join('\n'), /exec -T banco/);
    assert.equal(v.indice('up '), -1, 'o backup não sobe nada');
  } finally {
    v.limpar();
  }
});

test('backup.sh recusa rótulo hostil e .env ausente, sem chamar o Docker', () => {
  const v = criarVm();
  try {
    for (const ruim of ['../x', 'a b', 'a;rm', 'x'.repeat(21)]) {
      const r = v.rodar(BACKUP, [ruim]);
      assert.equal(r.status, 1, ruim);
      assert.match(r.stderr, /rótulo inválido/);
    }
    fs.rmSync(path.join(v.vm, '.env'));
    const r = v.rodar(BACKUP, []);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /\.env ausente/);
    assert.equal(v.lerChamadas().length, 0);
    assert.equal(fs.existsSync(path.join(v.vm, 'backups')), false);
  } finally {
    v.limpar();
  }
});

test('backup.sh: pg_dump que falha ou sai vazio é erro e não deixa arquivo', () => {
  const v = criarVm();
  try {
    const pasta = path.join(v.vm, 'backups');
    const duble = path.join(path.dirname(v.vm), 'docker-dubles.sh');
    fs.writeFileSync(duble, '#!/usr/bin/env bash\necho "$*" >> "$CHAMADAS"\nexit 1\n', { mode: 0o755 });
    const falhou = v.rodar(BACKUP, []);
    assert.equal(falhou.status, 1);
    assert.match(falhou.stderr, /pg_dump falhou/);
    assert.deepEqual(fs.readdirSync(pasta), [], 'a falha não deixa arquivo nem parcial');
    fs.writeFileSync(duble, '#!/usr/bin/env bash\nexit 0\n', { mode: 0o755 });
    const vazio = v.rodar(BACKUP, []);
    assert.equal(vazio.status, 1);
    assert.match(vazio.stderr, /backup vazio/);
    assert.deepEqual(fs.readdirSync(pasta), []);
  } finally {
    v.limpar();
  }
});

test('backup.sh: uma falha no mesmo segundo não apaga o dump válido de mesmo nome', () => {
  const v = criarVm();
  try {
    // `date` fixo: as duas execuções caem no mesmo nome de arquivo.
    const bin = path.join(path.dirname(v.vm), 'bin-date');
    fs.mkdirSync(bin);
    fs.writeFileSync(path.join(bin, 'date'), '#!/usr/bin/env bash\necho 20260101T000000Z\n', { mode: 0o755 });
    const fixo = { PATH: `${unix(bin)}:${process.env.PATH}` };
    const bom = v.rodar(BACKUP, [], fixo);
    assert.equal(bom.status, 0, bom.stderr);
    const dump = bom.stdout.trim();
    fs.writeFileSync(path.join(path.dirname(v.vm), 'docker-dubles.sh'), '#!/usr/bin/env bash\nexit 1\n', { mode: 0o755 });
    assert.equal(v.rodar(BACKUP, [], fixo).status, 1);
    assert.match(fs.readFileSync(dump, 'utf8'), /dados-do-banco/);
  } finally {
    v.limpar();
  }
});

test('backup.sh: dump que trava passa do prazo, falha e não deixa arquivo', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(path.dirname(v.vm), 'docker-dubles.sh'), '#!/usr/bin/env bash\nsleep 30\n', { mode: 0o755 });
    const inicio = Date.now();
    const r = v.rodar(BACKUP, [], { PHATI_BACKUP_LIMITE: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /passou do prazo/);
    assert.ok(Date.now() - inicio < 15000, 'não esperou o dump travado inteiro');
    assert.deepEqual(fs.readdirSync(path.join(v.vm, 'backups')), []);
  } finally {
    v.limpar();
  }
});

test('implantar sem o backup.sh ao lado falha cedo, com instrução, sem tocar o Docker', () => {
  const v = criarVm();
  try {
    const solto = path.join(path.dirname(v.vm), 'instalado');
    fs.mkdirSync(solto);
    fs.copyFileSync(IMPLANTAR, path.join(solto, 'implantar.sh'));
    const r = v.rodar(path.join(solto, 'implantar.sh'), [v.promovido]);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /backup\.sh ausente/);
    assert.equal(v.lerChamadas().length, 0);
  } finally {
    v.limpar();
  }
});

test('restaurar exige a palavra RESTAURAR, arquivo existente e dentro de backups, e roda na ordem', () => {
  const v = criarVm();
  try {
    const pasta = path.join(v.vm, 'backups');
    fs.mkdirSync(pasta);
    const dump = path.join(pasta, 'phati-1.dump');
    fs.writeFileSync(dump, 'dados');
    assert.equal(v.rodar(RESTAURAR, [unix(dump), 'sim']).status, 1);
    assert.equal(v.rodar(RESTAURAR, [unix(path.join(pasta, 'nao-existe.dump')), 'RESTAURAR']).status, 1);
    const fora = path.join(v.vm, 'fora.dump');
    fs.writeFileSync(fora, 'dados');
    assert.equal(v.rodar(RESTAURAR, [unix(fora), 'RESTAURAR']).status, 1);
    assert.equal(v.rodar(RESTAURAR, [`${unix(pasta)}/../fora.dump`, 'RESTAURAR']).status, 1);
    assert.deepEqual(v.lerChamadas(), [], 'recusas não tocam o Docker');
    const ok = v.rodar(RESTAURAR, [unix(dump), 'RESTAURAR']);
    assert.equal(ok.status, 0, ok.stderr);
    const ordem = ['stop app', 'up -d --wait banco', 'pg_restore', 'up -d --no-deps app'].map((t) => v.indice(t));
    assert.ok(ordem.every((i) => i >= 0));
    assert.deepEqual([...ordem].sort((a, b) => a - b), ordem);
    // O dump é validado antes de apagar o schema, e a troca roda numa transação única.
    const restauracao = v.lerChamadas()[v.indice('pg_restore')];
    assert.ok(restauracao.indexOf('pg_restore') < restauracao.indexOf('DROP SCHEMA public CASCADE'));
    assert.match(restauracao, /--single-transaction/);
    assert.match(restauracao, /ON_ERROR_STOP=1/);
  } finally {
    v.limpar();
  }
});

test('trava: com outra implantação ou restauração segurando a trava, implantar e restaurar desistem sem tocar o Docker', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, '.trava.ocupado'), '');
    const curto = { PHATI_TRAVA_LIMITE: '1' };
    const implantar = v.rodar(IMPLANTAR, [v.promovido], curto);
    assert.equal(implantar.status, 1);
    assert.match(implantar.stderr, /segue rodando/);
    const pasta = path.join(v.vm, 'backups');
    fs.mkdirSync(pasta);
    fs.writeFileSync(path.join(pasta, 'phati-1.dump'), 'dados');
    const restaurar = v.rodar(RESTAURAR, [unix(path.join(pasta, 'phati-1.dump')), 'RESTAURAR'], curto);
    assert.equal(restaurar.status, 1);
    assert.match(restaurar.stderr, /segue rodando/);
    assert.deepEqual(v.lerChamadas(), []);
    assert.equal(v.lerFlock().length, 2);
  } finally {
    v.limpar();
  }
});

test('trava: o script se reexecuta sob `flock -w <limite> -E 75 <dir>/.trava`, repassa o código de saída e o trabalho roda uma vez', () => {
  const v = criarVm();
  try {
    const ok = v.rodar(IMPLANTAR, [v.promovido], { PHATI_TRAVA_LIMITE: '7' });
    assert.equal(ok.status, 0, ok.stderr);
    assert.equal(v.lerFlock().length, 1, 'só uma chamada: o filho não pede a trava de novo');
    assert.ok(v.lerFlock()[0].startsWith(`-w 7 -E 75 ${unix(v.vm)}/.trava bash `), v.lerFlock()[0]);
    assert.equal(v.lerChamadas().filter((c) => c.includes('run --rm migracao')).length, 1);
    const falha = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_SAUDE: 'unhealthy' });
    assert.equal(falha.status, 1, 'a falha do filho atravessa o flock');
    assert.match(falha.stderr, /não ficou saudável/);
  } finally {
    v.limpar();
  }
});

test('trava: sem o comando flock o script avisa e segue sem trava', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { PHATI_FLOCK: 'flock-que-nao-existe' });
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stderr, /sem flock neste sistema/);
    assert.deepEqual(v.lerFlock(), []);
  } finally {
    v.limpar();
  }
});

test('implantar guarda só os 14 backups mais recentes', () => {
  const v = criarVm();
  try {
    const pasta = path.join(v.vm, 'backups');
    fs.mkdirSync(pasta);
    const antigos = Array.from({ length: 15 }, (_, i) => path.join(pasta, `phati-antigo-${String(i).padStart(2, '0')}.dump`));
    antigos.forEach((arquivo, i) => {
      fs.writeFileSync(arquivo, 'dados');
      const data = new Date(Date.now() - (30 - i) * 86400000); // i = 0 é o mais velho
      fs.utimesSync(arquivo, data, data);
    });
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 0, r.stderr);
    const restam = fs.readdirSync(pasta);
    assert.equal(restam.length, 14);
    assert.ok(!restam.includes('phati-antigo-00.dump') && !restam.includes('phati-antigo-01.dump'), 'os dois mais velhos saem');
    assert.ok(restam.includes('phati-antigo-14.dump'), 'o mais recente dos antigos fica');
    assert.ok(restam.some((nome) => !nome.startsWith('phati-antigo')), 'o backup novo fica');
  } finally {
    v.limpar();
  }
});

test('restaurar diz a verdade sobre o estado do banco conforme o passo que falhou', () => {
  const v = criarVm();
  try {
    const pasta = path.join(v.vm, 'backups');
    fs.mkdirSync(pasta);
    const dump = unix(path.join(pasta, 'phati-1.dump'));
    fs.writeFileSync(dump, 'dados');
    const noPsql = v.rodar(RESTAURAR, [dump, 'RESTAURAR'], { DUBLE_RESTAURA_FALHA: '1' });
    assert.equal(noPsql.status, 1);
    assert.match(noPsql.stderr, /passo restaurar-dump/);
    assert.match(noPsql.stderr, /o banco ficou como estava/);
    const aoSubir = v.rodar(RESTAURAR, [dump, 'RESTAURAR'], { DUBLE_APP_FALHA: '1' });
    assert.equal(aoSubir.status, 1);
    assert.match(aoSubir.stderr, /o banco foi restaurado, mas o app não subiu/);
    // O comando de recuperação é o completo, igual ao que o script roda: projeto, .env e os dois arquivos do compose.
    assert.ok(aoSubir.stderr.includes(`COMPOSE_PROJECT_NAME=phati docker compose --env-file ${unix(v.vm)}/.env`), aoSubir.stderr);
    assert.ok(aoSubir.stderr.includes(`-f ${unix(v.vm)}/repo/servidor/compose.yaml -f ${unix(v.vm)}/repo/servidor/compose.implantacao.yaml up -d --no-deps app`), aoSubir.stderr);
    assert.doesNotMatch(aoSubir.stderr, /como estava/);
  } finally {
    v.limpar();
  }
});

test('workflow implantar: dispara à mão, só em main, com revisor, SSH com host fixado, só o SHA e o smoke ao fim', () => {
  const texto = fs.readFileSync(path.join(PASTA, '..', '.github', 'workflows', 'implantar.yml'), 'utf8').replace(/\r\n/g, '\n');
  assert.match(texto, /on:\n {2}workflow_dispatch:\n {4}inputs:\n {6}sha:/);
  assert.match(texto, /\npermissions:\n {2}contents: read\n/);
  assert.match(texto, /concurrency:\n {2}group: implantar\n {2}cancel-in-progress: false/);
  assert.match(texto, /environment: homologacao/);
  assert.match(texto, /bash scripts\/guardar-implantacao\.sh "\$REF" "\$PRIVADO" "\$SHA"/);
  assert.match(texto, /ssh -i ~\/\.ssh\/deploy -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "\$VM_USUARIO@\$VM_HOST" "\$SHA"/);
  assert.match(texto, /bash scripts\/smoke-implantacao\.sh "https:\/\/\$FQDN"/);
  assert.match(texto, /persist-credentials: false/);
  assert.doesNotMatch(texto, /StrictHostKeyChecking=no/);
  assert.doesNotMatch(texto, /run: .*\$\{\{/, 'valor de fora entra por env, nunca dentro do comando');
});

test('guarda: só main, só repositório público e só SHA que está em origin/main', () => {
  const v = criarVm();
  try {
    const guardar = (ref, privado, sha) => spawnSync('bash', [unix(GUARDAR), ref, privado, sha], { cwd: v.repo, encoding: 'utf8' });
    const ok = guardar('refs/heads/main', 'false', v.promovido);
    assert.equal(ok.status, 0, ok.stderr);
    assert.match(ok.stdout, /implantacao_guardada=/);
    assert.match(guardar('refs/heads/dev', 'false', v.promovido).stderr, /só roda em refs\/heads\/main/);
    assert.match(guardar('refs/heads/main', 'true', v.promovido).stderr, /precisa ser público/);
    assert.match(guardar('refs/heads/main', 'false', SHA_RUIM).stderr, /SHA completo/);
    assert.match(guardar('refs/heads/main', 'false', 'f'.repeat(40)).stderr, /não existe/);
    git(v.repo, 'fetch', '-q', 'origin', 'fora');
    assert.match(guardar('refs/heads/main', 'false', v.foraDeMain).stderr, /não está em origin\/main/);
    assert.match(guardar('refs/heads/main', '', v.promovido).stderr, /precisa ser público/);
  } finally {
    v.limpar();
  }
});

// Servidor de mentira para o smoke: cada rota devolve o que o teste pedir.
async function comServidor(rotas, fn) {
  const servidor = http.createServer((req, res) => {
    const rota = rotas[req.url] ?? { status: 404, corpo: '' };
    res.writeHead(rota.status, rota.cabecalhos ?? {});
    res.end(rota.corpo ?? '');
  });
  await new Promise((resolver) => servidor.listen(0, '127.0.0.1', resolver));
  try {
    return await fn(`http://127.0.0.1:${servidor.address().port}`);
  } finally {
    servidor.close();
  }
}
const ROTAS_OK = {
  '/saude': { status: 200, corpo: '{"estado": "ok"}' },
  '/entrar': { status: 200, cabecalhos: { 'Content-Security-Policy': "default-src 'self'" } },
  '/painel/': { status: 302, cabecalhos: { Location: '/painel/login/' } },
  '/api/v1/pessoas': { status: 401 },
};
const smoke = (url) => ASSINCRONO('bash', [unix(SMOKE), url]).then(
  (r) => ({ status: 0, ...r }),
  (e) => ({ status: e.code, stdout: e.stdout, stderr: e.stderr }),
);

test('smoke passa com o app saudável e reprova cada defeito sozinho', async () => {
  const ok = await comServidor(ROTAS_OK, smoke);
  assert.equal(ok.status, 0, ok.stderr);
  assert.match(ok.stdout, /smoke_ok/);
  const defeitos = {
    'saúde fora': { ...ROTAS_OK, '/saude': { status: 503, corpo: '{"estado": "indisponivel"}' } },
    'entrar sem CSP': { ...ROTAS_OK, '/entrar': { status: 200 } },
    'entrar quebrado': { ...ROTAS_OK, '/entrar': { status: 500, cabecalhos: { 'Content-Security-Policy': "default-src 'self'" } } },
    'painel aberto': { ...ROTAS_OK, '/painel/': { status: 200 } },
    'API aberta': { ...ROTAS_OK, '/api/v1/pessoas': { status: 200 } },
    'API ausente (404 não é negação)': { ...ROTAS_OK, '/api/v1/pessoas': { status: 404 } },
  };
  for (const [nome, rotas] of Object.entries(defeitos)) {
    const r = await comServidor(rotas, smoke);
    assert.equal(r.status, 1, nome);
    assert.match(r.stderr, /FALHA/, nome);
  }
});

// `curl` de mentira no PATH para o ramo https, que o servidor local (http) não alcança: responde por caminho e só
// devolve o HSTS quando FAKE_HSTS=1.
function smokeHttps(hsts, codigoDeSaida = 0) {
  const pasta = fs.mkdtempSync(path.join(os.tmpdir(), 'curl-falso-'));
  fs.writeFileSync(
    path.join(pasta, 'curl'),
    [
      '#!/usr/bin/env bash',
      'url="${*: -1}"',
      'if [[ " $* " == *" -D "* ]]; then',
      '  printf "HTTP/2 200\\r\\ncontent-security-policy: default-src self\\r\\n"',
      '  [[ "${FAKE_HSTS:-0}" == 1 ]] && printf "strict-transport-security: max-age=1\\r\\n"',
      '  exit "${FAKE_CURL_FALHA:-0}"',
      'fi',
      'if [[ " $* " == *" -w "* ]]; then',
      '  case "$url" in */painel/) printf 302 ;; */api/v1/pessoas) printf 401 ;; *) printf 200 ;; esac',
      '  exit 0',
      'fi',
      'echo \'{"estado": "ok"}\'',
      '',
    ].join('\n'),
    { mode: 0o755 },
  );
  const r = spawnSync('bash', [unix(SMOKE), 'https://phati.exemplo.test'], {
    env: { ...process.env, PATH: `${pasta}${path.delimiter}${process.env.PATH}`, FAKE_HSTS: hsts ? '1' : '0', FAKE_CURL_FALHA: String(codigoDeSaida) },
    encoding: 'utf8',
  });
  fs.rmSync(pasta, { recursive: true, force: true });
  return r;
}

test('smoke em https exige o HSTS: com o cabeçalho passa, sem ele reprova só essa verificação', () => {
  const com = smokeHttps(true);
  assert.equal(com.status, 0, com.stderr);
  assert.match(com.stdout, /HSTS presente/);
  const sem = smokeHttps(false);
  assert.equal(sem.status, 1);
  assert.match(sem.stderr, /FALHA HSTS presente/);
  assert.doesNotMatch(sem.stderr, /FALHA \/saude|FALHA API/);
});

test('smoke: curl que falha depois de emitir cabeçalhos não vale como "achei o cabeçalho"', () => {
  const r = smokeHttps(true, 56);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /FALHA \/entrar leva Content-Security-Policy/);
  assert.match(r.stderr, /FALHA HSTS presente/);
});

test('smoke recusa URL com caminho, sem esquema e HTTP puro fora do computador local', async () => {
  for (const ruim of ['', 'host.exemplo', 'https://host/caminho', 'http://phati.exemplo.test', 'http://127.0.0.1.exemplo.test']) {
    const r = await smoke(ruim);
    assert.equal(r.status, 1, ruim);
    assert.match(r.stderr, /URL base/);
  }
});
