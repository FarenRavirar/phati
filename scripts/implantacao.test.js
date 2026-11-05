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
const { execFile, execFileSync, spawnSync } = require('node:child_process');
const { promisify } = require('node:util');

const ASSINCRONO = promisify(execFile);
const PASTA = __dirname;
const IMPLANTAR = path.join(PASTA, 'implantar.sh');
const RESTAURAR = path.join(PASTA, 'restaurar.sh');
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
      '  *"ps -q banco"*) [[ "${DUBLE_BANCO:-1}" == 1 ]] && echo banco1 ;;',
      '  *"ps -q app"*) echo app1 ;;',
      '  *"exec -T banco"*pg_dump*) echo "dados-do-banco" ;;',
      '  inspect*) echo "${DUBLE_SAUDE:-healthy}" ;;',
      'esac',
      'exit 0',
      '',
    ].join('\n'),
    { mode: 0o755 },
  );
  const ambiente = {
    ...process.env,
    PHATI_DIR: unix(vm),
    DOCKER: unix(dublê),
    CHAMADAS: unix(chamadas),
    PHATI_ESPERA: '0',
    PHATI_TENTATIVAS: '2',
  };
  const rodar = (script, argumentos, extra = {}) =>
    spawnSync('bash', [unix(script), ...argumentos], { env: { ...ambiente, ...extra }, encoding: 'utf8' });
  const lerChamadas = () => (fs.existsSync(chamadas) ? fs.readFileSync(chamadas, 'utf8').split('\n').filter(Boolean) : []);
  const indice = (trecho) => lerChamadas().findIndex((linha) => linha.includes(trecho));
  const registro = () => {
    const arquivo = path.join(vm, 'implantacoes.log');
    return fs.existsSync(arquivo) ? fs.readFileSync(arquivo, 'utf8') : '';
  };
  const limpar = () => fs.rmSync(raiz, { recursive: true, force: true });
  return { vm, repo, promovido, foraDeMain, rodar, lerChamadas, indice, registro, limpar };
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
    const ordem = ['pg_dump', ' build', 'stop app', 'up -d --wait banco', 'run --rm migracao', 'run --rm --no-deps estaticos', 'up -d --no-deps app', 'up -d --no-deps nginx cloudflared'].map((t) => v.indice(t));
    assert.ok(ordem.every((i) => i >= 0), `faltou passo: ${ordem}`);
    assert.deepEqual([...ordem].sort((a, b) => a - b), ordem, 'passos fora de ordem');
    const dumps = fs.readdirSync(path.join(v.vm, 'backups'));
    assert.equal(dumps.length, 1);
    assert.match(fs.readFileSync(path.join(v.vm, 'backups', dumps[0]), 'utf8'), /dados-do-banco/);
    assert.match(v.registro(), /OK/);
    assert.equal(git(v.repo, 'rev-parse', 'HEAD'), v.promovido);
  } finally {
    v.limpar();
  }
});

test('implantar sem banco no ar é a primeira implantação: sem backup, e segue', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_BANCO: '0' });
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
    assert.equal(v.indice('nginx cloudflared'), -1);
    assert.match(v.registro(), /FALHOU/);
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
  } finally {
    v.limpar();
  }
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
  };
  for (const [nome, rotas] of Object.entries(defeitos)) {
    const r = await comServidor(rotas, smoke);
    assert.equal(r.status, 1, nome);
    assert.match(r.stderr, /FALHA/, nome);
  }
});

test('smoke recusa URL com caminho ou sem esquema', async () => {
  for (const ruim of ['', 'host.exemplo', 'https://host/caminho']) {
    const r = await smoke(ruim);
    assert.equal(r.status, 1, ruim);
    assert.match(r.stderr, /URL base/);
  }
});
