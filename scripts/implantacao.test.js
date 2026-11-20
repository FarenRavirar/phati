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
  // O valor marcador é o "segredo" que nunca pode aparecer no log nem no stdout (spec 009, A7).
  if (comEnv) fs.writeFileSync(path.join(vm, '.env'), 'PHATI_X=1\nPHATI_HOSTS_PERMITIDOS=phati.exemplo.test,outro.exemplo.test\nPHATI_SEGREDO_MARCADOR=valor-secreto-9f3a\n');
  const chamadas = path.join(raiz, 'chamadas.log');
  // Nome do projeto Compose que cada chamada ao Docker viu (`COMPOSE_PROJECT_NAME` do script): prova o PHATI_PROJETO (X4a).
  const projetos = path.join(raiz, 'projetos.log');
  const visto = path.join(raiz, 'alvo-visto.log');
  const dublê = path.join(raiz, 'docker-dubles.sh');
  fs.writeFileSync(
    dublê,
    [
      '#!/usr/bin/env bash',
      'echo "$*" >> "$CHAMADAS"',
      'echo "${COMPOSE_PROJECT_NAME:-sem-projeto}" >> "$PROJETOS"',
      'case "$*" in',
      '  *"comum.compat_migracao"*) printf "[%s]\\n" "$@" > "$ARGV"; [[ -n "${DUBLE_COMPAT_SAIDA:-}" ]] && printf "%s\\n" "$DUBLE_COMPAT_SAIDA"; exit "${DUBLE_COMPAT_RC:-0}" ;;',
      '  *" build"*) [[ "${DUBLE_BUILD_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"up -d --no-deps app_"*) [[ "${DUBLE_APP_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"config --services"*) [[ "${DUBLE_CONFIG_FALHA:-0}" == 1 ]] && exit 1; echo banco; [[ "${DUBLE_SEM_EXTENSOES:-0}" == 1 ]] || echo banco_extensoes ;;',
      '  *"run --rm banco_extensoes"*) [[ "${DUBLE_EXTENSOES_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"run --rm --no-deps camadas_dono"*) [[ "${DUBLE_CAMADAS_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"run --rm --no-deps pacotes_dono"*) [[ "${DUBLE_PACOTES_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"exec -T banco"*pg_restore*) [[ "${DUBLE_RESTAURA_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"ps -q banco"*) [[ "${DUBLE_BANCO:-1}" == 1 ]] && echo banco1 ;;',
      '  *"run --rm migracao"*) [[ "${DUBLE_MIGRACAO_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"run --rm --no-deps estaticos_"*) [[ "${DUBLE_ESTATICOS_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"ps -q app_azul"*) echo app_azul1 ;;',
      '  *"ps -q app_verde"*) echo app_verde1 ;;',
      '  *"ps -q pgb1"*) [[ "${DUBLE_PGB:-0}" == 1 || -e "$PGB_MARCA" ]] && echo pgb11 ;;',
      '  *"ps -q pgb2"*) [[ "${DUBLE_PGB:-0}" == 1 || -e "$PGB_MARCA" ]] && echo pgb21 ;;',
      '  *"ps -q pgb_ns"*) [[ "${DUBLE_PGB:-0}" == 1 || -e "$PGB_MARCA" ]] && echo pgbns1 ;;',
      '  *"up -d --no-deps pgb_ns"*) touch "$PGB_MARCA" ;;',
      '  *"ps -aq --filter"*) [[ "${DUBLE_ORFAO:-0}" == 1 ]] && echo orfao1 ;;',
      '  *"ps -q nginx"*) [[ "${DUBLE_NGINX:-1}" == 1 ]] && echo nginx1 ;;',
      '  *"nginx -t"*) cat "$ALVO_DIR/alvo.conf" >> "$VISTO" 2>/dev/null; echo "--" >> "$VISTO"; [[ "${DUBLE_NGINX_TESTE_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"nginx -s reload"*) [[ "${DUBLE_RELOAD_FALHA:-0}" == 1 ]] && exit 1; [[ "${DUBLE_RELOAD_2_FALHA:-0}" == 1 && "$(grep -c "nginx -s reload" "$CHAMADAS")" -ge 2 ]] && exit 1 ;;',
      '  *"exec -T nginx wget"*) [[ "${DUBLE_SAUDA_NGINX_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"exec -T banco"*pg_dump*) echo "dados-do-banco" ;;',
      '  *inspect*app_azul*) echo "${DUBLE_SAUDE_AZUL:-${DUBLE_SAUDE:-healthy}}" ;;',
      '  *inspect*app_verde*) echo "${DUBLE_SAUDE_VERDE:-${DUBLE_SAUDE:-healthy}}" ;;',
      '  *inspect*pgb*) echo "${DUBLE_SAUDE_PGB:-healthy}" ;;',
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
    PHATI_ALVO_DIR: unix(path.join(vm, 'alvo')),
    ALVO_DIR: unix(path.join(vm, 'alvo')),
    VISTO: unix(visto),
    PGB_MARCA: unix(path.join(raiz, 'pgb-no-ar')),
    ARGV: unix(path.join(vm, 'compat-argv.log')),
    PROJETOS: unix(projetos),
    // Vazio = padrão `phati`, mesmo que o ambiente de quem roda tenha PHATI_PROJETO.
    PHATI_PROJETO: '',
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
  // Promove um commit novo a main (vira candidato a implantação) e devolve o SHA.
  const promover = () => {
    git(trabalho, 'switch', '-q', 'main');
    contadorPromocao += 1;
    fs.writeFileSync(path.join(trabalho, 'servidor', `promocao-${contadorPromocao}`), 'x\n');
    git(trabalho, 'add', '.');
    git(trabalho, 'commit', '-q', '-m', `promocao ${contadorPromocao}`);
    git(trabalho, 'push', '-q', 'origin', 'main');
    return git(trabalho, 'rev-parse', 'HEAD');
  };
  const zerar = () => fs.rmSync(chamadas, { force: true });
  const lerAlvo = () => fs.readFileSync(path.join(vm, 'alvo', 'alvo.conf'), 'utf8');
  const lerArquivo = (nome) => fs.readFileSync(path.join(vm, nome), 'utf8');
  const contarChamadas = (trecho) => lerChamadas().filter((linha) => linha.includes(trecho)).length;
  const lerProjetos = () => (fs.existsSync(projetos) ? fs.readFileSync(projetos, 'utf8').split('\n').filter(Boolean) : []);
  return { vm, repo, promovido, foraDeMain, rodar, lerChamadas, lerProjetos, lerFlock, indice, registro, limpar, promover, zerar, lerAlvo, lerArquivo, contarChamadas, visto, alvo: path.join(vm, 'alvo'), trabalho, lerArgv: () => fs.readFileSync(path.join(vm, 'compat-argv.log'), 'utf8') };
}
let contadorPromocao = 0;

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

test('implantar (instalação existente, sem ativa): backup, build, pgbouncer, migrar, estáticos, app, troca e túnel, nessa ordem', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 0, r.stderr);
    const ordem = ['pg_dump', ' build', 'up -d --no-deps pgb_ns pgb1 pgb2', 'run --rm migracao', 'run --rm --no-deps estaticos_azul', 'up -d --no-deps app_azul', 'run --rm --no-deps nginx nginx -t', 'exec -T nginx wget', 'up -d --no-deps nginx cloudflared'].map((t) => v.indice(t));
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

test('implantar aplica o PostGIS antes de parar o app (volume que já existia não ganha a extensão no init)', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 0, r.stderr);
    const ordem = [' build', 'run --rm banco_extensoes', 'run --rm --no-deps pgb_auth', 'run --rm migracao'].map((t) => v.indice(t));
    assert.ok(ordem.every((i) => i >= 0), `faltou passo: ${ordem}`);
    assert.deepEqual([...ordem].sort((a, b) => a - b), ordem, 'o PostGIS tem de vir antes da migração');
  } finally {
    v.limpar();
  }
});

