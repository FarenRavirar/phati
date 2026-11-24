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
const { unix, lerLinhas, escreverFlock } = require('./ajuda-teste');

const ASSINCRONO = promisify(execFile);
const PASTA = __dirname;
const IMPLANTAR = path.join(PASTA, 'implantar.sh');
const RESTAURAR = path.join(PASTA, 'restaurar.sh');
const BACKUP = path.join(PASTA, 'backup.sh');
const GUARDAR = path.join(PASTA, 'guardar-implantacao.sh');
const SMOKE = path.join(PASTA, 'smoke-implantacao.sh');
const SHA_RUIM = 'não-é-sha';

const git = (diretorio, ...argumentos) =>
  execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', ...argumentos], { cwd: diretorio, stdio: 'pipe', encoding: 'utf8' }).trim();

// VM de mentira: remoto com `main`, clone em `repo/` (com a pasta `servidor/`), `.env` e um `docker` que anota e responde.
function criarVm({ comEnv = true, nomeVm = 'vm' } = {}) {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), 'implantacao-'));
  const remoto = path.join(raiz, 'remoto.git');
  const vm = path.join(raiz, nomeVm);
  const repo = path.join(vm, 'repo');
  const trabalho = path.join(raiz, 'trabalho');
  execFileSync('git', ['init', '-q', '--bare', '-b', 'main', remoto]);
  execFileSync('git', ['clone', '-q', remoto, trabalho], { stdio: 'pipe' });
  fs.mkdirSync(path.join(trabalho, 'servidor'));
  fs.writeFileSync(path.join(trabalho, 'servidor', 'arquivo'), 'a\n');
  git(trabalho, 'add', '.');
  git(trabalho, 'commit', '-q', '-m', 'um');
  // Ancestral de main sem a infraestrutura de implantação (o SHA que apagou o nginx do clone na VM): a pré-checagem recusa.
  const semInfra = git(trabalho, 'rev-parse', 'HEAD');
  fs.writeFileSync(path.join(trabalho, 'servidor', 'compose.implantacao.yaml'), 'services: {}\n');
  fs.mkdirSync(path.join(trabalho, 'servidor', 'nginx'));
  fs.writeFileSync(path.join(trabalho, 'servidor', 'nginx', 'default.conf'), 'server {}\n');
  git(trabalho, 'add', '.');
  git(trabalho, 'commit', '-q', '-m', 'dois: infraestrutura de implantação');
  // Ancestral de main com infraestrutura mas sem o serviço banco_novo: a pré-checagem do banco ativo (C5) recusa.
  const semBancoNovo = git(trabalho, 'rev-parse', 'HEAD');
  fs.writeFileSync(path.join(trabalho, 'servidor', 'compose.implantacao.yaml'), 'services:\n  banco:\n    image: sintetica\n  banco_novo:\n    image: sintetica\n');
  git(trabalho, 'add', '.');
  git(trabalho, 'commit', '-q', '-m', 'tres: serviço banco_novo');
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
  // PHATI_ALVO_DIR que cada chamada ao Docker recebeu (X4: o backup e a restauração resolvem o caminho sem a variável).
  const alvoVars = path.join(raiz, 'alvo-vars.log');
  // COMPOSE_PROFILES que cada chamada ao Docker viu (spec 009 R15, T5.4c: `banco_novo` só existe com o profile da troca).
  const perfis = path.join(raiz, 'perfis.log');
  // PHATI_BANCO_DESTINO que cada chamada ao Docker recebeu pelo ambiente (o `.env` não entra aqui: o compose o lê sozinho).
  const destinos = path.join(raiz, 'destinos.log');
  const dublê = path.join(raiz, 'docker-dubles.sh');
  fs.writeFileSync(
    dublê,
    [
      '#!/usr/bin/env bash',
      'echo "$*" >> "$CHAMADAS"',
      'echo "${PHATI_ALVO_DIR:-sem-alvo}" >> "$ALVO_VARS"',
      'echo "${COMPOSE_PROJECT_NAME:-sem-projeto}" >> "$PROJETOS"',
      'echo "${COMPOSE_PROFILES:-sem-perfil}" >> "$PERFIS"',
      'echo "${PHATI_BANCO_DESTINO:-sem-destino}" >> "$DESTINOS"',
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
      '  *"service=nginx"*) [[ "${DUBLE_NGINX_AUSENTE:-0}" == 1 ]] || echo nginx1 ;;',
      '  *"ps -aq --filter"*) [[ "${DUBLE_ORFAO:-0}" == 1 ]] && echo orfao1 ;;',
      '  *"ps -q nginx"*) [[ "${DUBLE_NGINX:-1}" == 1 ]] && echo nginx1 ;;',
      // O default.conf inclui /etc/nginx/alvo/alvo.conf sem condição: sem o arquivo, o nginx -t reprova (medido com nginx 1.18).
      '  *"nginx -t"*) cat "$ALVO_DIR/alvo.conf" >> "$VISTO" 2>/dev/null; echo "--" >> "$VISTO"; [[ -f "$ALVO_DIR/alvo.conf" ]] || exit 1; [[ "${DUBLE_NGINX_TESTE_FALHA:-0}" == 1 ]] && exit 1; [[ "${DUBLE_NGINX_CANDIDATA_INVALIDA:-0}" == 1 && "$*" == *"exec -T nginx nginx -t"* ]] && grep -q app_verde "$ALVO_DIR/alvo.conf" && exit 1 ;;',
      '  *"nginx -s reload"*) [[ "${DUBLE_RELOAD_FALHA:-0}" == 1 ]] && exit 1; [[ "${DUBLE_RELOAD_2_FALHA:-0}" == 1 && "$(grep -c "nginx -s reload" "$CHAMADAS")" -ge 2 ]] && exit 1 ;;',
      '  *"exec -T nginx wget"*) [[ "${DUBLE_SAUDA_NGINX_FALHA:-0}" == 1 ]] && exit 1 ;;',
      // Marca `sim`/`nao` do default.conf: `nao` só até a primeira recriação do nginx (o contêiner recriado já o monta).
      // DUBLE_EXEC_FALHA simula erro do exec (sem marca, rc 1): não é arquivo ausente.
      '  *"exec -T nginx sh -c"*"/etc/nginx/conf.d/default.conf"*) [[ "${DUBLE_EXEC_FALHA:-0}" == 1 ]] && exit 1; if [[ "${DUBLE_CONF_AUSENTE:-0}" == 1 ]] && ! grep -q "force-recreate nginx" "$CHAMADAS"; then echo nao; else echo sim; fi ;;',
      '  *"force-recreate nginx"*) [[ "${DUBLE_RECRIAR_FALHA:-0}" == 1 ]] && exit 1 ;;',
      // R17: contagem de publicações na origem. DUBLE_PUBLICACAO = contagem (padrão 0); DUBLE_PUBLICACAO_FALHA: consulta falha.
      '  *"pg_publication"*) [[ "${DUBLE_PUBLICACAO_FALHA:-0}" == 1 ]] && exit 1; echo "${DUBLE_PUBLICACAO:-0}" ;;',
      // R9/A5 (passos da troca e da faxina): falhas injetadas no `up` do nginx (DUBLE_NGINX_UP_FALHA) e do cloudflared
      // (DUBLE_TUNEL_FALHA), no `rm` do órfão. Os `up` são separados: a mensagem diz qual falhou.
      // DUBLE_NGINX_UP_2_FALHA: só o segundo `up` do nginx (o da etapa depois da troca; na primeira implantação o primeiro está na troca).
      '  *"up -d --no-deps nginx"*) [[ "${DUBLE_NGINX_UP_FALHA:-0}" == 1 ]] && exit 1; [[ "${DUBLE_NGINX_UP_2_FALHA:-0}" == 1 && "$(grep -c "up -d --no-deps nginx" "$CHAMADAS")" -ge 2 ]] && exit 1 ;;',
      '  *"up -d --no-deps cloudflared"*) [[ "${DUBLE_TUNEL_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"rm -f"*) [[ "${DUBLE_ORFAO_RM_FALHA:-0}" == 1 ]] && exit 1 ;;',
      '  *"exec -T banco"*pg_dump*) echo "dados-do-banco" ;;',
      // DUBLE_INSPECT_FALHA: o inspect falha (rc 1, sem saída). DUBLE_RUNNING_SAIDA: saída que não é true nem false.
      '  *"State.Running"*) [[ "${DUBLE_INSPECT_FALHA:-0}" == 1 ]] && exit 1; if [[ -n "${DUBLE_RUNNING_SAIDA:-}" ]]; then echo "$DUBLE_RUNNING_SAIDA"; elif [[ "${DUBLE_NGINX_PARADO:-0}" == 1 ]]; then echo false; else echo true; fi ;;',
      '  *inspect*app_azul*) echo "${DUBLE_SAUDE_AZUL:-${DUBLE_SAUDE:-healthy}}" ;;',
      '  *inspect*app_verde*) echo "${DUBLE_SAUDE_VERDE:-${DUBLE_SAUDE:-healthy}}" ;;',
      '  *inspect*pgb21*) echo "${DUBLE_SAUDE_PGB2:-${DUBLE_SAUDE_PGB:-healthy}}" ;;',
      '  *inspect*pgb*) echo "${DUBLE_SAUDE_PGB:-healthy}" ;;',
      '  "volume inspect"*) [[ "${DUBLE_VOLUME:-0}" == 1 ]] || exit 1 ;;',
      'esac',
      'exit 0',
      '',
    ].join('\n'),
    { mode: 0o755 },
  );
  // `flock` de mentira (scripts/ajuda-teste.js), com registro das chamadas. O `flock` de verdade tem o passo próprio
  // do CI (`trava-flock.test.sh`); aqui se prova o que o script faz com ele.
  const flockChamadas = path.join(raiz, 'flock.log');
  const flockDuble = escreverFlock(path.join(raiz, 'flock-dubles.sh'), { registro: true });
  const ambiente = {
    ...process.env,
    // Sem perfil herdado do processo: só o `extra` do teste pode ligar um profile (o que o script exporta é o que se mede).
    COMPOSE_PROFILES: '',
    PHATI_DIR: unix(vm),
    DOCKER: unix(dublê),
    PHATI_FLOCK: unix(flockDuble),
    FLOCK_CHAMADAS: unix(flockChamadas),
    CHAMADAS: unix(chamadas),
    PHATI_ESPERA: '0',
    PHATI_TENTATIVAS: '2',
    PHATI_ALVO_DIR: unix(path.join(vm, 'alvo')),
    ALVO_DIR: unix(path.join(vm, 'alvo')),
    ALVO_VARS: unix(alvoVars),
    VISTO: unix(visto),
    PGB_MARCA: unix(path.join(raiz, 'pgb-no-ar')),
    ARGV: unix(path.join(vm, 'compat-argv.log')),
    PROJETOS: unix(projetos),
    PERFIS: unix(perfis),
    DESTINOS: unix(destinos),
    // Vazio = padrão `phati`, mesmo que o ambiente de quem roda tenha PHATI_PROJETO.
    PHATI_PROJETO: '',
    // Vazio = sem destino herdado do ambiente de quem roda (cada teste liga o que quer pelo `extra`).
    PHATI_BANCO_DESTINO: '',
  };
  const rodar = (script, argumentos, extra = {}) =>
    spawnSync('bash', [unix(script), ...argumentos], { env: { ...ambiente, ...extra }, encoding: 'utf8' });
  const lerChamadas = () => lerLinhas(chamadas);
  const indice = (trecho) => lerChamadas().findIndex((linha) => linha.includes(trecho));
  const lerFlock = () => lerLinhas(flockChamadas);
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
  const lerProjetos = () => lerLinhas(projetos);
  const lerAlvoVars = () => lerLinhas(alvoVars);
  const lerPerfis = () => lerLinhas(perfis);
  const lerDestinos = () => lerLinhas(destinos);
  return { vm, repo, promovido, semInfra, semBancoNovo, foraDeMain,lerAlvoVars, lerPerfis, lerDestinos, rodar, lerChamadas, lerProjetos, lerFlock, indice, registro, limpar, promover, zerar, lerAlvo, lerArquivo, contarChamadas, visto, alvo: path.join(vm, 'alvo'), trabalho, lerArgv: () => fs.readFileSync(path.join(vm, 'compat-argv.log'), 'utf8') };
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
    const ordem = ['pg_dump', ' build', 'up -d --no-deps pgb_ns pgb1 pgb2', 'run --rm migracao', 'run --rm --no-deps estaticos_azul', 'up -d --no-deps app_azul', 'run --rm --no-deps nginx nginx -t', 'exec -T nginx wget', 'up -d --no-deps cloudflared'].map((t) => v.indice(t));
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
    const dump = criarDump(v);
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
    const ordem = [' build', 'up -d --no-deps pgb_ns pgb1 pgb2', 'run --rm migracao', 'run --rm --no-deps estaticos_azul', 'up -d --no-deps app_azul', 'run --rm --no-deps nginx nginx -t', 'exec -T nginx wget', 'up -d --no-deps cloudflared'].map((t) => v.indice(t));
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
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b]);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /ativa=verde anterior=azul/);
    assert.equal(v.lerArquivo('ativa').trim(), 'verde');
    assert.equal(v.lerAlvo(), ALVO_VERDE);
    assert.equal(v.lerArquivo('pilha-verde.sha').trim(), b);
    assert.equal(v.lerArquivo('pilha-azul.sha').trim(), v.promovido, 'a azul segue com o SHA dela');
    assert.equal(v.indice('stop '), -1, 'a azul não para');
    assert.equal(v.contarChamadas('up -d --no-deps app_azul'), 0, 'a azul não é recriada');
    const ordem = [' build', 'run --rm --no-deps estaticos_verde', 'up -d --no-deps app_verde', 'exec -T nginx nginx -t', 'exec -T nginx nginx -s reload', 'exec -T nginx wget', 'up -d --no-deps cloudflared'].map((t) => v.indice(t));
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
    const b = implantarEPromover(v);
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
    // A autocura só lê o contêiner (exec sh -c, marca sim): nginx não é recarregado nem recriado.
    assert.equal(v.contarChamadas('nginx -s reload'), 0);
    assert.equal(v.contarChamadas('force-recreate'), 0);
    assert.match(v.registro(), /FALHOU/);
  } finally {
    v.limpar();
  }
});

