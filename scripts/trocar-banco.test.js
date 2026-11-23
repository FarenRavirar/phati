'use strict';
// Suíte do `trocar-banco.sh` (spec 009 R15, R17, R18, R8): `preparar` e `trocar`.
// Roda com: node --test scripts/
// O Docker e o flock são dublês que só anotam as chamadas; o que se prova aqui é a ordem dos passos, o RESUME garantido
// em falha, o host restaurado antes do RESUME, a assinatura removida em falha e o segredo fora de linha de comando, saída
// e registro. O SQL em si (publicação, setval, lista de tabelas) não roda aqui: o dublê só responde por marcador; o ensaio
// real (spike, /tmp/claude-1001/.../scratchpad/spike) é que mediu o mecanismo.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const PASTA = __dirname;
const TROCAR = path.join(PASTA, 'trocar-banco.sh');
const unix = (caminho) => caminho.replace(/\\/g, '/');
// Valor marcador da senha do `replicador`: nunca pode aparecer em saída, registro ou argumento de chamada (spec 009, A7).
const SEGREDO = 'valor-secreto-9f3a';
// Verificador SCRAM sintético da origem (o dublê o devolve pelo psql da origem): nunca pode aparecer fora do pipe.
const VERIFICADOR = 'SCRAM-SHA-256$4096:marcador-salt$marcador-chave';
// Padrão de restauração do host (o `sed` que volta `banco_novo` para `banco`).
const RESTAURA = 's/host=banco_novo /host=banco /';
const DIREITO = 's/host=banco /host=banco_novo /';