test('implantar falha fechada se o PostGIS não puder ser aplicado: o app não para e o registro diz FALHOU', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_EXTENSOES_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /falhou no passo: extensoes/);
    assert.equal(v.indice('stop app'), -1, 'o app não pode parar antes de a extensão estar aplicada');
    assert.equal(v.indice('run --rm migracao'), -1);
    assert.match(v.registro(), /FALHOU: falhou no passo: extensoes/);
  } finally {
    v.limpar();
  }
});

test('implantar roda o dono do volume das camadas antes de subir o app (o `up --no-deps` não dispara depends_on)', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 0, r.stderr);
    const ordem = ['run --rm --no-deps estaticos', 'run --rm --no-deps camadas_dono', 'up -d --no-deps app'].map((t) => v.indice(t));
    assert.ok(ordem.every((i) => i >= 0), `faltou passo: ${ordem}`);
    assert.deepEqual([...ordem].sort((a, b) => a - b), ordem, 'o chown das camadas tem de vir antes de subir o app');
  } finally {
    v.limpar();
  }
});

test('implantar roda o dono do volume dos pacotes antes de subir o app (o `up --no-deps` não dispara depends_on)', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 0, r.stderr);
    const ordem = ['run --rm --no-deps estaticos', 'run --rm --no-deps pacotes_dono', 'up -d --no-deps app'].map((t) => v.indice(t));
    assert.ok(ordem.every((i) => i >= 0), `faltou passo: ${ordem}`);
    assert.deepEqual([...ordem].sort((a, b) => a - b), ordem, 'o chown dos pacotes tem de vir antes de subir o app');
  } finally {
    v.limpar();
  }
});

test('implantar falha fechada se o dono do volume dos pacotes falhar: o app não sobe e o registro diz FALHOU', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_PACOTES_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /falhou no passo: pacotes-dono/);
    assert.equal(v.indice('up -d --no-deps app'), -1, 'o app não pode subir sem o volume dos pacotes acertado');
    assert.match(v.registro(), /FALHOU: falhou no passo: pacotes-dono/);
  } finally {
    v.limpar();
  }
});

test('implantar falha fechada se o dono do volume das camadas falhar: o app não sobe e o registro diz FALHOU', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_CAMADAS_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /falhou no passo: camadas-dono/);
    assert.equal(v.indice('up -d --no-deps app'), -1, 'o app não pode subir sem o volume das camadas acertado');
    assert.match(v.registro(), /FALHOU: falhou no passo: camadas-dono/);
  } finally {
    v.limpar();
  }
});

test('implantar com Compose sem banco_extensoes (commit antigo) pula o PostGIS, registra e segue a recuperação', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_SEM_EXTENSOES: '1' });
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /pulado: compose sem banco_extensoes/);
    assert.match(v.registro(), /pulado: compose sem banco_extensoes/);
    assert.equal(v.indice('run --rm banco_extensoes'), -1);
    assert.ok(v.indice('up -d --no-deps app_azul') > 0, 'o app sobe mesmo sem o PostGIS no Compose');
    assert.match(r.stdout, /implantado=/);
  } finally {
    v.limpar();
  }
});