test('nginx -t falha: nenhum reload, alvo.conf anterior restaurado e a ativa segue', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
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
    const b = implantarEPromover(v);
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
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_SAUDA_NGINX_FALHA: '1', DUBLE_RELOAD_2_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /alvo.conf revertido, mas o nginx não recarregou; recupere com:/);
    const recuperacao = `printf 'set $alvo app_azul;\\nset $pilha azul;\\n' > ${unix(v.alvo)}/alvo.conf && PHATI_ALVO_DIR=${unix(v.alvo)} COMPOSE_PROJECT_NAME=phati docker compose --env-file ${unix(v.vm)}/.env -f ${unix(v.vm)}/repo/servidor/compose.yaml -f ${unix(v.vm)}/repo/servidor/compose.implantacao.yaml exec -T nginx nginx -s reload`;
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
      // A autocura só lê o contêiner (exec sh -c, marca sim): o nginx não é recarregado nem recriado.
      assert.equal(v.contarChamadas('nginx -s reload'), 0, `${esperado}: o nginx não é recarregado`);
      assert.equal(v.contarChamadas('force-recreate'), 0, `${esperado}: o nginx não é recriado`);
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
    // A autocura só lê o contêiner (exec sh -c, marca sim): nginx não é recarregado nem recriado.
    assert.equal(v.contarChamadas('nginx -s reload'), 0);
    assert.equal(v.contarChamadas('force-recreate'), 0);
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
    for (const bloco of blocos) assert.match(bloco, /^set \$alvo app_(azul|verde);\nset \$pilha \1;\n$/, bloco);
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

// Banco ativo (spec 009 R15, T5.4c): `banco-ativo` = banco_novo faz os scripts falarem com esse serviço e ligarem o profile da
// troca. Sem o arquivo, o padrão é `banco` e nenhum profile é ligado. Valor hostil recusa antes de qualquer chamada ao Docker.
// Chamada que mexe no serviço `banco` (palavra exata, não `banco_novo` nem `banco_extensoes`).
const tocaBancoAntigo = (chamadas) => chamadas.filter((l) => /(^| )banco( |$)/.test(l));
// Mesma chamada `exec -T <svc> sh -c` que leva o comando (pg_dump ou pg_restore): não basta um `sh -c` qualquer no serviço.
const chamadaShCom = (v, svc, comando) => v.lerChamadas().find((l) => l.includes(`exec -T ${svc} sh -c`) && l.includes(comando));

test('implantar com banco-ativo=banco_novo sobe, espera e faz backup de banco_novo, com o profile da troca', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco_novo\n');
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_BANCO: '0', DUBLE_VOLUME: '1' });
    assert.equal(r.status, 0, r.stderr);
    assert.ok(v.indice('up -d --wait banco_novo') >= 0, 'faltou subir banco_novo');
    assert.ok(chamadaShCom(v, 'banco_novo', 'pg_dump'), 'o backup tem de rodar pg_dump em banco_novo');
    assert.ok(v.lerChamadas().includes('volume inspect phati_dados_banco_novo'), 'tem_dados tem de olhar o volume dados_banco_novo');
    assert.deepEqual(tocaBancoAntigo(v.lerChamadas()), [], 'o serviço banco antigo não pode ser tocado');
    assert.ok(v.lerPerfis().length > 0 && v.lerPerfis().every((p) => p === 'troca-banco'), v.lerPerfis().join(','));
  } finally {
    v.limpar();
  }
});

test('implantar sem banco-ativo usa banco e não liga profile nenhum', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_BANCO: '0', DUBLE_VOLUME: '1' });
    assert.equal(r.status, 0, r.stderr);
    assert.ok(v.indice('up -d --wait banco') >= 0);
    assert.ok(v.lerChamadas().includes('volume inspect phati_dados_banco'));
    assert.equal(v.lerChamadas().filter((l) => l.includes('banco_novo')).length, 0);
    assert.ok(v.lerPerfis().every((p) => p === 'sem-perfil'), v.lerPerfis().join(','));
  } finally {
    v.limpar();
  }
});

test('implantar com banco-ativo=banco_novo recusa SHA cujo compose não declara banco_novo, antes do checkout e sem Docker', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco_novo\n');
    const antes = git(v.repo, 'rev-parse', 'HEAD');
    const r = v.rodar(IMPLANTAR, [v.semBancoNovo], { DUBLE_BANCO: '0', DUBLE_VOLUME: '1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /o SHA não declara o serviço banco_novo no compose de implantação/);
    assert.equal(git(v.repo, 'rev-parse', 'HEAD'), antes, 'o clone mudou antes da recusa');
    assert.equal(v.lerChamadas().length, 0, 'chamada Docker antes da recusa');
  } finally {
    v.limpar();
  }
});

test('implantar sem banco-ativo não aplica a checagem do banco_novo: SHA sem o serviço segue', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.semBancoNovo], { DUBLE_BANCO: '0', DUBLE_VOLUME: '1' });
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.equal(git(v.repo, 'rev-parse', 'HEAD'), v.semBancoNovo);
    assert.doesNotMatch(r.stderr, /não declara o serviço/);
  } finally {
    v.limpar();
  }
});

test('implantar recusa banco-ativo hostil ou fora de banco e banco_novo, sem tocar o Docker', () => {
  const v = criarVm();
  try {
    for (const ruim of ['banco; rm -rf /', ' ', 'banco_velho', '']) {
      fs.writeFileSync(path.join(v.vm, 'banco-ativo'), ruim);
      const r = v.rodar(IMPLANTAR, [v.promovido]);
      assert.equal(r.status, 1, JSON.stringify(ruim));
      assert.match(r.stderr, /banco-ativo tem valor inválido/);
    }
    assert.deepEqual(v.lerChamadas(), []);
  } finally {
    v.limpar();
  }
});

test('backup.sh com banco-ativo=banco_novo faz o pg_dump nesse serviço, com o profile da troca', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco_novo\n');
    const r = v.rodar(BACKUP, ['ab']);
    assert.equal(r.status, 0, r.stderr);
    assert.ok(chamadaShCom(v, 'banco_novo', 'pg_dump'), v.lerChamadas().join('\n'));
    assert.deepEqual(tocaBancoAntigo(v.lerChamadas()), []);
    assert.ok(v.lerPerfis().length > 0 && v.lerPerfis().every((p) => p === 'troca-banco'), v.lerPerfis().join(','));
  } finally {
    v.limpar();
  }
});

test('backup.sh sem banco-ativo faz o pg_dump em banco, sem profile', () => {
  const v = criarVm();
  try {
    const r = v.rodar(BACKUP, ['ab']);
    assert.equal(r.status, 0, r.stderr);
    assert.ok(chamadaShCom(v, 'banco', 'pg_dump'), 'o backup tem de rodar pg_dump em banco');
    assert.ok(v.lerPerfis().every((p) => p === 'sem-perfil'), v.lerPerfis().join(','));
  } finally {
    v.limpar();
  }
});