// Corpo do `docker` de mentira. Responde por marcador na linha de comando e por tag do SQL que chega por stdin (`-f -`).
// Cada chamada vai ao `CHAMADAS`; SQL por stdin leva `#sql:<tag>`. `DUBLE_FALHA_UMA` falha uma vez (texto na linha de
// comando); `DUBLE_FALHA_SQL` falha toda vez que a tag aparecer. O `\${...}` é escapado porque o corpo é template literal.
const CORPO_DUBLE = `#!/usr/bin/env bash
args="$*"
tag=""
ent=""
if [[ "$args" == *"-f -"* ]]; then
  ent="$(cat)"
  case "$ent" in
    *"CREATE PUBLICATION"*) tag=publicacao ;;
    *"CREATE SUBSCRIPTION"*) tag=assinatura ;;
    *"DROP SUBSCRIPTION"*) tag=limpa ;;
    *"DROP PUBLICATION"*) tag=despublica ;;
    *"DISABLE"*) tag=desabilita ;;
    *"pg_sequences"*) tag=sequencias ;;
    *"setval"*) tag=setval ;;
    *"sha256"*) tag=hash ;;
    *"format('ALTER ROLE"*) tag=leitura-verificador ;;
    *"ALTER ROLE"*) tag=verificador ;;
    *) tag=esquema ;;
  esac
  echo "$args #sql:$tag" >> "$CHAMADAS"
else
  echo "$args" >> "$CHAMADAS"
fi
if [[ -n "\${DUBLE_FALHA_UMA:-}" && "$args" == *"$DUBLE_FALHA_UMA"* && ! -e "$VM/.falhou-uma" ]]; then
  touch "$VM/.falhou-uma"
  exit 1
fi
if [[ -n "$tag" && "\${DUBLE_FALHA_SQL:-}" == "$tag" ]]; then
  echo "ERROR: falha simulada em $tag com senha $PHATI_BANCO_REPLICADOR_SENHA" >&2
  exit 1
fi
if [[ "$tag" == sequencias ]]; then
  echo "SELECT setval('public.fazenda_id_seq', 1001, true);"
fi
# Hash do verificador: origem sempre "h-igual"; destino "h-igual" salvo DUBLE_HASH_NOVO (salt diferente).
if [[ "$tag" == hash ]]; then
  if [[ "$args" == *"exec -T banco_novo"* ]]; then echo "\${DUBLE_HASH_NOVO:-h-igual}"; else echo "h-igual"; fi
fi
# Verificador SCRAM da origem: vai só ao pipe (stdout do psql da origem), que chega ao psql do destino por stdin.
if [[ "$tag" == leitura-verificador && "$args" == *"exec -T banco sh"* ]]; then
  echo "ALTER ROLE app PASSWORD 'SCRAM-SHA-256\$4096:marcador-salt\$marcador-chave';"
fi
case "$args" in
  *"-e PHATI_BANCO_REPLICADOR_SENHA"*) if [[ "\${DUBLE_SQL_FALHA:-0}" == 1 ]]; then echo "ERROR: CREATE ROLE replicador PASSWORD $PHATI_BANCO_REPLICADOR_SENHA" >&2; exit 1; fi ;;
  *"ps -q banco_novo"*) [[ "\${DUBLE_NOVO_AUSENTE:-0}" == 1 ]] || echo novo1 ;;
  *"ps -q banco"*) [[ "\${DUBLE_BANCO_AUSENTE:-0}" == 1 ]] || echo banco1 ;;
  *"ps -q pgb1"*) echo pgb11 ;;
  *"ps -q pgb2"*) echo pgb21 ;;
  *"inspect"*novo1*) echo "\${DUBLE_SAUDE_NOVO:-healthy}" ;;
  *"inspect"*banco1*) if [[ "\${DUBLE_BANCO_NAO_VOLTA:-0}" == 1 && -e "$VM/.subiu" ]]; then echo starting; else echo "\${DUBLE_SAUDE_BANCO:-healthy}"; fi ;;
  *"inspect"*pgb11*) echo "\${DUBLE_SAUDE_PGB1:-healthy}" ;;
  *"inspect"*pgb21*) echo "\${DUBLE_SAUDE_PGB2:-healthy}" ;;
  *"up -d --no-deps banco_novo"*) [[ "\${DUBLE_UP_NOVO_FALHA:-0}" == 1 ]] && exit 1 ;;
  *"up -d --no-deps banco"*) [[ "\${DUBLE_UP_FALHA:-0}" == 1 ]] && exit 1; touch "$VM/.subiu" ;;
  *"pg_dump"*) [[ "\${DUBLE_BACKUP_FALHA:-0}" == 1 ]] && exit 1; echo "dados-do-banco" ;;
  *"SHOW wal_level"*) if [[ -e "$VM/.subiu" ]]; then echo "\${DUBLE_WAL_DEPOIS:-logical}"; else echo "\${DUBLE_WAL:-off}"; fi ;;
  *"pg_current_wal_lsn"*) echo "0/16B3748" ;;
  *"pg_stat_subscription"*) echo "\${DUBLE_LAG:-t}" ;;
  *"srsubstate"*) echo "\${DUBLE_SINCRONIA:-5/5}" ;;
  *"string_agg"*) [[ "\${DUBLE_TABELAS_VAZIA:-0}" == 1 ]] || echo "public.fazenda" ;;
  *"exec -T banco_novo"*"count(*)"*) echo "\${DUBLE_TABELAS_DESTINO:-0}" ;;
  *"-c PAUSE"*) [[ -n "\${DUBLE_PAUSE_FALHA:-}" && "$args" == *"exec -T $DUBLE_PAUSE_FALHA "* ]] && exit 1 ;;
  *"-c RESUME"*) [[ -n "\${DUBLE_RESUME_FALHA:-}" && "$args" == *"exec -T $DUBLE_RESUME_FALHA "* ]] && exit 1 ;;
esac
exit 0
`;