test('implantar falha fechada se não der para listar os serviços do Compose: o app não para e o registro diz FALHOU', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_CONFIG_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /falhou no passo: extensoes/);
    assert.equal(v.indice('stop app'), -1, 'sem a lista de serviços não se sabe se o PostGIS existe: o app não para');
    assert.match(v.registro(), /FALHOU: falhou no passo: extensoes/);
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
    assert.match(r.stderr, /a candidata app_azul não ficou saudável/);
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

test('PHATI_PROJETO=outro leva o nome do projeto Compose a implantar e ao volume do banco; sem ele o padrão é phati', () => {
  const v = criarVm();
  try {
    // Sem `ativa` é a primeira implantação: a faxina de órfãos filtra pelo projeto. Banco sem contêiner, volume existe.
    const ok = v.rodar(IMPLANTAR, [v.promovido], { PHATI_PROJETO: 'outro', DUBLE_BANCO: '0', DUBLE_VOLUME: '1' });
    assert.equal(ok.status, 0, ok.stderr);
    assert.ok(v.lerProjetos().length > 0);
    assert.ok(v.lerProjetos().every((p) => p === 'outro'), v.lerProjetos().join(','));
    assert.ok(v.lerChamadas().some((l) => l.includes('volume inspect outro_dados_banco')));
    assert.ok(v.lerChamadas().some((l) => l.includes('label=com.docker.compose.project=outro')));
    assert.ok(!v.lerChamadas().some((l) => l.includes('phati_dados_banco') || l.includes('project=phati')));
    const padrao = criarVm();
    try {
      const r = padrao.rodar(IMPLANTAR, [padrao.promovido], { PHATI_PROJETO: '' });
      assert.equal(r.status, 0, r.stderr);
      assert.ok(padrao.lerProjetos().length > 0 && padrao.lerProjetos().every((p) => p === 'phati'));
    } finally {
      padrao.limpar();
    }
  } finally {
    v.limpar();
  }
});

test('PHATI_PROJETO inválido para implantar, backup e restaurar antes de qualquer chamada ao Docker', () => {
  const v = criarVm();
  try {
    const pasta = path.join(v.vm, 'backups');
    fs.mkdirSync(pasta);
    const dump = path.join(pasta, 'phati-1.dump');
    fs.writeFileSync(dump, 'dados');
    for (const ruim of ['Outro', 'a b', 'a;touch x', '-x', 'a/b']) {
      const i = v.rodar(IMPLANTAR, [v.promovido], { PHATI_PROJETO: ruim });
      assert.equal(i.status, 1, ruim);
      assert.match(i.stderr, /PHATI_PROJETO inválido/, ruim);
      const b = v.rodar(BACKUP, [], { PHATI_PROJETO: ruim });
      assert.equal(b.status, 1, ruim);
      assert.match(b.stderr, /PHATI_PROJETO inválido/, ruim);
      const r = v.rodar(RESTAURAR, [unix(dump), 'RESTAURAR'], { PHATI_PROJETO: ruim });
      assert.equal(r.status, 1, ruim);
      assert.match(r.stderr, /PHATI_PROJETO inválido/, ruim);
    }
    assert.deepEqual(v.lerChamadas(), [], 'valor inválido não chega ao Docker');
  } finally {
    v.limpar();
  }
});