test('backup.sh recusa banco-ativo hostil sem tocar o Docker', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco_velho\n');
    const r = v.rodar(BACKUP, ['ab']);
    afirmarRecusa(v, r, /banco-ativo tem valor inválido/);
  } finally {
    v.limpar();
  }
});

test('restaurar com banco-ativo=banco_novo sobe e restaura banco_novo, com o profile da troca', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco_novo\n');
    const dump = criarDump(v);
    const r = v.rodar(RESTAURAR, [dump, 'RESTAURAR']);
    assert.equal(r.status, 0, r.stderr);
    assert.ok(v.indice('up -d --wait banco_novo') >= 0, 'faltou subir banco_novo');
    assert.ok(chamadaShCom(v, 'banco_novo', 'pg_restore'), 'a restauração tem de rodar pg_restore em banco_novo');
    assert.deepEqual(tocaBancoAntigo(v.lerChamadas()), []);
    assert.ok(v.lerPerfis().length > 0 && v.lerPerfis().every((p) => p === 'troca-banco'), v.lerPerfis().join(','));
  } finally {
    v.limpar();
  }
});

test('restaurar recusa banco-ativo hostil sem tocar o Docker', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco; rm -rf /');
    const dump = criarDump(v);
    const r = v.rodar(RESTAURAR, [dump, 'RESTAURAR']);
    afirmarRecusa(v, r, /banco-ativo tem valor inválido/);
  } finally {
    v.limpar();
  }
});

// Troca de banco interrompida e divergência de destino (spec 009 R15). O marcador `troca-banco-em-curso` recusa implantar,
// backup e restaurar antes de qualquer chamada ao Docker. Com banco-ativo=banco_novo, o compose recebe o destino pelo ambiente
// (vence o `.env`); com banco (ou sem o arquivo), um destino banco_novo no `.env` ou no ambiente é divergência e recusa.
const MENSAGEM_MARCADOR = /troca de banco interrompida \(marcador .*troca-banco-em-curso\): reconcilie antes de implantar/;
const MENSAGEM_DIVERGENTE = /estado de banco divergente: \.env aponta banco_novo, banco-ativo não/;
const apontarDestino = (v, valor) => fs.appendFileSync(path.join(v.vm, '.env'), `PHATI_BANCO_DESTINO=${valor}\n`);
const todosDestinos = (v, esperado) => {
  const destinos = v.lerDestinos();
  assert.ok(destinos.length > 0, 'nenhuma chamada ao Docker');
  assert.ok(destinos.every((d) => d === esperado), destinos.join(','));
};

test('implantar, backup e restaurar recusam com marcador de troca interrompida, sem tocar o Docker', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'troca-banco-em-curso'), 'modo=fisica passo=pausa\n');
    afirmarRecusa(v, v.rodar(IMPLANTAR, [v.promovido]), MENSAGEM_MARCADOR);
    afirmarRecusa(v, v.rodar(BACKUP, ['ab']), MENSAGEM_MARCADOR);
    afirmarRecusa(v, v.rodar(RESTAURAR, [criarDump(v), 'RESTAURAR']), MENSAGEM_MARCADOR);
    assert.ok(fs.existsSync(path.join(v.vm, 'troca-banco-em-curso')), 'a recusa não pode remover o marcador');
  } finally {
    v.limpar();
  }
});

test('implantar com banco-ativo=banco_novo passa PHATI_BANCO_DESTINO=banco_novo ao compose, mesmo com .env sem destino', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco_novo\n');
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_BANCO: '0', DUBLE_VOLUME: '1' });
    assert.equal(r.status, 0, r.stderr);
    todosDestinos(v, 'banco_novo');
  } finally {
    v.limpar();
  }
});

test('backup.sh com banco-ativo=banco_novo passa o destino ao compose', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco_novo\n');
    const r = v.rodar(BACKUP, ['ab']);
    assert.equal(r.status, 0, r.stderr);
    todosDestinos(v, 'banco_novo');
  } finally {
    v.limpar();
  }
});

test('restaurar com banco-ativo=banco_novo passa o destino ao compose', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco_novo\n');
    const r = v.rodar(RESTAURAR, [criarDump(v), 'RESTAURAR']);
    assert.equal(r.status, 0, r.stderr);
    todosDestinos(v, 'banco_novo');
  } finally {
    v.limpar();
  }
});

test('.env com banco_novo e banco-ativo ausente é divergência: implantar, backup e restaurar recusam sem tocar o Docker', () => {
  const v = criarVm();
  try {
    apontarDestino(v, 'banco_novo');
    afirmarRecusa(v, v.rodar(IMPLANTAR, [v.promovido]), MENSAGEM_DIVERGENTE);
    afirmarRecusa(v, v.rodar(BACKUP, ['ab']), MENSAGEM_DIVERGENTE);
    afirmarRecusa(v, v.rodar(RESTAURAR, [criarDump(v), 'RESTAURAR']), MENSAGEM_DIVERGENTE);
  } finally {
    v.limpar();
  }
});

test('destino banco_novo herdado do ambiente com banco-ativo=banco também é divergência e recusa', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco\n');
    afirmarRecusa(v, v.rodar(IMPLANTAR, [v.promovido], { PHATI_BANCO_DESTINO: 'banco_novo' }), MENSAGEM_DIVERGENTE);
  } finally {
    v.limpar();
  }
});

test('sem marcador e sem divergência, implantar segue sem destino exportado e com .env=banco também segue', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_BANCO: '0', DUBLE_VOLUME: '1' });
    assert.equal(r.status, 0, r.stderr);
    todosDestinos(v, 'sem-destino');
  } finally {
    v.limpar();
  }
  const w = criarVm();
  try {
    apontarDestino(w, 'banco');
    const r = w.rodar(IMPLANTAR, [w.promovido], { DUBLE_BANCO: '0', DUBLE_VOLUME: '1' });
    assert.equal(r.status, 0, r.stderr);
    todosDestinos(w, 'sem-destino');
  } finally {
    w.limpar();
  }
});

test('restaurar sobe e para só a pilha ativa, lida de `ativa`', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'ativa'), 'verde\n');
    const dump = criarDump(v);
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
    const dump = criarDump(v);
    const r = v.rodar(RESTAURAR, [dump, 'RESTAURAR']);
    afirmarRecusa(v, r, /tem valor inválido/);
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
    assert.ok(v.indice('run --rm --no-deps pgb_auth') >= 0, 'o auth tem de rodar');
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
    assert.ok(v.indice('rm -f orfao1') > v.indice('up -d --no-deps cloudflared'), 'depois da troca e do túnel');
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

// R9/A5 (T4.1): falhas injetadas nos passos sem teste. Cada um afirma: pilha ativa de pé, alvo e `ativa` coerentes,
// comando de recuperação quando a reversão falha, código de saída e registro.

// Dublê de `mv` que falha só quando o destino casa `padrao` (padrão do `case` do shell); o resto vai para o `mv` de verdade.
function mvQueFalha(padrao) {
  const shim = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-falha-'));
  const mvReal = unix(execFileSync('bash', ['-c', 'command -v mv'], { encoding: 'utf8' }).trim());
  fs.writeFileSync(path.join(shim, 'mv'), `#!/usr/bin/env bash\nfor arg; do :; done\ncase "$arg" in ${padrao}) echo "mv: falha simulada" >&2; exit 1 ;; esac\nexec "${mvReal}" "$@"\n`, { mode: 0o755 });
  return shim;
}
const comPath = (shim) => ({ PATH: [shim, process.env.PATH].join(path.delimiter) });
const temporarios = (dir) => fs.readdirSync(dir).filter((nome) => nome.startsWith('.tmp.'));

test('R9/A5 trava: segunda implantação com a trava ocupada (código 75) sai com erro limpo e a pilha ativa segue intacta', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    fs.writeFileSync(path.join(v.vm, '.trava.ocupado'), '');
    const r = v.rodar(IMPLANTAR, [b], { PHATI_TRAVA_LIMITE: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /outra implantação ou restauração segue rodando/);
    assert.doesNotMatch(r.stderr, /falhou no passo/);
    assert.deepEqual(v.lerChamadas(), [], 'nenhuma chamada ao Docker');
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.lerArquivo('pilha-azul.sha').trim(), v.promovido);
    assert.equal(fs.existsSync(path.join(v.vm, 'pilha-verde.sha')), false, 'a candidata não é tocada');
  } finally {
    v.limpar();
  }
});

test('R9/A5 gravar ativa falha na implantação normal: reverte o alvo.conf para a ativa anterior, avisa e registra FALHOU', () => {
  const v = criarVm();
  const shim = mvQueFalha('*/ativa');
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], comPath(shim));
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /falha ao gravar ativa=verde; alvo.conf revertido para app_azul, que segue servindo/);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.contarChamadas('nginx -s reload'), 2, 'recarrega para verde e de volta para azul');
    assert.deepEqual(temporarios(v.vm), [], 'nenhum temporário de `ativa` sobra');
    assert.match(v.registro(), /FALHOU: falha ao gravar ativa=verde/);
  } finally {
    fs.rmSync(shim, { recursive: true, force: true });
    v.limpar();
  }
});

test('R9/A5 gravar o alvo.conf falha na troca: nenhum reload, alvo e ativa intactos, sem temporário, e o aviso diz que a ativa segue', () => {
  const v = criarVm();
  const shim = mvQueFalha('*/alvo.conf');
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], comPath(shim));
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /falhou no passo: troca/);
    assert.match(r.stderr, /a pilha ativa \(azul\) segue servindo/);
    assert.equal(v.contarChamadas('nginx -s reload'), 0);
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.deepEqual(temporarios(v.alvo), [], 'o .tmp do alvo.conf não sobra no diretório que o nginx monta');
    assert.match(v.registro(), /FALHOU: falhou no passo: troca/);
  } finally {
    fs.rmSync(shim, { recursive: true, force: true });
    v.limpar();
  }
});