// VM de mentira: `.env` com a senha, clone com o SQL sintético e o `docker` de mentira acima.
function criarVm({ comSenha = true } = {}) {
  const vm = fs.mkdtempSync(path.join(os.tmpdir(), 'trocar-banco-'));
  fs.mkdirSync(path.join(vm, 'repo', '.git'), { recursive: true });
  fs.mkdirSync(path.join(vm, 'repo', 'servidor', 'banco'), { recursive: true });
  fs.writeFileSync(path.join(vm, 'repo', 'servidor', 'compose.implantacao.yaml'), 'services: {}\n');
  fs.writeFileSync(path.join(vm, 'repo', 'servidor', 'banco', 'papeis.sql'), '-- sintético\n');
  const linhaSenha = comSenha ? `PHATI_BANCO_REPLICADOR_SENHA=${SEGREDO}\n` : 'PHATI_BANCO_REPLICADOR_SENHA=\n';
  fs.writeFileSync(path.join(vm, '.env'), `PHATI_BANCO_NOME=phati\nPHATI_BANCO_APP_USUARIO=app\n${linhaSenha}`, { mode: 0o640 });
  const chamadas = path.join(vm, 'chamadas.log');
  const dublê = path.join(vm, 'docker-dublê.sh');
  fs.writeFileSync(dublê, CORPO_DUBLE, { mode: 0o755 });
  // `flock` de mentira com a mesma linha de comando: "ocupado" é o arquivo `<trava>.ocupado`, como no implantacao.test.js.
  const flockDublê = path.join(vm, 'flock-dublê.sh');
  fs.writeFileSync(
    flockDublê,
    [
      '#!/usr/bin/env bash',
      't=0; e=1',
      'while [[ "${1:-}" == -* ]]; do case "$1" in -w) t="$2"; shift 2 ;; -E) e="$2"; shift 2 ;; *) shift ;; esac; done',
      'arquivo="$1"; shift',
      'if [[ -e "$arquivo.ocupado" ]]; then sleep "$t"; exit "$e"; fi',
      'exec "$@"',
      '',
    ].join('\n'),
    { mode: 0o755 },
  );
  const lerChamadas = () => (fs.existsSync(chamadas) ? fs.readFileSync(chamadas, 'utf8').split('\n').filter(Boolean) : []);
  const indice = (trecho) => lerChamadas().findIndex((linha) => linha.includes(trecho));
  const contar = (trecho) => lerChamadas().filter((linha) => linha.includes(trecho)).length;
  const lerArq = (nome) => (fs.existsSync(path.join(vm, nome)) ? fs.readFileSync(path.join(vm, nome), 'utf8') : null);
  return {
    vm,
    lerChamadas,
    indice,
    contar,
    registro: () => lerArq('implantacoes.log') ?? '',
    env: () => fs.readFileSync(path.join(vm, '.env'), 'utf8'),
    modoEnv: () => fs.statSync(path.join(vm, '.env')).mode & 0o777,
    bancoAtivo: () => lerArq('banco-ativo'),
    limpar: () => fs.rmSync(vm, { recursive: true, force: true }),
    rodar(args, extra = {}) {
      return spawnSync('bash', [unix(TROCAR), ...args], {
        encoding: 'utf8',
        env: {
          ...process.env,
          PHATI_DIR: unix(vm),
          DOCKER: unix(dublê),
          PHATI_FLOCK: unix(flockDublê),
          PHATI_ESPERA: '0',
          PHATI_TENTATIVAS: '2',
          CHAMADAS: unix(chamadas),
          VM: unix(vm),
          ...extra,
        },
      });
    },
  };
}

// Troca com o caminho feliz por padrão (wal já `logical`, senão a troca recusa). Cada teste sobrescreve só o que quer.
const trocar = (v, extra = {}) => v.rodar(['trocar'], { DUBLE_WAL: 'logical', ...extra });

// Nenhuma saída, registro nem argumento de chamada pode conter a senha.
function semSegredo(v, r) {
  assert.ok(!r.stdout.includes(SEGREDO), 'segredo no stdout');
  assert.ok(!r.stderr.includes(SEGREDO), 'segredo no stderr');
  assert.ok(!v.registro().includes(SEGREDO), 'segredo no registro');
  assert.ok(!v.lerChamadas().some((linha) => linha.includes(SEGREDO)), 'segredo em argumento de chamada');
}

// Nenhuma saída, registro nem argumento de chamada pode conter o verificador SCRAM copiado.
function semVerificador(v, r) {
  assert.ok(!r.stdout.includes(VERIFICADOR), 'verificador no stdout');
  assert.ok(!r.stderr.includes(VERIFICADOR), 'verificador no stderr');
  assert.ok(!v.registro().includes(VERIFICADOR), 'verificador no registro');
  assert.ok(!v.lerChamadas().some((linha) => linha.includes(VERIFICADOR)), 'verificador em argumento de chamada');
}

// Estado de "nada trocado" depois de falha: `.env` sem destino e sem banco-ativo. O host é checado à parte (há casos em que o
// `sed` foi tentado e depois restaurado, então a linha de comando sozinha não prova nada).
function nadaTrocado(v) {
  assert.ok(!v.env().includes('PHATI_BANCO_DESTINO='), '.env ganhou destino sem sucesso');
  assert.equal(v.bancoAtivo(), null, 'banco-ativo gravado sem sucesso');
}