test('restaurar com PHATI_PROJETO=outro usa o projeto outro, inclusive na instrução de recuperação', () => {
  const v = criarVm();
  try {
    const pasta = path.join(v.vm, 'backups');
    fs.mkdirSync(pasta);
    const dump = path.join(pasta, 'phati-1.dump');
    fs.writeFileSync(dump, 'dados');
    const ok = v.rodar(RESTAURAR, [unix(dump), 'RESTAURAR'], { PHATI_PROJETO: 'outro' });
    assert.equal(ok.status, 0, ok.stderr);
    assert.ok(v.lerProjetos().length > 0 && v.lerProjetos().every((p) => p === 'outro'));
    const falha = v.rodar(RESTAURAR, [unix(dump), 'RESTAURAR'], { PHATI_PROJETO: 'outro', DUBLE_APP_FALHA: '1' });
    assert.equal(falha.status, 1);
    assert.match(falha.stderr, /COMPOSE_PROJECT_NAME=outro docker compose/);
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

test('backup.sh usa o rótulo pedido no nome do dump', () => {
  const v = criarVm();
  try {
    const r = v.rodar(BACKUP, ['ab-1_x']);
    assert.equal(r.status, 0, r.stderr);
    assert.match(path.basename(r.stdout.trim()), /^phati-\d{8}T\d{6}Z-ab-1_x\.dump$/);
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

test('backup.sh: dump que trava e ignora o TERM passa do prazo, é morto, falha e não deixa arquivo', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(path.dirname(v.vm), 'docker-dubles.sh'), '#!/usr/bin/env bash\ntrap "" TERM\nexec sleep 30\n', { mode: 0o755 }); // ignora o TERM: só o KILL do `timeout -k` o encerra
    const inicio = Date.now();
    const r = v.rodar(BACKUP, [], { PHATI_BACKUP_LIMITE: '1', PHATI_BACKUP_ABATE: '1' });
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

// Spec 009 (Blue-Green): duas pilhas, troca do destino do nginx, rollback instantâneo e falha injetada em cada passo.
const ALVO_AZUL = 'set $alvo app_azul;\nset $pilha azul;\n';
const ALVO_VERDE = 'set $alvo app_verde;\nset $pilha verde;\n';

test('primeira implantação (sem ativa) sobe azul, troca o nginx pelo contêiner novo e grava o estado', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /implantado=[0-9a-f]{12} ativa=azul anterior=nenhuma/);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.lerArquivo('pilha-azul.sha').trim(), v.promovido);
    assert.equal(v.indice('stop '), -1, 'nenhuma pilha é parada');
    const ordem = [' build', 'up -d --no-deps pgb_ns pgb1 pgb2', 'run --rm migracao', 'run --rm --no-deps estaticos_azul', 'up -d --no-deps app_azul', 'run --rm --no-deps nginx nginx -t', 'exec -T nginx wget', 'up -d --no-deps nginx cloudflared'].map((t) => v.indice(t));
    assert.ok(ordem.every((i) => i >= 0), `faltou passo: ${ordem}`);
    assert.deepEqual([...ordem].sort((a, b) => a - b), ordem, 'passos fora de ordem');
    assert.match(v.registro(), / OK origem=nenhuma destino=azul migracao=nenhuma\n/);
  } finally {
    v.limpar();
  }
});

test('segunda implantação sobe verde ao lado da azul, troca o destino e deixa a azul de pé', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = v.promover();
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b]);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /ativa=verde anterior=azul/);
    assert.equal(v.lerArquivo('ativa').trim(), 'verde');
    assert.equal(v.lerAlvo(), ALVO_VERDE);
    assert.equal(v.lerArquivo('pilha-verde.sha').trim(), b);
    assert.equal(v.lerArquivo('pilha-azul.sha').trim(), v.promovido, 'a azul segue com o SHA dela');
    assert.equal(v.indice('stop '), -1, 'a azul não para');
    assert.equal(v.contarChamadas('up -d --no-deps app_azul'), 0, 'a azul não é recriada');
    const ordem = [' build', 'run --rm --no-deps estaticos_verde', 'up -d --no-deps app_verde', 'exec -T nginx nginx -t', 'exec -T nginx nginx -s reload', 'exec -T nginx wget', 'up -d --no-deps nginx cloudflared'].map((t) => v.indice(t));
    assert.ok(ordem.every((i) => i >= 0), `faltou passo: ${ordem}`);
    assert.deepEqual([...ordem].sort((a, b) => a - b), ordem, 'passos fora de ordem');
    assert.match(v.registro(), / OK origem=azul destino=verde migracao=nenhuma\n/);
  } finally {
    v.limpar();
  }
});

test('terceira implantação volta ao azul: a candidata é sempre a pilha que não está ativa', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    assert.equal(v.rodar(IMPLANTAR, [v.promover()]).status, 0);
    const c = v.promover();
    v.zerar();
    const r = v.rodar(IMPLANTAR, [c]);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /ativa=azul anterior=verde/);
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.lerArquivo('pilha-azul.sha').trim(), c);
    assert.ok(v.indice('up -d --no-deps app_azul') >= 0, 'a azul é a candidata, então sobe');
  } finally {
    v.limpar();
  }
});

test('rollback rápido: o SHA da pilha inativa e saudável só troca o destino, sem build, migração nem backup', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = v.promover();
    assert.equal(v.rodar(IMPLANTAR, [b]).status, 0);
    v.zerar();
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /implantado=[0-9a-f]{12} ativa=azul anterior=verde/);
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    for (const proibido of [' build', 'run --rm migracao', 'pg_dump', 'up -d --no-deps app_', 'run --rm --no-deps estaticos_']) {
      assert.equal(v.indice(proibido), -1, `o rollback rápido não chama: ${proibido}`);
    }
    assert.ok(v.indice('exec -T nginx nginx -s reload') >= 0, 'o rollback recarrega o nginx');
    assert.match(v.registro(), / OK origem=verde destino=azul migracao=pulada\n/);
  } finally {
    v.limpar();
  }
});

test('rollback com a pilha inativa não saudável não pula o build: vira implantação normal e a candidata é conferida', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = v.promover();
    assert.equal(v.rodar(IMPLANTAR, [b]).status, 0);
    v.zerar();
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_SAUDE_AZUL: 'unhealthy' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /a candidata app_azul não ficou saudável/);
    assert.match(r.stderr, /a pilha ativa \(verde\) segue servindo/);
    assert.ok(v.indice(' build') >= 0, 'sem a pilha saudável, o SHA é reconstruído');
    assert.equal(v.lerAlvo(), ALVO_VERDE, 'o destino não mudou');
    assert.equal(v.lerArquivo('ativa').trim(), 'verde');
  } finally {
    v.limpar();
  }
});

test('candidata não fica healthy: a ativa segue, alvo.conf intacto e o erro diz que a ativa segue', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = v.promover();
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_SAUDE_VERDE: 'unhealthy' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /a candidata app_verde não ficou saudável/);
    assert.match(r.stderr, /a pilha ativa \(azul\) segue servindo/);
    assert.equal(v.lerAlvo(), ALVO_AZUL, 'alvo.conf intacto');
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.equal(fs.existsSync(path.join(v.vm, 'pilha-verde.sha')), false, 'a candidata não virou pilha servindo');
    assert.equal(v.contarChamadas('exec -T nginx nginx -t'), 0, 'o nginx nem foi mexido');
    assert.match(v.registro(), /FALHOU: a candidata app_verde não ficou saudável/);
  } finally {
    v.limpar();
  }
});

test('candidata que não fica saudável na primeira implantação não chega ao nginx', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_SAUDE: 'unhealthy' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /a candidata app_azul não ficou saudável/);
    assert.doesNotMatch(r.stderr, /segue servindo/, 'não havia pilha ativa');
    assert.equal(fs.existsSync(path.join(v.alvo, 'alvo.conf')), false);
    assert.equal(v.contarChamadas('nginx'), 0);
    assert.match(v.registro(), /FALHOU/);
  } finally {
    v.limpar();
  }
});