test('R9/A5 cloudflared falha depois da troca: reverte a troca (alvo e ativa voltam ao azul), diz que o túnel segue fora e dá o comando para subi-lo', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_TUNEL_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    const subir = `PHATI_ALVO_DIR=${unix(v.alvo)} COMPOSE_PROJECT_NAME=phati docker compose --env-file ${unix(v.vm)}/.env -f ${unix(v.vm)}/repo/servidor/compose.yaml -f ${unix(v.vm)}/repo/servidor/compose.implantacao.yaml up -d --no-deps cloudflared`;
    assert.ok(r.stderr.includes(`cloudflared falhou depois da troca; o túnel segue fora, suba à mão com: ${subir}; alvo.conf revertido para app_azul, que segue servindo`), r.stderr);
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.equal(v.contarChamadas('nginx -s reload'), 2, 'recarrega o destino novo e depois o anterior');
    assert.equal(v.indice('stop '), -1, 'nenhuma pilha parada');
    assert.match(v.registro(), /FALHOU: cloudflared falhou depois da troca; o túnel segue fora/);
  } finally {
    v.limpar();
  }
});

test('R9/A5 nginx falha depois da troca: a mensagem diz que o nginx falhou, que o cloudflared não foi tentado e reverte a troca', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_NGINX_UP_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /nginx falhou depois da troca; cloudflared não foi tentado; alvo.conf revertido para app_azul, que segue servindo/);
    assert.equal(v.indice('up -d --no-deps cloudflared'), -1, 'o túnel não é tocado quando o nginx falha');
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
  } finally {
    v.limpar();
  }
});

test('R9/A5 cloudflared falha depois da troca e a reversão também falha: a mensagem traz o túnel fora e o comando de recuperação completo', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_TUNEL_FALHA: '1', DUBLE_RELOAD_2_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /cloudflared falhou depois da troca; o túnel segue fora, suba à mão com: .+; alvo.conf revertido, mas o nginx não recarregou; recupere com:/);
    const recuperacao = `printf 'set $alvo app_azul;\\nset $pilha azul;\\n' > ${unix(v.alvo)}/alvo.conf && PHATI_ALVO_DIR=${unix(v.alvo)} COMPOSE_PROJECT_NAME=phati docker compose --env-file ${unix(v.vm)}/.env -f ${unix(v.vm)}/repo/servidor/compose.yaml -f ${unix(v.vm)}/repo/servidor/compose.implantacao.yaml exec -T nginx nginx -s reload`;
    assert.ok(r.stderr.includes(recuperacao), r.stderr);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul', 'a ativa volta ao anterior antes da reversão do alvo');
  } finally {
    v.limpar();
  }
});

// Primeira implantação (sem `ativa`): o alvo.conf nunca é removido (o nginx monta o diretório e não sobe sem ele). Antes da
// correção, a reversão apagava o arquivo e deixava a config inválida.
test('R9/A5 primeira implantação com cloudflared falhando: alvo.conf segue na candidata, ativa coerente, sem rm na saída e com o comando de subida', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_TUNEL_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /cloudflared falhou depois da troca; o túnel segue fora, suba à mão com: .+ up -d --no-deps cloudflared; sem pilha anterior: a candidata app_azul segue no alvo.conf e em ativa, nada revertido/);
    assert.doesNotMatch(r.stderr, /rm -f/);
    assert.equal(v.lerAlvo(), ALVO_AZUL, 'alvo.conf segue apontando a candidata');
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.equal(v.contarChamadas('nginx -s reload'), 0, 'primeira implantação sobe o nginx por contêiner, sem reload');
    assert.match(v.registro(), /FALHOU: cloudflared falhou depois da troca/);
  } finally {
    v.limpar();
  }
});

test('R9/A5 primeira implantação com nginx falhando depois da troca: alvo.conf fica, a mensagem diz como subir o nginx e o túnel não é tentado', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_NGINX_UP_2_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /nginx falhou depois da troca; cloudflared não foi tentado; suba o nginx à mão com: .+ up -d --no-deps nginx; sem pilha anterior: a candidata app_azul segue no alvo.conf e em ativa, nada revertido/);
    assert.doesNotMatch(r.stderr, /rm -f/);
    assert.equal(v.indice('up -d --no-deps cloudflared'), -1, 'o túnel não é tocado quando o nginx falha');
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
  } finally {
    v.limpar();
  }
});

test('R9/A5 primeira implantação com /saude falhando na troca: mantém o alvo.conf da candidata, não grava ativa e diz que não há pilha anterior', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_SAUDA_NGINX_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /\/saude pelo nginx falhou depois do reload; sem pilha anterior: alvo.conf segue apontando app_azul/);
    assert.doesNotMatch(r.stderr, /rm -f/);
    assert.equal(v.lerAlvo(), ALVO_AZUL, 'o arquivo não some: o nginx o monta');
    assert.equal(fs.existsSync(path.join(v.vm, 'ativa')), false, 'a ativa não é gravada antes da troca');
    assert.match(v.registro(), /FALHOU: \/saude pelo nginx falhou/);
  } finally {
    v.limpar();
  }
});

test('R9/A5 ativa sem alvo.conf e /saude falhando: a reversão grava o destino da ativa (app_azul) em vez de remover o arquivo', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    fs.rmSync(path.join(v.alvo, 'alvo.conf'));
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_SAUDA_NGINX_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /\/saude pelo nginx falhou depois do reload; alvo.conf revertido para app_azul, que segue servindo/);
    assert.equal(v.lerAlvo(), ALVO_AZUL, 'alvo.conf com o destino da ativa');
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
  } finally {
    v.limpar();
  }
});

test('R9/A5 primeira implantação com /saude e reload falhando na reversão: diz que não há pilha anterior, mantém o alvo.conf da candidata e o comando não tem rm', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_SAUDA_NGINX_FALHA: '1', DUBLE_NGINX_UP_2_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /\/saude pelo nginx falhou depois do reload; sem pilha anterior: alvo.conf segue apontando app_azul, mas o nginx não recarregou; recupere com: .+ up -d --no-deps nginx/);
    assert.doesNotMatch(r.stderr, /rm -f/);
    assert.doesNotMatch(r.stderr, /alvo.conf revertido/);
    assert.equal(v.lerAlvo(), ALVO_AZUL, 'o arquivo existe e aponta a candidata');
    assert.equal(fs.existsSync(path.join(v.vm, 'ativa')), false, 'a ativa não é gravada');
  } finally {
    v.limpar();
  }
});

test('R9/A5 ativa sem alvo.conf e reload falhando na reversão: o arquivo fica com o destino da ativa e a saída não tem rm -f', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    fs.rmSync(path.join(v.alvo, 'alvo.conf'));
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_SAUDA_NGINX_FALHA: '1', DUBLE_RELOAD_2_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /\/saude pelo nginx falhou depois do reload; alvo.conf revertido, mas o nginx não recarregou; recupere com:/);
    assert.doesNotMatch(r.stderr, /rm -f/);
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
  } finally {
    v.limpar();
  }
});

test('R9/A5 primeira implantação com cloudflared falhando: a segunda execução não recusa por divergência e sobe verde com azul anterior', () => {
  const v = criarVm();
  try {
    const r1 = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_TUNEL_FALHA: '1' });
    assert.equal(r1.status, 1, r1.stderr);
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    const b = v.promover();
    const r2 = v.rodar(IMPLANTAR, [b]);
    assert.equal(r2.status, 0, r2.stderr);
    assert.doesNotMatch(r2.stderr, /reconcilie/);
    assert.match(r2.stdout, /implantado=[0-9a-f]{12} ativa=verde anterior=azul/);
    assert.equal(v.lerArquivo('ativa').trim(), 'verde');
    assert.equal(v.lerAlvo(), ALVO_VERDE);
  } finally {
    v.limpar();
  }
});

test('R9/A5 remoção do app órfão falha depois da troca: a troca fica (não reverte), e a mensagem diz o que remover à mão', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_ORFAO: '1', DUBLE_ORFAO_RM_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /a troca já foi feita \(ativa=azul\), mas não consegui remover o app órfão orfao1/);
    assert.ok(r.stderr.includes('rm -f orfao1'), r.stderr);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.contarChamadas('nginx -s reload'), 0, 'primeira implantação sobe o nginx por contêiner, sem reload; nada é revertido');
    assert.equal(v.contarChamadas('force-recreate'), 0, 'nada é recriado de volta');
    assert.equal(v.indice('stop '), -1, 'nenhuma pilha parada');
    assert.match(v.registro(), /FALHOU: a troca já foi feita/);
  } finally {
    v.limpar();
  }
});

test('R9/A5 up da candidata falha: a ativa segue, o alvo não muda, o SHA antigo da candidata sai do estado e nada é recarregado', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    fs.writeFileSync(path.join(v.vm, 'pilha-verde.sha'), `${'f'.repeat(40)}\n`);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_APP_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /falhou no passo: app-candidata/);
    assert.match(r.stderr, /a pilha ativa \(azul\) segue servindo/);
    assert.equal(v.contarChamadas('nginx -s reload'), 0);
    assert.equal(v.contarChamadas('force-recreate'), 0);
    assert.equal(v.lerAlvo(), ALVO_AZUL);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.equal(fs.existsSync(path.join(v.vm, 'pilha-verde.sha')), false, 'o SHA antigo da candidata sai antes do up');
    assert.equal(v.indice('stop '), -1);
    assert.match(v.registro(), /FALHOU: falhou no passo: app-candidata/);
  } finally {
    v.limpar();
  }
});

test('R17: publicação lógica na origem recusa a migração antes de qualquer migrate; a consulta que falha ou responde sem número também recusa', () => {
  const v = criarVm();
  try {
    const primeira = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_PUBLICACAO: '1' });
    assert.equal(primeira.status, 1, primeira.stderr);
    assert.match(primeira.stderr, /replicação lógica em curso \(publicação na origem\): migração não roda \(R17\)/);
    assert.equal(v.indice('run --rm migracao'), -1, 'nenhum migrate');
    assert.equal(v.indice('up -d --no-deps app_azul'), -1, 'a candidata não sobe');
    assert.match(v.registro(), /FALHOU: replicação lógica em curso/);

    const falha = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_PUBLICACAO_FALHA: '1' });
    assert.equal(falha.status, 1, falha.stderr);
    assert.match(falha.stderr, /não consegui conferir a replicação lógica em banco \(R17\): migração não roda/);
    assert.equal(v.indice('run --rm migracao'), -1);

    const sem = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_PUBLICACAO: 'sim' });
    assert.equal(sem.status, 1, sem.stderr);
    assert.match(sem.stderr, /saída inesperada ao conferir a replicação lógica \(R17\)/);
    assert.equal(v.indice('run --rm migracao'), -1);
  } finally {
    v.limpar();
  }
});

test('R17: com a ativa de pé e publicação na origem, a segunda implantação recusa a migração e a ativa segue', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_PUBLICACAO: '2' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /replicação lógica em curso/);
    assert.equal(v.indice('run --rm migracao'), -1);
    assert.equal(v.indice('up -d --no-deps app_verde'), -1, 'a candidata não sobe');
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.equal(v.lerAlvo(), ALVO_AZUL);
  } finally {
    v.limpar();
  }
});