test('preparar feliz: backup antes do PAUSE, PAUSE antes do reinício do banco, RESUME por último, sem segredo', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['preparar']);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /^preparar_ok pausa_ms=\d+$/m);
    const backup = v.indice('pg_dump');
    const sql = v.indice('-e PHATI_BANCO_REPLICADOR_SENHA');
    const pausa = v.indice('exec -T pgb1 psql -X -q -h /tmp/pgb/pgb1 -p 6432 -U pgbouncer pgbouncer -c PAUSE');
    const sobe = v.indice('up -d --no-deps banco');
    const retoma = v.indice('exec -T pgb1 psql -X -q -h /tmp/pgb/pgb1 -p 6432 -U pgbouncer pgbouncer -c RESUME');
    assert.ok(backup >= 0 && sql > backup && pausa > sql && sobe > pausa && retoma > sobe, `ordem: ${backup} ${sql} ${pausa} ${sobe} ${retoma}`);
    assert.equal(v.contar('-c RESUME'), 2);
    assert.match(v.registro(), /troca-banco preparar OK pausa_ms=\d+/);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('preparar: o console do PgBouncer leva -U pgbouncer em PAUSE e RESUME (sem ele o psql falha no ensaio)', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['preparar']);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contar('-U pgbouncer pgbouncer -c PAUSE'), 2);
    assert.equal(v.contar('-U pgbouncer pgbouncer -c RESUME'), 2);
    assert.equal(v.contar('pgbouncer -c PAUSE') - v.contar('-U pgbouncer pgbouncer -c PAUSE'), 0, 'PAUSE sem -U pgbouncer');
  } finally {
    v.limpar();
  }
});

test('preparar com wal_level já logical: não pausa nem reinicia, mas segue com backup e SQL', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['preparar'], { DUBLE_WAL: 'logical' });
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /^preparar_ok ja_logical=1$/m);
    assert.equal(v.contar('-c PAUSE'), 0);
    assert.equal(v.contar('up -d --no-deps banco'), 0);
    assert.equal(v.contar('pg_dump'), 1);
    assert.equal(v.contar('-e PHATI_BANCO_REPLICADOR_SENHA'), 1);
    assert.match(v.registro(), /troca-banco preparar OK ja_logical=1/);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('preparar recusa sem .env, sem senha do replicador e sem clone, sem chamar o Docker', () => {
  const semEnv = criarVm();
  try {
    fs.rmSync(path.join(semEnv.vm, '.env'));
    const r = semEnv.rodar(['preparar']);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /\.env ausente/);
    assert.deepEqual(semEnv.lerChamadas(), []);
  } finally {
    semEnv.limpar();
  }
  const semSenha = criarVm({ comSenha: false });
  try {
    const r = semSenha.rodar(['preparar']);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /PHATI_BANCO_REPLICADOR_SENHA ausente ou vazia/);
    assert.ok(!r.stderr.includes(SEGREDO));
    assert.deepEqual(semSenha.lerChamadas(), []);
  } finally {
    semSenha.limpar();
  }
  const semClone = criarVm();
  try {
    fs.rmSync(path.join(semClone.vm, 'repo', '.git'), { recursive: true });
    const r = semClone.rodar(['preparar']);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /não é um clone/);
    assert.deepEqual(semClone.lerChamadas(), []);
  } finally {
    semClone.limpar();
  }
});