test('nginx -t falha: nenhum reload, alvo.conf anterior restaurado e a ativa segue', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = v.promover();
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_NGINX_TESTE_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /nginx -t ou reload falhou/);
    assert.match(r.stderr, /segue servindo/);
    assert.equal(v.contarChamadas('nginx -s reload'), 0, 'nenhum reload');
    assert.equal(v.lerAlvo(), ALVO_AZUL, 'alvo.conf restaurado');
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
  } finally {
    v.limpar();
  }
});

test('verificação pelo nginx falha depois do reload: reverte alvo.conf, recarrega de novo e registra a falha', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = v.promover();
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_SAUDA_NGINX_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /\/saude pelo nginx falhou depois do reload/);
    assert.match(r.stderr, /alvo.conf revertido para app_azul, que segue servindo/);
    assert.equal(v.contarChamadas('nginx -s reload'), 2, 'recarrega o destino novo e depois o anterior');
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.match(v.registro(), /FALHOU: \/saude pelo nginx falhou depois do reload; .* origem=azul destino=verde/);
  } finally {
    v.limpar();
  }
});

test('falha ao reverter: a mensagem traz o comando de recuperação completo', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = v.promover();
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_SAUDA_NGINX_FALHA: '1', DUBLE_RELOAD_2_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /alvo.conf revertido, mas o nginx não recarregou; recupere com:/);
    const recuperacao = `printf 'set $alvo app_azul;\\nset $pilha azul;\\n' > ${unix(v.alvo)}/alvo.conf && COMPOSE_PROJECT_NAME=phati docker compose --env-file ${unix(v.vm)}/.env -f ${unix(v.vm)}/repo/servidor/compose.yaml -f ${unix(v.vm)}/repo/servidor/compose.implantacao.yaml exec -T nginx nginx -s reload`;
    assert.ok(r.stderr.includes(recuperacao), r.stderr);
  } finally {
    v.limpar();
  }
});

test('falhas antes da troca não tocam o nginx: build, migração e estáticos deixam a ativa servindo', () => {
  const casos = [
    [{ DUBLE_BUILD_FALHA: '1' }, 'falhou no passo: build'],
    [{ DUBLE_MIGRACAO_FALHA: '1' }, 'falhou no passo: migracao'],
    [{ DUBLE_ESTATICOS_FALHA: '1' }, 'falhou no passo: estaticos'],
  ];
  for (const [extra, esperado] of casos) {
    const v = criarVm();
    try {
      assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
      const b = v.promover();
      v.zerar();
      const r = v.rodar(IMPLANTAR, [b], extra);
      assert.equal(r.status, 1, esperado);
      assert.match(r.stderr, new RegExp(esperado), esperado);
      assert.match(r.stderr, /a pilha ativa \(azul\) segue servindo/, esperado);
      assert.equal(v.contarChamadas('up -d --no-deps app_verde'), 0, `${esperado}: a candidata não sobe`);
      assert.equal(v.contarChamadas('exec -T nginx'), 0, `${esperado}: o nginx não é tocado`);
      assert.equal(v.lerAlvo(), ALVO_AZUL, esperado);
      assert.equal(v.lerArquivo('ativa').trim(), 'azul', esperado);
      assert.match(v.registro(), new RegExp(`FALHOU: ${esperado}`), esperado);
    } finally {
      v.limpar();
    }
  }
});

test('PostGIS, pacotes e camadas que falham na primeira implantação: nada chega ao nginx', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_CAMADAS_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /falhou no passo: camadas-dono/);
    assert.equal(fs.existsSync(path.join(v.alvo, 'alvo.conf')), false);
    assert.equal(v.contarChamadas('nginx'), 0);
  } finally {
    v.limpar();
  }
});

test('--sem-migracao com volume existente: sem backup, sem migração, e o app da candidata sobe', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido, '--sem-migracao']);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.indice('pg_dump'), -1);
    assert.equal(v.indice('run --rm migracao'), -1);
    assert.ok(v.indice('up -d --no-deps app_azul') > 0);
  } finally {
    v.limpar();
  }
});

test('alvo.conf: o nginx sempre vê o arquivo inteiro e nenhum temporário sobra no diretório', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    assert.equal(v.rodar(IMPLANTAR, [v.promover()]).status, 0);
    // Cada `nginx -t` do dublê grava o alvo.conf que o nginx leria naquele instante, separado por `--`.
    const blocos = fs.readFileSync(v.visto, 'utf8').split('--\n').slice(0, -1);
    assert.ok(blocos.length >= 2, `poucas leituras: ${blocos.length}`);
    for (const bloco of blocos) assert.match(bloco, /^set \$alvo app_(azul|verde);\nset \$pilha (azul|verde);\n$/, bloco);
    assert.deepEqual(fs.readdirSync(v.alvo), ['alvo.conf'], 'sem temporário sobrando');
  } finally {
    v.limpar();
  }
});