test('R17: sem publicação na origem a migração roda normalmente (caminho feliz)', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 0, r.stderr);
    // Sem a consulta no registro (índice -1), a comparação de ordem não pode passar por acaso.
    const publicacao = v.indice('pg_publication');
    assert.ok(publicacao >= 0, 'a consulta de publicação foi feita');
    assert.ok(v.indice('run --rm migracao') > publicacao, 'a conferência vem antes da migração');
    assert.ok(v.indice('run --rm migracao') >= 0);
  } finally {
    v.limpar();
  }
});

test('R17: a consulta de publicação usa o mesmo PHATI_BANCO_NOME (e o mesmo padrão phati) que o compose põe no contêiner do banco', () => {
  // A consulta roda dentro do contêiner do banco (`compor exec`): o nome vem do ambiente desse contêiner, que o compose
  // preenche com `${PHATI_BANCO_NOME:-phati}`. Se um dos dois mudar sozinho, o teste reprova.
  const compose = fs.readFileSync(path.join(PASTA, '..', 'servidor', 'compose.yaml'), 'utf8');
  const inicio = compose.indexOf('\n  banco:');
  assert.ok(inicio >= 0, 'serviço banco no compose');
  // Só o bloco do serviço `banco` (até a próxima chave de serviço, com dois espaços): um serviço posterior com a chave não conta.
  const resto = compose.slice(inicio + 1);
  const proximo = resto.search(/\n  [a-z_][a-z_0-9]*:/);
  const bloco = proximo < 0 ? resto : resto.slice(0, proximo);
  const chave = bloco.match(/PHATI_BANCO_NOME: (.*)/);
  assert.ok(chave, 'PHATI_BANCO_NOME dentro do serviço banco');
  assert.equal(chave[1], '${PHATI_BANCO_NOME:-phati}');
  assert.match(fs.readFileSync(IMPLANTAR, 'utf8'), /-d "\$\{PHATI_BANCO_NOME:-phati\}" -c "SELECT count\(\*\) FROM pg_publication"/);
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
    const b = implantarEPromover(v);
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
    // A autocura só lê o contêiner (exec sh -c, marca sim): o nginx não é recarregado nem recriado.
    assert.equal(v.contarChamadas('nginx -s reload'), 0, 'o nginx não é recarregado');
    assert.equal(v.contarChamadas('force-recreate'), 0, 'o nginx não é recriado');
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

test('X2: migração fora do fluxo: falha depois da migração diz que o esquema já mudou e não manda subir a ativa', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_COMPAT_RC: '3', DUBLE_COMPAT_SAIDA: 'FORA_DO_FLUXO x', PHATI_ACEITO_PARADA: '1', DUBLE_SAUDE_VERDE: 'unhealthy' });
    assert.equal(r.status, 1);
    assert.equal(v.contarChamadas('stop app_azul'), 1);
    assert.match(r.stderr, /o esquema JÁ foi migrado pela migração fora do fluxo/);
    assert.equal(r.stderr.includes('Suba com'), false, r.stderr);
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

// X1 a X6 da revisão da PR #70: cada caso feliz vem com um infeliz (recusa, falha ou ausência).
test('X1: sem ativa e com app legado da 006, migração incompatível sem PHATI_ACEITO_PARADA é recusada antes de migrar', () => {
  const v = criarVm();
  try {
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_ORFAO: '1', DUBLE_COMPAT_RC: '3', DUBLE_COMPAT_SAIDA: 'FORA_DO_FLUXO x' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /migração incompatível por design/);
    assert.equal(v.contarChamadas('comum.compat_migracao'), 1, 'o legado conta como versão anterior servindo: a verificação roda');
    assert.equal(v.indice('run --rm migracao'), -1);
    assert.equal(v.indice('stop orfao1'), -1);
  } finally {
    v.limpar();
  }
});

test('X1: app legado da 006 com migração compatível segue: verifica, migra, sobe a candidata e registra OK', () => {
  const v = criarVm();
  try {
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_ORFAO: '1', DUBLE_COMPAT_RC: '0' });
    assert.equal(r.status, 0, r.stderr);
    assert.ok(v.indice('comum.compat_migracao') < v.indice('run --rm migracao'), 'a verificação vem antes da migração');
    assert.match(v.registro(), / OK origem=nenhuma destino=azul migracao=compativel\n/);
  } finally {
    v.limpar();
  }
});

test('X1: legado da 006 com migração fora do fluxo para o contêiner antes de migrar; falha depois diz que o esquema já mudou', () => {
  const v = criarVm();
  try {
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_ORFAO: '1', DUBLE_COMPAT_RC: '3', DUBLE_COMPAT_SAIDA: 'FORA_DO_FLUXO x', PHATI_ACEITO_PARADA: '1', DUBLE_SAUDE_AZUL: 'unhealthy' });
    assert.equal(r.status, 1, r.stderr);
    assert.equal(v.contarChamadas('stop orfao1'), 1, 'o legado é parado, não o app_azul');
    const ordem = ['stop orfao1', 'run --rm migracao', 'up -d --no-deps app_azul'].map((t) => v.indice(t));
    assert.ok(ordem[0] >= 0 && ordem[0] < ordem[1] && ordem[1] < ordem[2], `ordem: ${ordem}`);
    assert.match(r.stderr, /o esquema JÁ foi migrado/);
    assert.equal(r.stderr.includes('Suba com'), false, r.stderr);
  } finally {
    v.limpar();
  }
});

test('X2: falha em estáticos depois da migração fora do fluxo manda recuperar à mão, não subir a ativa', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_COMPAT_RC: '3', DUBLE_COMPAT_SAIDA: 'FORA_DO_FLUXO x', PHATI_ACEITO_PARADA: '1', DUBLE_ESTATICOS_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.ok(v.indice('run --rm migracao') >= 0, 'a migração rodou antes da falha');
    assert.match(r.stderr, /o esquema JÁ foi migrado/);
    assert.match(r.stderr, /recupere à mão/);
    assert.equal(r.stderr.includes('Suba com'), false, r.stderr);
  } finally {
    v.limpar();
  }
});

test('X3: falha ao gravar ativa no rollback rápido reverte o alvo.conf e avisa, sem deixar alvo e ativa divergentes', () => {
  const v = criarVm();
  const shim = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-falha-'));
  try {
    const mvReal = unix(execFileSync('bash', ['-c', 'command -v mv'], { encoding: 'utf8' }).trim());
    // Dublê de `mv`: falha só ao gravar `ativa`; o resto vai para o `mv` de verdade.
    fs.writeFileSync(path.join(shim, 'mv'), `#!/usr/bin/env bash\nfor arg; do :; done\ncase "$arg" in */ativa) echo "mv: falha simulada" >&2; exit 1 ;; esac\nexec "${mvReal}" "$@"\n`, { mode: 0o755 });
    const a = v.promovido;
    assert.equal(v.rodar(IMPLANTAR, [a]).status, 0);
    const b = v.promover();
    assert.equal(v.rodar(IMPLANTAR, [b]).status, 0);
    v.zerar();
    // Rollback para A: a pilha azul (inativa) está saudável. O alvo vira azul e gravar `ativa` falha.
    // Node procura o `bash` pelo PATH do filho: o PATH original segue depois do dublê, com o separador da plataforma.
    const r = v.rodar(IMPLANTAR, [a], { PATH: [shim, process.env.PATH].join(path.delimiter) });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /falha ao gravar ativa=azul; alvo.conf revertido para app_verde, que segue servindo/);
    assert.equal(v.lerArquivo('ativa').trim(), 'verde');
    assert.match(v.lerAlvo(), /set \$alvo app_verde;/);
    assert.equal(v.contarChamadas('nginx -s reload'), 2, 'recarrega para azul e de volta para verde');
    assert.match(v.registro(), /FALHOU: falha ao gravar ativa=azul/);
  } finally {
    fs.rmSync(shim, { recursive: true, force: true });
    v.limpar();
  }
});

test('X4: backup.sh sem PHATI_ALVO_DIR no ambiente usa o do .env; sem ele, $PHATI_DIR/alvo', () => {
  const doEnv = criarVm();
  const padrao = criarVm({ comEnv: true });
  try {
    fs.appendFileSync(path.join(doEnv.vm, '.env'), 'PHATI_ALVO_DIR=/caminho/do/env\n');
    const r = doEnv.rodar(BACKUP, [], { PHATI_ALVO_DIR: '' });
    assert.equal(r.status, 0, r.stderr);
    assert.ok(doEnv.lerAlvoVars().length > 0, 'o compose foi chamado');
    assert.ok(doEnv.lerAlvoVars().every((x) => x === '/caminho/do/env'), doEnv.lerAlvoVars().join(','));
    const r2 = padrao.rodar(BACKUP, [], { PHATI_ALVO_DIR: '' });
    assert.equal(r2.status, 0, r2.stderr);
    assert.ok(padrao.lerAlvoVars().every((x) => x === unix(path.join(padrao.vm, 'alvo'))), padrao.lerAlvoVars().join(','));
  } finally {
    doEnv.limpar();
    padrao.limpar();
  }
});

test('X4: restaurar.sh sem PHATI_ALVO_DIR usa $PHATI_DIR/alvo e a instrução de recuperação traz a variável', () => {
  const v = criarVm();
  try {
    const pasta = path.join(v.vm, 'backups');
    fs.mkdirSync(pasta);
    const dump = path.join(pasta, 'phati-1.dump');
    fs.writeFileSync(dump, 'dados');
    const falha = v.rodar(RESTAURAR, [unix(dump), 'RESTAURAR'], { PHATI_ALVO_DIR: '', DUBLE_APP_FALHA: '1' });
    assert.equal(falha.status, 1);
    assert.ok(falha.stderr.includes(`PHATI_ALVO_DIR=${unix(path.join(v.vm, 'alvo'))} COMPOSE_PROJECT_NAME=phati docker compose`), falha.stderr);
    assert.ok(v.lerAlvoVars().every((x) => x === unix(path.join(v.vm, 'alvo'))), v.lerAlvoVars().join(','));
  } finally {
    v.limpar();
  }
});