test('preparar recusa PgBouncer indisponível e banco parado antes do backup, sem PAUSE', () => {
  const pgb = criarVm();
  try {
    const r = pgb.rodar(['preparar'], { DUBLE_SAUDE_PGB2: 'unhealthy' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /PgBouncer indisponível/);
    assert.equal(pgb.contar('pg_dump'), 0);
    assert.equal(pgb.contar('-c PAUSE'), 0);
  } finally {
    pgb.limpar();
  }
  const banco = criarVm();
  try {
    const r = banco.rodar(['preparar'], { DUBLE_SAUDE_BANCO: 'unhealthy' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /banco não está saudável/);
    assert.equal(banco.contar('pg_dump'), 0);
    assert.equal(banco.contar('-c PAUSE'), 0);
  } finally {
    banco.limpar();
  }
});

test('falha do backup aborta antes de qualquer alteração: sem SQL, sem PAUSE', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['preparar'], { DUBLE_BACKUP_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /backup verificado falhou: nada foi alterado/);
    assert.equal(v.contar('-e PHATI_BANCO_REPLICADOR_SENHA'), 0);
    assert.equal(v.contar('-c PAUSE'), 0);
    assert.equal(v.contar('up -d --no-deps banco'), 0);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('falha do SQL do replicador: RESUME ocorre, saída suprimida e a senha não vaza', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['preparar'], { DUBLE_WAL: 'off', DUBLE_SQL_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /SQL do papel replicador falhou/);
    assert.equal(v.contar('-c PAUSE'), 0);
    assert.equal(v.contar('-c RESUME'), 0, 'sem PAUSE não há RESUME');
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('PAUSE de pgb2 falha: RESUME nos dois processos, sem reiniciar o banco', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['preparar'], { DUBLE_PAUSE_FALHA: 'pgb2' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /não consegui pausar pgb2/);
    assert.equal(v.contar('up -d --no-deps banco'), 0);
    assert.equal(v.contar('-c RESUME'), 2, 'RESUME nos dois, mesmo com PAUSE parcial');
    assert.match(v.registro(), /troca-banco preparar FALHOU: não consegui pausar pgb2/);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('falha no reinício do banco: RESUME ocorre (trap)', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['preparar'], { DUBLE_WAL: 'off', DUBLE_UP_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /não consegui recriar o banco/);
    assert.equal(v.contar('-c RESUME'), 2);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('banco não volta saudável depois do reinício: RESUME ocorre', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['preparar'], { DUBLE_WAL: 'off', DUBLE_BANCO_NAO_VOLTA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /banco não voltou saudável/);
    assert.equal(v.contar('-c RESUME'), 2);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('wal_level que não vira logical após o reinício: aborta com RESUME', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['preparar'], { DUBLE_WAL: 'off', DUBLE_WAL_DEPOIS: 'replica' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /wal_level não virou logical \(valor: replica\)/);
    assert.equal(v.contar('-c RESUME'), 2);
    assert.match(v.registro(), /FALHOU: wal_level não virou logical/);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('RESUME que falha no caminho feliz aparece em AVISO e não encerra com sucesso', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['preparar'], { DUBLE_WAL: 'off', DUBLE_RESUME_FALHA: 'pgb1' });
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /RESUME falhou em/);
    assert.ok(!/^preparar_ok/m.test(r.stdout));
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('subcomando inválido, ausente ou com argumento extra é recusado sem chamar o Docker', () => {
  const v = criarVm();
  try {
    for (const args of [[], ['xyz'], ['preparar; rm -rf /'], ['preparar', '--apagar'], ['trocar', '--apagar']]) {
      const r = v.rodar(args);
      assert.equal(r.status, 1, JSON.stringify(args));
      assert.match(r.stderr, /subcomando inválido|opção desconhecida/);
    }
    assert.deepEqual(v.lerChamadas(), []);
  } finally {
    v.limpar();
  }
});

test('trava ocupada vira erro com mensagem (rc 1), sem chamar o Docker', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, '.trava.ocupado'), '');
    const r = v.rodar(['preparar'], { PHATI_TRAVA_LIMITE: '0' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /outra operação de banco ou implantação segue rodando/);
    assert.match(v.registro(), /FALHOU: trava ocupada/);
    assert.deepEqual(v.lerChamadas(), []);
  } finally {
    v.limpar();
  }
});

// ---- trocar (T5.4b) ----

test('trocar feliz: ordem exata das chamadas, destino gravado e banco-ativo só no sucesso, sem segredo', () => {
  const v = criarVm();
  try {
    const modo = v.modoEnv();
    const r = trocar(v);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /^trocar_ok pausa_ms=\d+$/m);
    const passos = [
      ['sobe banco_novo', 'up -d --no-deps banco_novo'],
      ['backup', 'pg_dump'],
      ['esquema', '--schema-only'],
      ['publicação', '#sql:publicacao'],
      ['assinatura', '#sql:assinatura'],
      ['espera r', 'srsubstate'],
      ['leitura do verificador', '#sql:leitura-verificador'],
      ['verificador no destino', '#sql:verificador'],
      ['PAUSE', '-c PAUSE'],
      ['lag zero', 'pg_stat_subscription'],
      ['DISABLE', '#sql:desabilita'],
      ['setval', '#sql:setval'],
      ['sed host', 'sed -i'],
      ['RELOAD', '-c RELOAD'],
      ['RESUME', '-c RESUME'],
      ['DROP SUBSCRIPTION', '#sql:limpa'],
      ['DROP PUBLICATION', '#sql:despublica'],
    ];
    const idx = passos.map(([, trecho]) => v.indice(trecho));
    passos.forEach(([nome], k) => {
      assert.ok(idx[k] >= 0, `${nome} não ocorreu`);
      if (k > 0) assert.ok(idx[k] > idx[k - 1], `${nome} veio antes de ${passos[k - 1][0]}`);
    });
    assert.equal(v.contar('-c RESUME'), 2);
    assert.equal(v.contar(DIREITO), 2, 'host novo nos dois PgBouncer');
    assert.equal(v.contar('margem=1000'), 1, 'margem padrão na consulta de sequências');
    assert.equal(v.contar('#sql:hash'), 2, 'hash lido nas duas pontas');
    assert.equal(v.contar('#sql:verificador'), 1, 'verificador aplicado uma vez no destino');
    assert.equal(v.contar('#sql:despublica'), 1, 'publicação removida no sucesso');
    semVerificador(v, r);
    assert.equal(v.env().split('\n').filter((l) => l === 'PHATI_BANCO_DESTINO=banco_novo').length, 1);
    assert.equal(v.bancoAtivo(), 'banco_novo\n');
    assert.equal(v.modoEnv(), modo, 'modo do .env mudou');
    assert.match(v.registro(), /troca-banco trocar OK pausa_ms=\d+ destino=banco_novo/);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar: PHATI_MARGEM_SEQ chega à consulta de sequências', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { PHATI_MARGEM_SEQ: '50' });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contar('margem=50'), 1);
    assert.equal(v.contar('margem=1000'), 0);
  } finally {
    v.limpar();
  }
});

test('trocar: margem inválida (negativa, texto ou decimal) recusa sem chamar o Docker', () => {
  const v = criarVm();
  try {
    for (const margem of ['-1', 'abc', '1.5', '99999999999999999']) {
      const r = trocar(v, { PHATI_MARGEM_SEQ: margem });
      assert.equal(r.status, 1, margem);
      assert.match(r.stderr, /PHATI_MARGEM_SEQ inválida/);
    }
    assert.deepEqual(v.lerChamadas(), []);
  } finally {
    v.limpar();
  }
});

test('trocar já feito (banco-ativo=banco_novo): sai ok sem chamar o Docker nem pausar', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco_novo\n');
    const r = trocar(v);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /^trocar_ok ja_trocado=1$/m);
    assert.deepEqual(v.lerChamadas(), []);
    assert.match(v.registro(), /troca-banco trocar OK ja_trocado=1/);
  } finally {
    v.limpar();
  }
});