test('implantacoes.log tem origem e destino no fim da linha, sem segredo no log, no stdout ou na chamada', () => {
  const v = criarVm();
  try {
    const a = v.rodar(IMPLANTAR, [v.promovido]);
    const b = v.rodar(IMPLANTAR, [v.promover()]);
    assert.equal(a.status, 0, a.stderr);
    assert.equal(b.status, 0, b.stderr);
    const log = v.registro();
    assert.match(log, / inicio anterior=/);
    assert.match(log, / OK origem=nenhuma destino=azul migracao=nenhuma\n/);
    assert.match(log, / OK origem=azul destino=verde migracao=nenhuma\n/);
    for (const texto of [log, a.stdout, a.stderr, b.stdout, b.stderr, v.lerChamadas().join('\n')]) {
      assert.ok(!texto.includes('valor-secreto-9f3a'), 'segredo vazou');
    }
    assert.ok(v.lerChamadas().some((linha) => linha.includes('Host: phati.exemplo.test')), 'o Host vem do primeiro de PHATI_HOSTS_PERMITIDOS');
  } finally {
    v.limpar();
  }
});

test('PHATI_HOSTS_PERMITIDOS: hostil recusa cedo sem tocar o Docker; ausente usa localhost', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, '.env'), 'PHATI_HOSTS_PERMITIDOS=ruim;rm -rf /\n');
    const hostil = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(hostil.status, 1);
    assert.match(hostil.stderr, /primeiro host de PHATI_HOSTS_PERMITIDOS inválido/);
    assert.deepEqual(v.lerChamadas(), []);
    fs.writeFileSync(path.join(v.vm, '.env'), 'PHATI_X=1\n');
    const ausente = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(ausente.status, 0, ausente.stderr);
    assert.ok(v.lerChamadas().some((linha) => linha.includes('Host: localhost')), 'sem a variável, usa localhost');
  } finally {
    v.limpar();
  }
});

test('restaurar sobe e para só a pilha ativa, lida de `ativa`', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'ativa'), 'verde\n');
    const pasta = path.join(v.vm, 'backups');
    fs.mkdirSync(pasta);
    const dump = unix(path.join(pasta, 'phati-1.dump'));
    fs.writeFileSync(dump, 'dados');
    const r = v.rodar(RESTAURAR, [dump, 'RESTAURAR']);
    assert.equal(r.status, 0, r.stderr);
    assert.ok(v.indice('stop app_verde') >= 0, 'para a verde');
    assert.equal(v.indice('stop app_azul'), -1, 'não mexe na azul');
    assert.ok(v.indice('up -d --no-deps app_verde') > v.indice('pg_restore'), 'sobe a verde depois do banco');
  } finally {
    v.limpar();
  }
});

test('restaurar recusa `ativa` com valor fora de azul e verde, sem tocar o Docker', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'ativa'), 'roxo\n');
    const pasta = path.join(v.vm, 'backups');
    fs.mkdirSync(pasta);
    const dump = unix(path.join(pasta, 'phati-1.dump'));
    fs.writeFileSync(dump, 'dados');
    const r = v.rodar(RESTAURAR, [dump, 'RESTAURAR']);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /tem valor inválido/);
    assert.deepEqual(v.lerChamadas(), []);
  } finally {
    v.limpar();
  }
});

test('PgBouncer já de pé: não sobe nem recria pgb_ns/pgb1/pgb2 (recriar o pgb_ns derrubaria o banco da ativa)', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_PGB: '1' });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contarChamadas('up -d --no-deps pgb_'), 0, 'nenhum up de pgb*');
    assert.equal(v.contarChamadas('run --rm --no-deps pgb_auth'), 0, 'o auth também não roda');
    assert.match(r.stdout, /implantado=/);
  } finally {
    v.limpar();
  }
});

test('PgBouncer parado: sobe com o auth antes e espera pgb1 e pgb2 saudáveis', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 0, r.stderr);
    assert.ok(v.indice('run --rm --no-deps pgb_auth') < v.indice('up -d --no-deps pgb_ns pgb1 pgb2'));
    assert.equal(v.contarChamadas('up -d --no-deps pgb_ns pgb1 pgb2'), 1);
  } finally {
    v.limpar();
  }
});

test('primeira implantação sobre o app da 006: remove o órfão só depois da troca, registra e não toca volumes', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_ORFAO: '1' });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contarChamadas('rm -f orfao1'), 1, 'o órfão sai uma vez');
    assert.ok(v.indice('rm -f orfao1') > v.indice('exec -T nginx wget'), 'só depois da verificação pelo nginx');
    assert.ok(v.indice('rm -f orfao1') > v.indice('up -d --no-deps nginx cloudflared'), 'depois da troca e do túnel');
    assert.match(v.registro(), /removido-orfao=app/);
    assert.equal(v.lerChamadas().filter((c) => /volume (rm|prune)|down -v|rm -f .*(estaticos|dados|pacotes|camadas)/.test(c)).length, 0, 'nenhum volume tocado');
  } finally {
    v.limpar();
  }
});

test('primeira implantação que falha antes da troca não remove o app antigo', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_ORFAO: '1', DUBLE_BUILD_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.equal(v.contarChamadas('rm -f'), 0, 'o app antigo segue de pé');
    assert.doesNotMatch(v.registro(), /removido-orfao/);
  } finally {
    v.limpar();
  }
});

// Spec 009 X3b: verificação R4/R5 das migrações novas, na candidata, antes de migrar (comum.compat_migracao).
const ARQ_MIGRACAO = 'servidor/catalogo/migrations/0002_x.py';
const MIGRACAO_TEXTO = 'from django.db import migrations\n\n\nclass Migration(migrations.Migration):\n    dependencies = []\n    operations = [migrations.CreateModel(name="Teste", fields=[])]\n';
// Commit novo em main com arquivos dados (caminho -> texto); devolve o SHA. Caminho pode ter espaço e caracteres de shell.
function promoverCom(v, arquivos) {
  git(v.trabalho, 'switch', '-q', 'main');
  for (const [caminho, texto] of Object.entries(arquivos)) {
    const completo = path.join(v.trabalho, caminho);
    fs.mkdirSync(path.dirname(completo), { recursive: true });
    fs.writeFileSync(completo, texto);
  }
  git(v.trabalho, 'add', '.');
  git(v.trabalho, 'commit', '-q', '-m', 'migracao de teste');
  git(v.trabalho, 'push', '-q', 'origin', 'main');
  return git(v.trabalho, 'rev-parse', 'HEAD');
}