test('X4: restauração confirmada tira pilha-<inativa>.sha; restauração que falha deixa o SHA como estava', () => {
  const v = criarVm();
  try {
    const pasta = path.join(v.vm, 'backups');
    fs.mkdirSync(pasta);
    const dump = path.join(pasta, 'phati-1.dump');
    fs.writeFileSync(dump, 'dados');
    // Sem `ativa`, a ativa é azul e a inativa é verde.
    fs.writeFileSync(path.join(v.vm, 'pilha-verde.sha'), `${'a'.repeat(40)}\n`);
    const falha = v.rodar(RESTAURAR, [unix(dump), 'RESTAURAR'], { DUBLE_RESTAURA_FALHA: '1' });
    assert.equal(falha.status, 1);
    assert.equal(fs.existsSync(path.join(v.vm, 'pilha-verde.sha')), true, 'sem restauração, o SHA da inativa fica');
    const ok = v.rodar(RESTAURAR, [unix(dump), 'RESTAURAR']);
    assert.equal(ok.status, 0, ok.stderr);
    assert.equal(fs.existsSync(path.join(v.vm, 'pilha-verde.sha')), false, 'a inativa perde o SHA: o banco mudou');
  } finally {
    v.limpar();
  }
});

test('X6: pgb1 saudável e pgb2 indisponível falha antes de migrar e de trocar o nginx', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_SAUDE_PGB2: 'unhealthy' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /pgb2 não ficou saudável \(estado: unhealthy\)/);
    assert.equal(r.stderr.includes('pgb1 não ficou'), false, r.stderr);
    assert.equal(v.indice('run --rm migracao'), -1);
    assert.equal(v.indice('up -d --no-deps app_azul'), -1);
    assert.equal(v.indice('nginx -t'), -1);
    assert.equal(v.indice('nginx -s reload'), -1);
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
    const b = implantarEPromover(v);
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

// Bug da VM (spec 009 T3.4): SHA ancestral de main sem `servidor/nginx` fez o checkout apagar o diretório que o nginx
// monta. A pré-checagem recusa antes do checkout; a autocura recria o nginx quando o `default.conf` montado sumiu.
test('SHA sem a infraestrutura de implantação é recusado antes do checkout: clone intacto, nada de Docker, registro FALHOU', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.semInfra]);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /o SHA não traz a infraestrutura de implantação blue-green: servidor\/compose\.implantacao\.yaml/);
    assert.equal(git(v.repo, 'rev-parse', 'HEAD'), v.promovido, 'o clone não muda de SHA');
    assert.ok(fs.existsSync(path.join(v.repo, 'servidor', 'nginx', 'default.conf')), 'o servidor/nginx segue no clone');
    assert.deepEqual(v.lerChamadas(), [], 'nada de Docker antes da recusa');
    assert.match(v.registro(), /FALHOU: o SHA não traz a infraestrutura/);
  } finally {
    v.limpar();
  }
});

test('autocura: nginx de pé sem o default.conf montado é recriado (bind obsoleto) e não só recarregado', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_CONF_AUSENTE: '1' });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contarChamadas('up -d --no-deps --force-recreate nginx'), 1, 'recriado uma vez');
    assert.equal(v.contarChamadas('nginx -s reload'), 1, 'a troca recarrega o alvo novo, depois da recriação feita antes do build');
    assert.equal(v.contarChamadas('/etc/nginx/conf.d/default.conf'), 1, 'o caminho exato do default.conf foi verificado');
    assert.match(v.registro(), /nginx-recriado=bind-obsoleto/);
  } finally {
    v.limpar();
  }
});

test('autocura: com o default.conf montado o nginx só recarrega, sem recriar e sem registrar', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b]);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contarChamadas('force-recreate'), 0);
    assert.equal(v.contarChamadas('nginx -s reload'), 1);
    assert.equal(v.contarChamadas('/etc/nginx/conf.d/default.conf'), 1, 'o caminho exato do default.conf foi verificado');
    assert.doesNotMatch(v.registro(), /nginx-recriado/);
  } finally {
    v.limpar();
  }
});

test('autocura: se a recriação do nginx falha, a implantação falha, registra FALHOU e não diz que recriou', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_CONF_AUSENTE: '1', DUBLE_RECRIAR_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(v.registro(), /FALHOU/);
    assert.doesNotMatch(v.registro(), /nginx-recriado/);
  } finally {
    v.limpar();
  }
});

// Recriação do nginx parado antes do build: o status, uma recriação e o registro, na ordem que o teste de autocura exige.
// Pasta `backups/` com um dump falso (o restaurar só precisa do nome e do arquivo); devolve o caminho do dump.
function criarDump(v) {
  const pasta = path.join(v.vm, 'backups');
  fs.mkdirSync(pasta);
  const dump = unix(path.join(pasta, 'phati-1.dump'));
  fs.writeFileSync(dump, 'dados');
  return dump;
}

// Recusa sem tocar o Docker: sai com 1, cita o trecho no stderr e não tem chamada ao Docker.
function afirmarRecusa(v, r, trecho) {
  assert.equal(r.status, 1);
  assert.match(r.stderr, trecho);
  assert.deepEqual(v.lerChamadas(), []);
}

function afirmarRecriadoAntesDoBuild(v, r) {
  assert.equal(r.status, 0, r.stderr);
  assert.equal(v.contarChamadas('force-recreate nginx'), 1, 'recriado uma vez');
  assert.ok(v.indice('force-recreate nginx') < v.indice(' build'), 'antes do build');
  assert.match(v.registro(), /nginx-recriado=parado/);
}

// Primeira implantação, promoção de um commit novo e chamadas zeradas: ponto de partida dos testes de autocura do nginx.
function implantarEPromover(v) {
  assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
  const b = v.promover();
  v.zerar();
  return b;
}

// Promove a main um commit que altera a infraestrutura (a função recebe o caminho do clone de trabalho) e devolve o SHA.
function promoverComAlteracao(v, alterar) {
  git(v.trabalho, 'switch', '-q', 'main');
  alterar(v.trabalho);
  git(v.trabalho, 'add', '-A');
  git(v.trabalho, 'commit', '-q', '-m', 'infraestrutura alterada');
  git(v.trabalho, 'push', '-q', 'origin', 'main');
  return git(v.trabalho, 'rev-parse', 'HEAD');
}

test('autocura: a config candidata é validada antes de recriar o nginx de pé; reprovada, o nginx de pé não é tocado', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_CONF_AUSENTE: '1', DUBLE_NGINX_TESTE_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.equal(v.contarChamadas('force-recreate'), 0, 'não recriou o nginx de pé');
    assert.equal(v.contarChamadas('nginx -s reload'), 0, 'nada recarregado');
    assert.match(r.stderr, /nginx de pé não pôde ser recriado com a config do clone/);
    assert.match(v.registro(), /FALHOU/);
    assert.doesNotMatch(v.registro(), /nginx-recriado/);
  } finally {
    v.limpar();
  }
});

test('autocura: candidata reprovada depois da recriação reverte o alvo.conf e não recarrega (o nginx segue com o alvo anterior)', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const antes = v.lerAlvo();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_CONF_AUSENTE: '1', DUBLE_NGINX_CANDIDATA_INVALIDA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.equal(v.contarChamadas('nginx -s reload'), 0, 'nada recarregado: o nginx recriado na autocura já lê o alvo anterior');
    assert.equal(v.lerAlvo(), antes, 'alvo.conf voltou ao da ativa');
    assert.match(v.registro(), /nginx-recriado=bind-obsoleto/);
    assert.match(v.registro(), /FALHOU/);
  } finally {
    v.limpar();
  }
});

test('autocura: erro do exec ao checar o default.conf não é lido como arquivo ausente: nada é recriado e a causa vai ao registro', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_EXEC_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.equal(v.contarChamadas('force-recreate'), 0, 'erro de exec não recria o nginx');
    assert.match(r.stderr, /não consegui verificar \/etc\/nginx\/conf\.d\/default\.conf/);
    assert.match(v.registro(), /nginx-verificacao-falhou/);
    assert.doesNotMatch(v.registro(), /nginx-recriado/);
  } finally {
    v.limpar();
  }
});

test('autocura: inspect que falha não é lido como nginx parado: nada é validado nem recriado e a implantação falha com a causa', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_INSPECT_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /não consegui verificar o estado do nginx/);
    assert.equal(v.contarChamadas('nginx -t'), 0, 'nenhuma validação com o estado desconhecido');
    assert.equal(v.contarChamadas('force-recreate'), 0, 'não recriou o nginx');
    assert.match(v.registro(), /nginx-estado-falhou/);
    assert.match(v.registro(), /FALHOU/);
    assert.doesNotMatch(v.registro(), /nginx-recriado/);
  } finally {
    v.limpar();
  }
});

test('autocura: saída do inspect fora de true e false é erro, não "parado": nada é recriado', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_RUNNING_SAIDA: 'talvez' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /não consegui verificar o estado do nginx/);
    assert.equal(v.contarChamadas('force-recreate'), 0, 'não recriou o nginx');
    assert.match(v.registro(), /nginx-estado-falhou/);
    assert.doesNotMatch(v.registro(), /nginx-recriado/);
  } finally {
    v.limpar();
  }
});

test('autocura: legado da 006 (sem ativa e sem alvo.conf) com nginx parado não valida nem recria: a implantação segue até a troca', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    fs.rmSync(path.join(v.vm, 'ativa'));
    fs.rmSync(path.join(v.alvo, 'alvo.conf'));
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_NGINX_PARADO: '1' });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contarChamadas('force-recreate'), 0, 'nada recriado antes da troca');
    assert.equal(v.contarChamadas('nginx -t'), 1, 'só a validação da troca, não a da autocura');
    assert.match(v.lerAlvo(), /set \$alvo app_azul;/, 'a troca gravou o alvo.conf');
    assert.match(v.registro(), /OK/);
    assert.doesNotMatch(v.registro(), /nginx-recriado/);
  } finally {
    v.limpar();
  }
});

test('autocura: sem ativa mas com alvo.conf, nginx parado é recriado antes do build (recuperação antecipada preservada)', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    fs.rmSync(path.join(v.vm, 'ativa'));
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_NGINX_PARADO: '1' });
    afirmarRecriadoAntesDoBuild(v, r);
  } finally {
    v.limpar();
  }
});