test('trocar recusa wal_level que não é logical antes de subir o banco_novo', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['trocar'], { DUBLE_WAL: 'off' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /wal_level não é logical: rode preparar antes/);
    assert.equal(v.contar('up -d --no-deps banco_novo'), 0);
    assert.equal(v.contar('-c PAUSE'), 0);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar recusa sem senha do replicador e destino atual diferente de banco, sem chamar o Docker', () => {
  const semSenha = criarVm({ comSenha: false });
  try {
    const r = trocar(semSenha);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /PHATI_BANCO_REPLICADOR_SENHA ausente ou vazia/);
    assert.deepEqual(semSenha.lerChamadas(), []);
  } finally {
    semSenha.limpar();
  }
  const outro = criarVm();
  try {
    fs.appendFileSync(path.join(outro.vm, '.env'), 'PHATI_BANCO_DESTINO=outro_banco\n');
    const r = trocar(outro);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /PHATI_BANCO_DESTINO é 'outro_banco'/);
    assert.equal(outro.contar('-c PAUSE'), 0);
  } finally {
    outro.limpar();
  }
});

test('trocar: banco_novo não saudável aborta antes do backup e sem PAUSE', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_SAUDE_NOVO: 'unhealthy' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /banco_novo não voltou saudável/);
    assert.equal(v.contar('pg_dump'), 0);
    assert.equal(v.contar('-c PAUSE'), 0);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar: falha do backup não toca em nada (sem esquema, publicação, PAUSE nem host)', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_BACKUP_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /backup verificado falhou: nada foi alterado/);
    assert.equal(v.contar('--schema-only'), 0);
    assert.equal(v.contar('#sql:publicacao'), 0);
    assert.equal(v.contar('#sql:assinatura'), 0);
    assert.equal(v.contar('-c PAUSE'), 0);
    assert.equal(v.contar('sed -i'), 0);
    nadaTrocado(v);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar: destino já com tabelas de usuário pula o esquema (AVISO) e segue', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_TABELAS_DESTINO: '3' });
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stderr, /já tem tabelas de usuário em public: esquema não aplicado/);
    assert.equal(v.contar('--schema-only'), 0);
    assert.equal(v.contar('#sql:publicacao'), 1);
  } finally {
    v.limpar();
  }
});