test('migração: sem arquivo novo de migração, migracao=nenhuma e o verificador não é chamado', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = v.promover();
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b]);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contarChamadas('comum.compat_migracao'), 0);
    assert.ok(v.indice('run --rm migracao') >= 0, 'a migração roda do jeito de sempre');
    assert.match(v.registro(), / OK origem=azul destino=verde migracao=nenhuma\n/);
  } finally {
    v.limpar();
  }
});

test('migração compatível (rc 0): verificada na candidata antes de rodar, com backup, e o log diz compativel sem segredo', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b]);
    assert.equal(r.status, 0, r.stderr);
    const verificacao = v.indice('run --rm --no-deps migracao python -m comum.compat_migracao');
    assert.ok(verificacao >= 0, 'o verificador roda');
    assert.ok(verificacao < v.indice('run --rm migracao'), 'antes da migração');
    assert.ok(v.indice('pg_dump') >= 0 && v.indice('pg_dump') < verificacao, 'backup antes da verificação e da migração');
    assert.match(v.lerArgv(), /^\[catalogo\/migrations\/0002_x\.py\]$/m, 'o caminho vai sem o prefixo servidor/');
    assert.match(v.registro(), / OK origem=azul destino=verde migracao=compativel\n/);
    assert.ok(!v.registro().includes('valor-secreto-9f3a'));
  } finally {
    v.limpar();
  }
});

test('migração reprovada (rc 1): não roda, nginx e alvo.conf intactos, ativa segue, e a mensagem traz a linha REPROVADA', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const linha = 'REPROVADA servidor/catalogo/migrations/0002_x.py:7 RemoveField: remove coluna que a versão anterior ainda lê';
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_COMPAT_RC: '1', DUBLE_COMPAT_SAIDA: linha });
    assert.equal(r.status, 1);
    assert.ok(r.stderr.includes('REPROVADA servidor/catalogo/migrations/0002_x.py:7 RemoveField'), r.stderr);
    assert.match(r.stderr, /a pilha ativa segue servindo/);
    assert.equal(v.indice('run --rm migracao'), -1, 'a migração NÃO roda');
    assert.equal(v.contarChamadas('exec -T nginx'), 0, 'o nginx não é tocado');
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.match(v.registro(), /FALHOU: migração reprovada pelo verificador \(rc 1\)/);
  } finally {
    v.limpar();
  }
});

test('verificador com erro (rc 2, ilegível ou sintaxe): erro antes da migração, ativa segue', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_COMPAT_RC: '2', DUBLE_COMPAT_SAIDA: 'ERRO arquivo ilegível' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /rc 2/);
    assert.equal(v.indice('run --rm migracao'), -1);
    assert.equal(v.lerAlvo(), ALVO_AZUL);
  } finally {
    v.limpar();
  }
});

test('rc desconhecido do verificador (ex.: 5): erro, fecha falhado, migração não roda', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_COMPAT_RC: '5' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /saída inesperada do verificador de migração \(rc 5\)/);
    assert.equal(v.indice('run --rm migracao'), -1);
    assert.equal(v.lerAlvo(), ALVO_AZUL);
  } finally {
    v.limpar();
  }
});

test('migração fora do fluxo (rc 3) sem PHATI_ACEITO_PARADA: erro que pede parada e aprovação, nada parado, nada migrado', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_COMPAT_RC: '3', DUBLE_COMPAT_SAIDA: 'FORA_DO_FLUXO servidor/catalogo/migrations/0002_x.py' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /exige parada do site, janela e aprovação do mantenedor/);
    assert.equal(v.contarChamadas('stop app_azul'), 0, 'nada parado');
    assert.equal(v.indice('run --rm migracao'), -1);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
  } finally {
    v.limpar();
  }
});

test('migração fora do fluxo (rc 3) com PHATI_ACEITO_PARADA=1: para a ativa antes de migrar, avisa, troca e registra fora-do-fluxo', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_COMPAT_RC: '3', DUBLE_COMPAT_SAIDA: 'FORA_DO_FLUXO servidor/catalogo/migrations/0002_x.py', PHATI_ACEITO_PARADA: '1' });
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stderr, /FICA FORA DO AR/);
    const ordem = ['stop app_azul', 'run --rm migracao', 'up -d --no-deps app_verde'].map((t) => v.indice(t));
    assert.ok(ordem.every((i) => i >= 0), `faltou passo: ${ordem}`);
    assert.deepEqual([...ordem].sort((a, b2) => a - b2), ordem, 'parar antes de migrar, migrar antes de subir a candidata');
    assert.equal(v.lerArquivo('ativa').trim(), 'verde');
    assert.match(v.registro(), / OK origem=azul destino=verde migracao=fora-do-fluxo\n/);
  } finally {
    v.limpar();
  }
});