test('SHA com a infraestrutura como link simbólico ou diretório é recusado antes do checkout', () => {
  const v = criarVm();
  const compose = (t) => path.join(t, 'servidor', 'compose.implantacao.yaml');
  try {
    const link = promoverComAlteracao(v, (t) => {
      fs.rmSync(compose(t));
      fs.symlinkSync('arquivo', compose(t));
    });
    const r = v.rodar(IMPLANTAR, [link]);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /infraestrutura de implantação blue-green: servidor\/compose\.implantacao\.yaml/);
    const diretorio = promoverComAlteracao(v, (t) => {
      fs.rmSync(compose(t));
      fs.mkdirSync(compose(t));
      fs.writeFileSync(path.join(compose(t), 'conteudo'), 'x\n');
    });
    const r2 = v.rodar(IMPLANTAR, [diretorio]);
    assert.equal(r2.status, 1);
    assert.match(r2.stderr, /infraestrutura de implantação blue-green: servidor\/compose\.implantacao\.yaml/);
    assert.equal(git(v.repo, 'rev-parse', 'HEAD'), v.promovido, 'o clone não muda de SHA');
    assert.deepEqual(v.lerChamadas(), [], 'nada de Docker antes da recusa');
  } finally {
    v.limpar();
  }
});

test('pré-checagem: cada arquivo de infraestrutura faltando recusa sozinho, citando o que falta', () => {
  const semDefault = criarVm();
  try {
    const sha = promoverComAlteracao(semDefault, (t) => fs.rmSync(path.join(t, 'servidor', 'nginx', 'default.conf')));
    const r = semDefault.rodar(IMPLANTAR, [sha]);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /servidor\/nginx\/default\.conf/);
    assert.doesNotMatch(r.stderr, /compose\.implantacao/);
    assert.deepEqual(semDefault.lerChamadas(), []);
  } finally {
    semDefault.limpar();
  }
  const semCompose = criarVm();
  try {
    const sha = promoverComAlteracao(semCompose, (t) => fs.rmSync(path.join(t, 'servidor', 'compose.implantacao.yaml')));
    const r = semCompose.rodar(IMPLANTAR, [sha]);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /servidor\/compose\.implantacao\.yaml/);
    assert.doesNotMatch(r.stderr, /default\.conf/);
    assert.deepEqual(semCompose.lerChamadas(), []);
  } finally {
    semCompose.limpar();
  }
});

test('autocura: nginx existente parado é recriado antes do build, com o alvo atual', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_NGINX_PARADO: '1' });
    afirmarRecriadoAntesDoBuild(v, r);
  } finally {
    v.limpar();
  }
});

test('autocura: sem contêiner nginx (primeira implantação de verdade) não consulta nem recria o nginx antes do build', () => {
  const v = criarVm();
  try {
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_NGINX_AUSENTE: '1' });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contarChamadas('force-recreate'), 0);
    assert.equal(v.contarChamadas('exec -T nginx sh -c'), 0, 'nenhuma verificação de default.conf sem contêiner');
    assert.doesNotMatch(v.registro(), /nginx-recriado/);
  } finally {
    v.limpar();
  }
});

test('autocura: candidata que falha no build não impede a recriação do nginx com bind obsoleto', () => {
  const v = criarVm();
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_CONF_AUSENTE: '1', DUBLE_BUILD_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.equal(v.contarChamadas('force-recreate nginx'), 1, 'recriado antes do build que falhou');
    assert.ok(v.indice('force-recreate nginx') < v.indice(' build'));
    assert.match(v.registro(), /nginx-recriado=bind-obsoleto/);
    assert.match(v.registro(), /FALHOU/);
  } finally {
    v.limpar();
  }
});

test('erro depois do checkout não devolve o clone a SHA sem infraestrutura: HEAD fica no SHA novo e o default.conf segue', () => {
  const v = criarVm();
  try {
    git(v.repo, 'checkout', '-q', '--detach', v.semInfra);
    const r = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_NGINX_TESTE_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.equal(git(v.repo, 'rev-parse', 'HEAD'), v.promovido, 'o clone fica no SHA que passou na pré-checagem');
    assert.ok(fs.existsSync(path.join(v.repo, 'servidor', 'nginx', 'default.conf')), 'o default.conf segue no clone');
    assert.match(v.registro(), /repo-mantido=[0-9a-f]{12}: anterior sem infraestrutura blue-green/);
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

// ---- E5: com banco-logico (modo lógico concluído) o override wal_level entra em todo compose; sem ele, não entra; arquivo ausente no clone recusa ----
const OVERRIDE_LOGICA = 'compose.troca-logica.yaml';
const comOverride = (v) => fs.writeFileSync(path.join(v.repo, 'servidor', OVERRIDE_LOGICA), 'services: {}\n');
const marcarLogico = (v) => fs.writeFileSync(path.join(v.vm, 'banco-logico'), 'logica\n');
const chamadasDeCompose = (v) => v.lerChamadas().filter((linha) => linha.includes('compose.implantacao.yaml'));

test('E5: backup.sh com banco-logico soma o override no compose; sem banco-logico não soma', () => {
  const v = criarVm();
  try {
    comOverride(v);
    marcarLogico(v);
    const r = v.rodar(BACKUP, []);
    assert.equal(r.status, 0, r.stderr);
    assert.ok(chamadasDeCompose(v).length >= 1, 'backup não chamou o compose');
    assert.ok(chamadasDeCompose(v).every((linha) => linha.includes(OVERRIDE_LOGICA)), 'override ausente numa chamada com banco-logico');
  } finally {
    v.limpar();
  }
  const sem = criarVm();
  try {
    comOverride(sem);
    const r = sem.rodar(BACKUP, []);
    assert.equal(r.status, 0, r.stderr);
    assert.ok(chamadasDeCompose(sem).length >= 1);
    assert.ok(chamadasDeCompose(sem).every((linha) => !linha.includes(OVERRIDE_LOGICA)), 'override somou sem banco-logico');
  } finally {
    sem.limpar();
  }
});

test('E5: backup.sh com banco-logico e sem o override no clone recusa antes do pg_dump', () => {
  const v = criarVm();
  try {
    marcarLogico(v);
    const r = v.rodar(BACKUP, []);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /banco-logico existe, mas .*compose\.troca-logica\.yaml não está no clone/);
    assert.equal(v.contarChamadas('pg_dump'), 0, 'pg_dump rodou sem o override');
  } finally {
    v.limpar();
  }
});

test('E5: restaurar.sh com banco-logico soma o override em todo compose', () => {
  const v = criarVm();
  try {
    comOverride(v);
    marcarLogico(v);
    const dump = path.join(v.vm, 'backups', 'phati-teste.dump');
    fs.mkdirSync(path.dirname(dump), { recursive: true });
    fs.writeFileSync(dump, 'dados\n');
    const r = v.rodar(RESTAURAR, [dump, 'RESTAURAR']);
    assert.equal(r.status, 0, r.stderr);
    assert.ok(chamadasDeCompose(v).length >= 1, 'restaurar não chamou o compose');
    assert.ok(chamadasDeCompose(v).every((linha) => linha.includes(OVERRIDE_LOGICA)), 'override ausente numa chamada com banco-logico');
  } finally {
    v.limpar();
  }
});

test('E5: implantar com banco-logico soma o override em todo compose, inclusive o up do banco', () => {
  const v = criarVm();
  try {
    comOverride(v);
    marcarLogico(v);
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 0, r.stderr);
    assert.ok(chamadasDeCompose(v).length >= 1);
    assert.ok(chamadasDeCompose(v).every((linha) => linha.includes(OVERRIDE_LOGICA)), 'override ausente numa chamada com banco-logico');
    assert.ok(v.lerChamadas().some((linha) => linha.includes('up -d --wait banco') && linha.includes(OVERRIDE_LOGICA)), 'up do banco sem o override');
  } finally {
    v.limpar();
  }
});

test('E5: implantar com banco-logico sem o override no clone recusa antes de qualquer compose', () => {
  const v = criarVm();
  try {
    marcarLogico(v);
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /banco-logico existe, mas .*compose\.troca-logica\.yaml não está no clone/);
    assert.equal(chamadasDeCompose(v).length, 0, 'compose chamado sem o override');
  } finally {
    v.limpar();
  }
});

test('E5: implantar sem banco-logico não soma o override', () => {
  const v = criarVm();
  try {
    comOverride(v);
    const r = v.rodar(IMPLANTAR, [v.promovido]);
    assert.equal(r.status, 0, r.stderr);
    assert.ok(chamadasDeCompose(v).length >= 1);
    assert.ok(chamadasDeCompose(v).every((linha) => !linha.includes(OVERRIDE_LOGICA)), 'override somou sem banco-logico');
  } finally {
    v.limpar();
  }
});

// ---- Lote 1 (review da PR #81): banco-logico sem o override devolve o clone ao SHA anterior (R1); destino com aspas ou
// comentário no `.env` é normalizado antes da comparação com banco_novo (R2) ----
test('E5: implantar com banco-logico sem o override devolve o clone ao SHA anterior, em vez de deixá-lo no SHA recusado', () => {
  const v = criarVm();
  try {
    marcarLogico(v);
    // `semBancoNovo` (commit "dois") não traz o override: o checkout vai a ele e a checagem recusa depois.
    const r = v.rodar(IMPLANTAR, [v.semBancoNovo]);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /banco-logico existe, mas .*compose\.troca-logica\.yaml não está no clone/);
    assert.equal(git(v.repo, 'rev-parse', 'HEAD'), v.promovido, 'clone ficou no SHA recusado');
    assert.match(v.registro(), /repo-restaurado=/);
    assert.equal(chamadasDeCompose(v).length, 0, 'compose chamado sem o override');
  } finally {
    v.limpar();
  }
});

test('R2: destino com aspas ou comentário no .env vale banco_novo: implantar, backup e restaurar recusam com banco-ativo=banco', () => {
  for (const valor of ['"banco_novo"', "'banco_novo'", 'banco_novo # x']) {
    const v = criarVm();
    try {
      apontarDestino(v, valor);
      afirmarRecusa(v, v.rodar(IMPLANTAR, [v.promovido]), MENSAGEM_DIVERGENTE);
      afirmarRecusa(v, v.rodar(BACKUP, ['ab']), MENSAGEM_DIVERGENTE);
      afirmarRecusa(v, v.rodar(RESTAURAR, [criarDump(v), 'RESTAURAR']), MENSAGEM_DIVERGENTE);
    } finally {
      v.limpar();
    }
  }
});

test('R2: destino banco com aspas ou comentário no .env segue nos três scripts (sem recusa)', () => {
  for (const valor of ['"banco"', "'banco' # x"]) {
    const v = criarVm();
    try {
      apontarDestino(v, valor);
      // Restaurar primeiro: ele cria a pasta de backups que o backup.sh usa depois.
      const re = v.rodar(RESTAURAR, [criarDump(v), 'RESTAURAR']);
      assert.equal(re.status, 0, re.stderr);
      const b = v.rodar(BACKUP, ['ab']);
      assert.equal(b.status, 0, b.stderr);
      const i = v.rodar(IMPLANTAR, [v.promovido], { DUBLE_BANCO: '0', DUBLE_VOLUME: '1' });
      assert.equal(i.status, 0, i.stderr);
      assert.doesNotMatch(i.stderr + b.stderr + re.stderr, MENSAGEM_DIVERGENTE);
    } finally {
      v.limpar();
    }
  }
});