test('trocar: lista de tabelas vazia recusa antes da publicação, sem PAUSE', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_TABELAS_VAZIA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /lista de tabelas vazia: nada a publicar/);
    assert.equal(v.contar('#sql:publicacao'), 0);
    assert.equal(v.contar('#sql:assinatura'), 0);
    assert.equal(v.contar('-c PAUSE'), 0);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar: sincronização que não chega a r deixa nada pausado e a assinatura limpa', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_SINCRONIA: '0/5' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /sincronização não chegou a 'r'/);
    assert.equal(v.contar('-c PAUSE'), 0);
    assert.equal(v.contar('#sql:limpa'), 1, 'assinatura não removida');
    assert.equal(v.contar('sed -i'), 0);
    nadaTrocado(v);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar: nenhuma tabela sincronizada (0/0) não conta como pronto', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_SINCRONIA: '0/0' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /sincronização não chegou a 'r'/);
    assert.equal(v.contar('-c PAUSE'), 0);
  } finally {
    v.limpar();
  }
});

test('trocar: lag que não chega a zero com PAUSE faz RESUME sem trocar o host', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_LAG: 'f' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /destino não alcançou o LSN da origem com PAUSE ativo: nada trocado/);
    assert.equal(v.contar('-c PAUSE'), 2);
    assert.equal(v.contar('-c RESUME'), 2);
    assert.equal(v.contar('#sql:desabilita'), 0);
    assert.equal(v.contar('sed -i'), 0);
    assert.equal(v.contar('#sql:limpa'), 1, 'assinatura não removida');
    assert.ok(v.indice('-c RESUME') < v.indice('#sql:limpa'), 'assinatura removida com PAUSE ainda ativo');
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar: falha do setval faz RESUME e deixa o host intacto', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_FALHA_SQL: 'setval' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /sequências não ajustadas no banco_novo: nada trocado/);
    assert.equal(v.contar('-c RESUME'), 2);
    assert.equal(v.contar('sed -i'), 0, 'host reescrito antes do setval');
    assert.equal(v.contar('#sql:limpa'), 1);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar: falha do sed no primeiro PgBouncer restaura o host e faz RESUME', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_FALHA_UMA: 'sed -i' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /não consegui trocar o host em pgb1/);
    assert.equal(v.contar(RESTAURA), 2, 'host não restaurado nos dois PgBouncer');
    assert.equal(v.contar('-c RELOAD'), 2, 'RELOAD da restauração');
    assert.equal(v.contar('-c RESUME'), 2);
    assert.equal(v.contar('#sql:limpa'), 1);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar: falha do RELOAD depois do sed restaura o host e faz RESUME', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_FALHA_UMA: '-c RELOAD' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /RELOAD falhou em pgb1/);
    assert.equal(v.contar(RESTAURA), 2, 'host não restaurado');
    assert.equal(v.contar('-c RELOAD'), 3, 'um RELOAD falho e dois da restauração');
    assert.equal(v.contar('-c RESUME'), 2);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar: RESUME falha depois da troca não restaura o host (sem rollback) e não remove a assinatura', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_RESUME_FALHA: 'pgb1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /RESUME falhou depois da troca de host: sem rollback automático/);
    assert.equal(v.contar(RESTAURA), 0, 'host restaurado depois do ponto sem volta');
    assert.equal(v.contar('#sql:limpa'), 0);
    assert.ok(!v.env().includes('PHATI_BANCO_DESTINO='), '.env gravado sem o RESUME');
  } finally {
    v.limpar();
  }
});