test('migração fora do fluxo: falha depois da parada diz que a ativa foi parada e o comando exato para subi-la', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_COMPAT_RC: '3', DUBLE_COMPAT_SAIDA: 'FORA_DO_FLUXO x', PHATI_ACEITO_PARADA: '1', DUBLE_SAUDE_VERDE: 'unhealthy' });
    assert.equal(r.status, 1);
    assert.equal(v.contarChamadas('stop app_azul'), 1);
    assert.match(r.stderr, /a pilha ativa \(azul\) foi parada para a migração fora do fluxo e NÃO serve/);
    assert.ok(r.stderr.includes(`up -d --no-deps app_azul`), r.stderr);
    assert.match(v.registro(), /FALHOU: a candidata app_verde não ficou saudável/);
  } finally {
    v.limpar();
  }
});

test('primeira implantação: sem ativa não há verificação (nada a comparar) e o log diz nenhuma', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_COMPAT_RC: '1' });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contarChamadas('comum.compat_migracao'), 0);
    assert.match(v.registro(), / OK origem=nenhuma destino=azul migracao=nenhuma\n/);
  } finally {
    v.limpar();
  }
});

test('--sem-migracao: sem verificação e sem migração, log diz pulada', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b, '--sem-migracao'], { DUBLE_COMPAT_RC: '1' });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contarChamadas('comum.compat_migracao'), 0);
    assert.equal(v.indice('run --rm migracao'), -1);
    assert.match(v.registro(), / OK origem=azul destino=verde migracao=pulada\n/);
  } finally {
    v.limpar();
  }
});

test('nome de arquivo hostil (espaço, ;, $(...)) chega ao verificador como um argumento só, sem virar shell', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const hostil = 'servidor/catalogo/migrations/0002_a b;$(touch PWNED).py';
    const b = promoverCom(v, { [hostil]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b]);
    assert.equal(r.status, 0, r.stderr);
    assert.ok(v.lerArgv().split('\n').includes('[catalogo/migrations/0002_a b;$(touch PWNED).py]'), v.lerArgv());
    assert.equal(fs.existsSync(path.join(v.repo, 'PWNED')), false);
  } finally {
    v.limpar();
  }
});

test('base da verificação inexistente no repositório: erro, sem chamar o verificador', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    fs.writeFileSync(path.join(v.vm, 'pilha-azul.sha'), `${'f'.repeat(40)}\n`);
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b]);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /não existe no repositório/);
    assert.equal(v.contarChamadas('comum.compat_migracao'), 0);
    assert.equal(v.indice('run --rm migracao'), -1);
  } finally {
    v.limpar();
  }
});

test('backup ausente com migração a verificar: erro antes da migração', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_BANCO: '0', DUBLE_VOLUME: '0', DUBLE_COMPAT_RC: '0' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /backup verificado ausente ou vazio: a migração não roda/);
    assert.equal(v.indice('run --rm migracao'), -1);
    assert.equal(v.indice('pg_dump'), -1);
  } finally {
    v.limpar();
  }
});

// X3c: estado que não pode mentir (pilha-<cor>.sha só com SHA que a pilha de fato roda) e repositório devolvido ao SHA
// que estava no ar quando a implantação falha (o nginx lê o default.conf do clone numa reinicialização).
test('X3c: falha depois da candidata saudável grava pilha-<cand>.sha com o SHA novo, nunca o antigo', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = v.promover();
    assert.equal(v.rodar(IMPLANTAR, [b]).status, 0);
    const c = v.promover();
    v.zerar();
    // A candidata azul sobe com C (saudável); o nginx -t falha depois: a azul de fato roda C.
    const r = v.rodar(IMPLANTAR, [c], { DUBLE_NGINX_TESTE_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.equal(v.lerArquivo('pilha-azul.sha').trim(), c, 'o estado diz o SHA que a azul roda');
  } finally {
    v.limpar();
  }
});

test('X3c: candidata não saudável tira pilha-<cand>.sha, e pedir o SHA antigo depois não cai no rollback rápido', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = v.promover();
    assert.equal(v.rodar(IMPLANTAR, [b]).status, 0);
    const c = v.promover();
    v.zerar();
    const r = v.rodar(IMPLANTAR, [c], { DUBLE_SAUDE_AZUL: 'unhealthy' });
    assert.equal(r.status, 1);
    assert.equal(fs.existsSync(path.join(v.vm, 'pilha-azul.sha')), false, 'a azul não roda SHA nenhum confiável');
    v.zerar();
    const antigo = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(antigo.status, 0, antigo.stderr);
    assert.ok(v.indice(' build') >= 0, 'sem a azul rotulada, o SHA antigo é reconstruído, sem rollback rápido');
  } finally {
    v.limpar();
  }
});

test('X3c: erro depois da troca devolve o repositório ao SHA anterior e registra repo-restaurado', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = v.promover();
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_NGINX_TESTE_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.equal(git(v.repo, 'rev-parse', 'HEAD'), v.promovido, 'o clone volta ao SHA que estava no ar');
    assert.match(v.registro(), /repo-restaurado=[0-9a-f]{12}/);
  } finally {
    v.limpar();
  }
});

test('X3c: sucesso não devolve o repositório ao SHA anterior', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = v.promover();
    const r = v.rodar(IMPLANTAR, [b]);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(git(v.repo, 'rev-parse', 'HEAD'), b);
    assert.doesNotMatch(v.registro(), /repo-restaurado/);
  } finally {
    v.limpar();
  }
});

test('X3c: primeira implantação que falha não faz checkout de volta (anterior = nenhum)', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_SAUDE: 'unhealthy' });
    assert.equal(r.status, 1);
    assert.equal(git(v.repo, 'rev-parse', 'HEAD'), v.promovido);
    assert.doesNotMatch(v.registro(), /repo-restaurado/);
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