// Revisão do PR 91 (CodeRabbit e Codex): ativa x alvo.conf, escape do comando impresso e migração fora do fluxo na falha pós-troca.

// Dublê de `mv` com contador: falha a partir da (limite+1)ª vez que o destino casa `padrao`. Deixa a troca gravar o alvo.conf
// e falha só a reversão (a gravação do alvo.conf é `mv` do bash, não o Docker).
function mvQueFalhaDepois(padrao, limite) {
  const shim = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-falha-'));
  const mvReal = unix(execFileSync('bash', ['-c', 'command -v mv'], { encoding: 'utf8' }).trim());
  const contador = unix(path.join(shim, 'contador'));
  fs.writeFileSync(path.join(shim, 'mv'), `#!/usr/bin/env bash\nfor arg; do :; done\ncase "$arg" in ${padrao}) n=$(( $(cat "${contador}" 2>/dev/null || echo 0) + 1 )); echo "$n" > "${contador}"; [[ "$n" -le ${limite} ]] || { echo "mv: falha simulada" >&2; exit 1; } ;; esac\nexec "${mvReal}" "$@"\n`, { mode: 0o755 });
  return shim;
}

test('ativa x alvo.conf: alvo.conf servindo outra pilha recusa antes de qualquer chamada ao Docker, sem aviso de "segue servindo"', () => {
  const v = criarVm();
  try {
    implantarEPromover(v);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    fs.writeFileSync(path.join(v.alvo, 'alvo.conf'), ALVO_VERDE);
    const b2 = v.promover();
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b2]);
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /ativa=azul mas alvo\.conf serve verde: reconcilie à mão antes de implantar/);
    assert.doesNotMatch(r.stderr, /segue servindo/, 'o aviso de pilha que segue servindo seria enganoso');
    assert.deepEqual(v.lerChamadas(), [], 'nenhuma chamada ao Docker');
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.equal(v.lerAlvo(), ALVO_VERDE);
  } finally {
    v.limpar();
  }
});

test('ativa x alvo.conf: alvo.conf consistente com a ativa segue normalmente (caminho feliz)', () => {
  const v = criarVm();
  try {
    implantarEPromover(v);
    const b2 = v.promover();
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b2]);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.lerArquivo('ativa').trim(), 'verde');
  } finally {
    v.limpar();
  }
});

test('ativa x alvo.conf: falha ao gravar o alvo.conf na reversão pós-troca deixa divergência, e a próxima execução recusa', () => {
  const v = criarVm();
  // O 1º mv para alvo.conf é a troca (passa); o 2º é a reversão, que falha.
  const shim = mvQueFalhaDepois('*/alvo.conf', 1);
  try {
    implantarEPromover(v);
    const b2 = v.promover();
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b2], { ...comPath(shim), DUBLE_TUNEL_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, /falha ao gravar o alvo.conf anterior/);
    assert.equal(v.lerArquivo('ativa').trim(), 'azul');
    assert.equal(v.lerAlvo(), ALVO_VERDE, 'a reversão não gravou: o alvo segue na candidata');
    const b3 = v.promover();
    v.zerar();
    const segunda = v.rodar(IMPLANTAR, [b3]);
    assert.equal(segunda.status, 1, segunda.stderr);
    assert.match(segunda.stderr, /ativa=azul mas alvo\.conf serve verde: reconcilie à mão/);
    assert.deepEqual(v.lerChamadas(), [], 'a segunda execução não toca no Docker nem sobrescreve a pilha que serve');
  } finally {
    fs.rmSync(shim, { recursive: true, force: true });
    v.limpar();
  }
});

// Escape (CodeRabbit): o comando impresso para o operador, colado num `bash -c`, não divide um caminho com espaço.
// O docker do teste é um dublê que grava cada argumento numa linha, então "dividido" aparece como argumento separado.
function dublePegaArgumentos() {
  const shim = fs.mkdtempSync(path.join(os.tmpdir(), 'docker-argv-'));
  fs.writeFileSync(path.join(shim, 'docker'), '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$ARGV_DOCKER"\n', { mode: 0o755 });
  return shim;
}

test('escape: o comando do túnel impresso com PHATI_DIR com espaço, colado em bash -c, chega ao docker com o caminho inteiro', () => {
  const v = criarVm({ nomeVm: 'vm com espaco' });
  const shim = dublePegaArgumentos();
  const argv = path.join(shim, 'argv.txt');
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_TUNEL_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    const cmd = /suba à mão com: (.+?); alvo\.conf revertido/.exec(r.stderr);
    assert.ok(cmd, r.stderr);
    const colado = spawnSync('bash', ['-c', cmd[1]], { env: { ...process.env, PATH: [shim, process.env.PATH].join(path.delimiter), ARGV_DOCKER: unix(argv) }, encoding: 'utf8' });
    assert.equal(colado.status, 0, colado.stderr);
    const args = lerLinhas(argv);
    assert.ok(args.includes(`${unix(v.vm)}/.env`), `--env-file inteiro: ${args}`);
    assert.ok(args.includes(`${unix(v.vm)}/repo/servidor/compose.yaml`), `-f inteiro: ${args}`);
    assert.ok(args.includes('cloudflared'), `serviço: ${args}`);
  } finally {
    fs.rmSync(shim, { recursive: true, force: true });
    v.limpar();
  }
});

test('escape: o comando de recuperação impresso com PHATI_DIR com espaço, colado em bash -c, grava o alvo e chega ao docker inteiro', () => {
  const v = criarVm({ nomeVm: 'vm com espaco' });
  const shim = dublePegaArgumentos();
  const argv = path.join(shim, 'argv.txt');
  try {
    const b = implantarEPromover(v);
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_TUNEL_FALHA: '1', DUBLE_RELOAD_2_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    const cmd = /recupere com: (.+)$/m.exec(r.stderr);
    assert.ok(cmd, r.stderr);
    // Alvo fora da ativa de propósito: o primeiro passo do comando precisa gravar o alvo da ativa (azul) para o teste provar algo.
    fs.writeFileSync(path.join(v.alvo, 'alvo.conf'), ALVO_VERDE);
    const colado = spawnSync('bash', ['-c', cmd[1]], { env: { ...process.env, PATH: [shim, process.env.PATH].join(path.delimiter), ARGV_DOCKER: unix(argv) }, encoding: 'utf8' });
    assert.equal(colado.status, 0, colado.stderr);
    assert.equal(v.lerAlvo(), ALVO_AZUL, 'o primeiro passo do comando grava o alvo da ativa');
    const args = lerLinhas(argv);
    assert.ok(args.includes(`${unix(v.vm)}/repo/servidor/compose.yaml`), `-f inteiro: ${args}`);
    assert.ok(args.includes('nginx'), `serviço: ${args}`);
  } finally {
    fs.rmSync(shim, { recursive: true, force: true });
    v.limpar();
  }
});

// X2 + CR (Codex P1): migração fora do fluxo parou a ativa e o esquema já mudou. Falha de nginx ou de túnel depois da troca
// não reverte à versão parada: a candidata segue no alvo.conf e a mensagem diz o comando para subir o serviço à mão.
test('migração fora do fluxo + cloudflared falha depois da troca: não reverte à ativa parada, mantém a candidata e dá o comando à mão', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_COMPAT_RC: '3', DUBLE_COMPAT_SAIDA: 'FORA_DO_FLUXO x', PHATI_ACEITO_PARADA: '1', DUBLE_TUNEL_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    const subir = `PHATI_ALVO_DIR=${unix(v.alvo)} COMPOSE_PROJECT_NAME=phati docker compose --env-file ${unix(v.vm)}/.env -f ${unix(v.vm)}/repo/servidor/compose.yaml -f ${unix(v.vm)}/repo/servidor/compose.implantacao.yaml up -d --no-deps cloudflared`;
    assert.ok(r.stderr.includes(`cloudflared falhou depois da troca; esquema já migrado: não volto à versão anterior (ver AVISO); a candidata app_verde segue no alvo.conf. Suba cloudflared à mão com: ${subir}`), r.stderr);
    assert.equal(v.lerAlvo(), ALVO_VERDE, 'a candidata segue no alvo.conf');
    assert.equal(v.lerArquivo('ativa').trim(), 'verde');
    assert.equal(v.contarChamadas('nginx -s reload'), 1, 'só o reload da troca: nenhuma reversão recarrega o alvo anterior');
    assert.match(v.registro(), /FALHOU: cloudflared falhou depois da troca/);
  } finally {
    v.limpar();
  }
});

test('migração fora do fluxo + nginx falha depois da troca: não reverte, mantém a candidata e dá o comando do nginx à mão', () => {
  const v = criarVm();
  try {
    assert.equal(v.rodar(IMPLANTAR, [v.promovido]).status, 0);
    const b = promoverCom(v, { [ARQ_MIGRACAO]: MIGRACAO_TEXTO });
    v.zerar();
    const r = v.rodar(IMPLANTAR, [b], { DUBLE_COMPAT_RC: '3', DUBLE_COMPAT_SAIDA: 'FORA_DO_FLUXO x', PHATI_ACEITO_PARADA: '1', DUBLE_NGINX_UP_FALHA: '1' });
    assert.equal(r.status, 1, r.stderr);
    const subir = `PHATI_ALVO_DIR=${unix(v.alvo)} COMPOSE_PROJECT_NAME=phati docker compose --env-file ${unix(v.vm)}/.env -f ${unix(v.vm)}/repo/servidor/compose.yaml -f ${unix(v.vm)}/repo/servidor/compose.implantacao.yaml up -d --no-deps nginx`;
    assert.ok(r.stderr.includes(`nginx falhou depois da troca; esquema já migrado: não volto à versão anterior (ver AVISO); a candidata app_verde segue no alvo.conf. Suba nginx à mão com: ${subir}`), r.stderr);
    assert.equal(v.lerAlvo(), ALVO_VERDE);
    assert.equal(v.lerArquivo('ativa').trim(), 'verde');
    assert.equal(v.contarChamadas('nginx -s reload'), 1, 'só o reload da troca');
    assert.equal(v.indice('up -d --no-deps cloudflared'), -1, 'o túnel não é tocado quando o nginx falha');
  } finally {
    v.limpar();
  }
});