test('trocar: DROP SUBSCRIPTION falho depois do RESUME vira AVISO e a troca conclui', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_FALHA_SQL: 'limpa' });
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /^trocar_ok pausa_ms=\d+$/m);
    assert.match(r.stderr, /AVISO: DROP SUBSCRIPTION falhou no banco_novo/);
    assert.equal(v.bancoAtivo(), 'banco_novo\n');
    assert.match(v.env(), /^PHATI_BANCO_DESTINO=banco_novo$/m);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar: verificador diferente depois de aplicar aborta antes do PAUSE, sem host alterado e com publicação removida', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_HASH_NOVO: 'h-outro' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /verificador de app no banco_novo difere da origem: nada pausado/);
    assert.equal(v.contar('-c PAUSE'), 0, 'pausou com verificador divergente');
    assert.equal(v.contar('sed -i'), 0, 'host alterado com verificador divergente');
    assert.equal(v.contar('#sql:despublica'), 1, 'publicação não removida no aborto');
    nadaTrocado(v);
    semSegredo(v, r);
    semVerificador(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar: falha ao ler o verificador da origem aborta antes do PAUSE, sem copiar nada', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_FALHA_SQL: 'leitura-verificador' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /verificador de app não copiado para o banco_novo: nada pausado/);
    assert.equal(v.contar('-c PAUSE'), 0);
    assert.equal(v.contar('sed -i'), 0);
    assert.equal(v.contar('#sql:despublica'), 1, 'publicação não removida no aborto');
    nadaTrocado(v);
    semSegredo(v, r);
    semVerificador(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar: falha ao ler o hash do verificador na origem aborta antes de qualquer cópia', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_FALHA_SQL: 'hash' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /verificador SCRAM de app ausente no banco: nada pausado/);
    assert.equal(v.contar('#sql:verificador'), 0, 'cópia tentada sem hash de origem');
    assert.equal(v.contar('-c PAUSE'), 0);
    nadaTrocado(v);
    semVerificador(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar: papel do app inválido (nome com maiúscula e ponto e vírgula) recusa antes de qualquer SQL', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { PHATI_BANCO_APP_USUARIO: 'App;drop' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /PHATI_BANCO_APP_USUARIO ausente ou inválido: nada foi feito/);
    assert.equal(v.contar('up -d'), 0, 'subiu o banco_novo com papel inválido');
    assert.equal(v.contar('#sql:'), 0, 'SQL executado com papel inválido');
    assert.equal(v.contar('-c PAUSE'), 0);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar: aborto remove a publicação depois da assinatura, com o RESUME já feito', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_LAG: 'f' });
    assert.equal(r.status, 1);
    assert.equal(v.contar('#sql:despublica'), 1, 'publicação não removida no aborto');
    assert.ok(v.indice('-c RESUME') < v.indice('#sql:limpa'), 'assinatura removida antes do RESUME');
    assert.ok(v.indice('#sql:limpa') < v.indice('#sql:despublica'), 'publicação removida antes da assinatura');
    nadaTrocado(v);
    semVerificador(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar: DROP PUBLICATION falho no aborto vira AVISO com comando e o erro original segue (rc 1)', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_LAG: 'f', DUBLE_FALHA_SQL: 'despublica' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /destino não alcançou o LSN da origem com PAUSE ativo: nada trocado/);
    assert.match(r.stderr, /AVISO: não consegui remover a publicação phati_troca_pub no banco: rode DROP PUBLICATION IF EXISTS phati_troca_pub; no banco/);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar: DROP PUBLICATION falho depois do RESUME vira AVISO e a troca conclui', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_FALHA_SQL: 'despublica' });
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /^trocar_ok pausa_ms=\d+$/m);
    assert.match(r.stderr, /AVISO: não consegui remover a publicação phati_troca_pub no banco/);
    assert.equal(v.bancoAtivo(), 'banco_novo\n');
    semVerificador(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar: falha da criação da assinatura não vaza a senha e não pausa', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_FALHA_SQL: 'assinatura' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /assinatura não criada no banco_novo \(saída suprimida: contém a senha\)/);
    assert.equal(v.contar('-c PAUSE'), 0);
    assert.equal(v.contar('#sql:limpa'), 0, 'assinatura que não foi criada não tem o que remover');
    nadaTrocado(v);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});
