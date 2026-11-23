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
// Senha sintética com espaço, aspas simples, barra invertida e dois-pontos: o escape do passfile (.pgpass) precisa cobri-la.
const SEGREDO_DIFICIL = "valor dif'icil\\x:y";
// Mesma senha depois do escape do formato .pgpass: `\` vira `\\` e `:` vira `\:`.
const SEGREDO_DIFICIL_ESCAPADO = "valor dif'icil\\\\x\\:y";
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
    *"ALTER SYSTEM RESET"*) tag=conninfo ;;
    *"DISABLE"*) tag=desabilita ;;
    *"pg_sequences"*) tag=sequencias ;;
    *"setval"*) tag=setval ;;
    *"sha256"*) tag=hash ;;
    *"format('ALTER ROLE"*) tag=leitura-verificador ;;
    *"ALTER ROLE"*) tag=verificador ;;
    *) tag=esquema ;;
  esac
  echo "$args #sql:$tag" >> "$CHAMADAS"
  if [[ "$tag" == assinatura ]]; then echo "$ent" >> "$VM/assinatura.sql"; fi
else
  echo "$args" >> "$CHAMADAS"
fi
if [[ -n "\${DUBLE_FALHA_UMA:-}" && "$args" == *"$DUBLE_FALHA_UMA"* && ! -e "$VM/.falhou-uma" ]]; then
  touch "$VM/.falhou-uma"
  exit 1
fi
# Sinal ao script (DUBLE_SINAL=<trecho>), uma vez: SIGTERM ao trocar-banco.sh (ancestral deste dublê). A trap roda quando esta
# chamada volta, então a sequência do script para logo depois dela.
if [[ -n "\${DUBLE_SINAL:-}" && "$args" == *"$DUBLE_SINAL"* && ! -e "$VM/.sinal" ]]; then
  touch "$VM/.sinal"
  pid=$PPID
  while [[ "$pid" -gt 1 ]] && ! grep -q 'trocar-banco.sh' "/proc/$pid/cmdline" 2>/dev/null; do pid="$(awk '{print $4}' "/proc/$pid/stat" 2>/dev/null)"; done
  kill -TERM "$pid" 2>/dev/null || true
fi
if [[ -n "$tag" && "\${DUBLE_FALHA_SQL:-}" == "$tag" ]]; then
  echo "ERROR: falha simulada em $tag com senha $PHATI_BANCO_REPLICADOR_SENHA" >&2
  exit 1
fi
if [[ "$tag" == conninfo && "\${DUBLE_CONNINFO_FALHA:-0}" == 1 ]]; then exit 1; fi
# Progresso do BuildKit no stdout, como o compose imprime quando precisa construir a imagem (DUBLE_PROGRESSO=1).
if [[ "\${DUBLE_PROGRESSO:-0}" == 1 && ( "$args" == *" run "* || "$args" == *" build "* ) ]]; then
  echo "#1 [internal] load build definition"
  echo "#2 DONE 0.1s"
fi
if [[ "$tag" == sequencias ]]; then
  echo "SELECT setval('public.fazenda_id_seq', 1001, true);"
fi
# Verificador SCRAM da origem: vai só ao pipe (stdout do psql da origem), que chega ao psql do destino por stdin. Vem de arquivo
# (escrito pelo JS), para o cifrão do verificador não passar pela expansão do Bash. DUBLE_PAYLOAD_ERRADO=1 troca por outro payload.
if [[ "$tag" == leitura-verificador && "$args" == *"exec -T banco sh"* ]]; then
  arq=verificador-esperado.sql
  [[ "\${DUBLE_PAYLOAD_ERRADO:-0}" == 1 ]] && arq=verificador-errado.sql
  cat "$VM/$arq"
fi
# O payload que chega ao destino por stdin fica guardado: o hash do destino só confere se for exatamente o esperado.
if [[ "$tag" == verificador && "$args" == *"exec -T banco_novo"* ]]; then printf '%s\n' "$ent" > "$VM/verificador-recebido.sql"; fi
# Hash do verificador: origem sempre "h-igual"; destino "h-igual" só com o payload esperado (senão "h-outro").
# DUBLE_HASH_NOVO força outro valor no destino (salt diferente).
if [[ "$tag" == hash ]]; then
  if [[ "$args" != *"exec -T banco_novo"* ]]; then echo "h-igual"
  elif [[ "$(cat "$VM/verificador-recebido.sql" 2>/dev/null)" == "$(cat "$VM/verificador-esperado.sql")" ]]; then echo "\${DUBLE_HASH_NOVO:-h-igual}"
  else echo "h-outro"; fi
fi
# Escrita do passfile da assinatura (sh -c script caminho origem banco): roda o script de verdade, com o arquivo em $VM.
if [[ "$args" == *"sh -c"*"phati-replicador.pgpass"* ]]; then
  [[ "\${DUBLE_PGPASS_FALHA:-0}" == 1 ]] && exit 1
  sh -c "\${@: -4:1}" "$VM/pgpass-gravado" "\${@: -2:1}" "\${@: -1}"
  exit $?
fi
case "$args" in
  *"build banco_novo"*)[[ "\${DUBLE_BUILD_FALHA:-0}" == 1 ]] && exit 1 ;;
  *"ls -A /var/lib/postgresql"*) [[ "\${DUBLE_VOLUME_CHEIO:-0}" == 1 ]] && echo PG_VERSION ;;
  *"SHOW server_version_num"*) echo "\${DUBLE_VERSAO_ORIGEM:-180003}" ;;
  *"postgres --version"*) echo "postgres (PostgreSQL) \${DUBLE_VERSAO_NOVO:-18.1}" ;;
  *"grep -qxF"*) [[ -e "$VM/.hba" || "\${DUBLE_HBA_TEM:-0}" == 1 ]] || exit 1 ;;
  *"printf"*"pg_hba.conf"*) touch "$VM/.hba"; [[ "\${DUBLE_HBA_FALHA:-0}" == 1 ]] && exit 1 ;;
  *"pg_hba_file_rules"*) echo "\${DUBLE_HBA_REGRA:-1}" ;;
  # Papel: sem o papeis.sql rodado na origem (arquivo .replicador ausente), vale DUBLE_REPLICADOR (padrão 1); depois, 1.
  *"rolreplication"*) if [[ -e "$VM/.replicador" ]]; then echo 1; else echo "\${DUBLE_REPLICADOR:-1}"; fi ;;
  *"pg_basebackup"*) [[ "\${DUBLE_BASE_FALHA:-0}" == 1 ]] && exit 1; touch "$VM/.base" ;;
  *"pg_is_in_recovery"*) if [[ -e "$VM/.promovido" || "\${DUBLE_SEM_RECOVERY:-0}" == 1 ]]; then echo f; else echo t; fi ;;
  *"pg_stat_wal_receiver"*) echo "\${DUBLE_STREAM:-1}" ;;
  # Depois do promote o standby deixa de receber do primário: o slot fica inativo (arquivo .standby-ativo sai).
  *"pg_promote"*) [[ "\${DUBLE_PROMOTE_FALHA:-0}" == 1 ]] && exit 1; touch "$VM/.promovido"; rm -f "$VM/.standby-ativo"; echo t ;;
  *"pg_last_wal_replay_lsn"*) echo "\${DUBLE_LAG_FISICO-0}" ;;
  # Slot: o PostgreSQL recusa drop com o standby ativo (arquivo .standby-ativo); .slot-removido prova que o drop foi feito.
  *"pg_drop_replication_slot"*) if [[ -e "$VM/.standby-ativo" ]]; then echo "ERROR: replication slot is active" >&2; exit 1; fi; [[ "\${DUBLE_SLOT_FALHA:-0}" == 1 ]] && exit 1; touch "$VM/.slot-removido"; echo "" ;;
  *"SELECT active FROM pg_replication_slots"*) if [[ -e "$VM/.standby-ativo" || "\${DUBLE_SLOT_ATIVO:-0}" == 1 ]]; then echo t; else echo f; fi ;;
  *"-e PHATI_BANCO_REPLICADOR_SENHA"*)if [[ "\${DUBLE_SQL_FALHA:-0}" == 1 ]]; then echo "ERROR: CREATE ROLE replicador PASSWORD $PHATI_BANCO_REPLICADOR_SENHA" >&2; exit 1; fi; touch "$VM/.replicador" ;;
  *"ps -q banco_novo"*) [[ "\${DUBLE_NOVO_AUSENTE:-0}" == 1 ]] || echo novo1 ;;
  *"ps -q banco"*) [[ "\${DUBLE_BANCO_AUSENTE:-0}" == 1 ]] || echo banco1 ;;
  *"ps -q pgb1"*) echo pgb11 ;;
  *"ps -q pgb2"*) echo pgb21 ;;
  *"inspect"*novo1*) echo "\${DUBLE_SAUDE_NOVO:-healthy}" ;;
  *"inspect"*banco1*) if [[ "\${DUBLE_BANCO_NAO_VOLTA:-0}" == 1 && -e "$VM/.subiu" ]]; then echo starting; else echo "\${DUBLE_SAUDE_BANCO:-healthy}"; fi ;;
  *"inspect"*pgb11*) echo "\${DUBLE_SAUDE_PGB1:-healthy}" ;;
  *"inspect"*pgb21*) echo "\${DUBLE_SAUDE_PGB2:-healthy}" ;;
  *"stop banco_novo"*|*"rm -sfv"*) rm -f "$VM/.standby-ativo" ;;
  *"up -d --no-deps banco_novo"*) [[ "\${DUBLE_UP_NOVO_FALHA:-0}" == 1 ]] && exit 1; touch "$VM/.standby-ativo" ;;
  *"up -d --no-deps banco"*) [[ "\${DUBLE_UP_FALHA:-0}" == 1 ]] && exit 1; touch "$VM/.subiu" ;;
  *"pg_dump"*) [[ "\${DUBLE_BACKUP_FALHA:-0}" == 1 ]] && exit 1; echo "dados-do-banco" ;;
  *"SHOW wal_level"*) if [[ -e "$VM/.subiu" ]]; then echo "\${DUBLE_WAL_DEPOIS:-logical}"; else echo "\${DUBLE_WAL:-off}"; fi ;;
  *"pg_current_wal_lsn"*) echo "0/16B3748" ;;
  *"pg_stat_subscription"*) echo "\${DUBLE_LAG:-t}" ;;
  # Confirmação do slot na origem: f até DUBLE_LAG_SLOT_APOS consultas (conta em $VM), depois t. DUBLE_LAG_SLOT=f nunca confirma.
  *"pg_replication_slots"*) n="$(cat "$VM/.slot-consultas" 2>/dev/null || echo 0)"; echo $((n + 1)) > "$VM/.slot-consultas"; if [[ "\${DUBLE_LAG_SLOT:-t}" == t ]] && (( n >= \${DUBLE_LAG_SLOT_APOS:-0} )); then echo t; else echo f; fi ;;
  *"srsubstate"*) echo "\${DUBLE_SINCRONIA:-5/5}" ;;
  *"string_agg"*) [[ "\${DUBLE_TABELAS_VAZIA:-0}" == 1 ]] || echo "public.fazenda" ;;
  *"exec -T banco_novo"*"count(*)"*) echo "\${DUBLE_TABELAS_DESTINO:-0}" ;;
  *"printf"*"/cfg/banco-destino"*) [[ "\${DUBLE_GRAVA_FALHA:-0}" == 1 ]] && exit 1 ;;
  *"rm -f /cfg/banco-destino"*) [[ "\${DUBLE_REMOVE_FALHA:-0}" == 1 ]] && exit 1 ;;
  # Remoção do passfile no banco_novo: o arquivo sai de $VM/pgpass-gravado para $VM/pgpass-removido (guarda o conteúdo para o teste).
  *"rm -f /tmp/phati-replicador.pgpass"*) [[ "\${DUBLE_PGPASS_REMOVE_FALHA:-0}" == 1 ]] && exit 1; mv -f "$VM/pgpass-gravado" "$VM/pgpass-removido" 2>/dev/null || true ;;
  # Restauração do host (C1): falha o sed de volta só na instância de DUBLE_RESTAURA_FALHA (a ida usa host=banco_novo /, outra forma).
  # Linha do ini (E11): o grep de host=banco (com espaço) passa só se a instância está no host original (DUBLE_INI_PGB1/2, padrão banco_novo).
  *"grep -q host="*) svc=pgb1; [[ "$args" == *"exec -T pgb2 "* ]] && svc=pgb2; est="\${DUBLE_INI_PGB1:-banco_novo}"; [[ "$svc" == pgb2 ]] && est="\${DUBLE_INI_PGB2:-banco_novo}"; [[ "$args" == *"host=banco "* && "$est" == banco ]] || exit 1 ;;
  *"host=banco_novo /host=banco /"*) [[ -n "\${DUBLE_RESTAURA_FALHA:-}" && "$args" == *"exec -T $DUBLE_RESTAURA_FALHA "* ]] && exit 1 ;;
  # PAUSE pendurado (C2): dorme além do limite em DUBLE_PAUSE_PENDURA; o exec troca o processo, então o timeout mata o sleep.
  *"-c PAUSE"*) [[ -n "\${DUBLE_PAUSE_PENDURA:-}" && "$args" == *"exec -T $DUBLE_PAUSE_PENDURA "* ]] && exec sleep 3; [[ -n "\${DUBLE_PAUSE_FALHA:-}" && "$args" == *"exec -T $DUBLE_PAUSE_FALHA "* ]] && exit 1 ;;
  *"-c RESUME"*) [[ -n "\${DUBLE_RESUME_FALHA:-}" && "$args" == *"exec -T $DUBLE_RESUME_FALHA "* ]] && exit 1 ;;
esac
exit 0
`;

// VM de mentira: `.env` com a senha, clone com o SQL sintético e o `docker` de mentira acima.
function criarVm({ comSenha = true, senha = SEGREDO } = {}) {
  const vm = fs.mkdtempSync(path.join(os.tmpdir(), 'trocar-banco-'));
  fs.mkdirSync(path.join(vm, 'repo', '.git'), { recursive: true });
  fs.mkdirSync(path.join(vm, 'repo', 'servidor', 'banco'), { recursive: true });
  fs.writeFileSync(path.join(vm, 'repo', 'servidor', 'compose.implantacao.yaml'), 'services: {}\n');
  fs.writeFileSync(path.join(vm, 'repo', 'servidor', 'banco', 'papeis.sql'), '-- sintético\n');
  // Verificador que a origem emite (esperado) e um payload trocado (DUBLE_PAYLOAD_ERRADO): o dublê os lê, sem `$` no Bash.
  fs.writeFileSync(path.join(vm, 'verificador-esperado.sql'), `ALTER ROLE app PASSWORD '${VERIFICADOR}';\n`);
  fs.writeFileSync(path.join(vm, 'verificador-errado.sql'), "ALTER ROLE app PASSWORD 'SCRAM-SHA-256$4096:outro-salt$outra-chave';\n");
  const linhaSenha = comSenha ? `PHATI_BANCO_REPLICADOR_SENHA=${senha}\n` : 'PHATI_BANCO_REPLICADOR_SENHA=\n';
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
          PHATI_ESPERA_MS: '0',
          PHATI_TENTATIVAS: '2',
          CHAMADAS: unix(chamadas),
          VM: unix(vm),
          PHATI_BANCO_NOME: '',
          COMPOSE_PROFILES: '',
          ...extra,
        },
      });
    },
  };
}

// Troca com o caminho feliz por padrão (wal já `logical`, senão a troca recusa). Cada teste sobrescreve só o que quer.
// `trocar` sem `--modo` é física (S2a) e sai antes do Docker: o caminho lógico, que é o que estes testes cobrem, pede `--modo logica`.
const trocar = (v, extra = {}) => v.rodar(['trocar', '--modo', 'logica'], { DUBLE_WAL: 'logical', ...extra });

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
      ['passfile gravado', 'phati-replicador.pgpass'],
      ['assinatura', '#sql:assinatura'],
      ['espera r', 'srsubstate'],
      ['leitura do verificador', '#sql:leitura-verificador'],
      ['verificador no destino', '#sql:verificador'],
      ['PAUSE', '-c PAUSE'],
      ['lag zero', 'pg_stat_subscription'],
      ['slot da origem confirmou', 'pg_replication_slots'],
      ['DISABLE', '#sql:desabilita'],
      ['setval', '#sql:setval'],
      ['sed host', 'sed -i'],
      ['RELOAD', '-c RELOAD'],
      ['RESUME', '-c RESUME'],
      ['DROP SUBSCRIPTION', '#sql:limpa'],
      ['passfile removido', 'rm -f /tmp/phati-replicador.pgpass'],
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
    // Conninfo da assinatura: aponta para o passfile, sem senha em texto (o log do servidor guarda a instrução).
    const sqlAssinatura = fs.readFileSync(path.join(v.vm, 'assinatura.sql'), 'utf8');
    assert.match(sqlAssinatura, /passfile=\/tmp\/phati-replicador\.pgpass/);
    assert.ok(!sqlAssinatura.includes('password='), 'conninfo com password=');
    assert.ok(!sqlAssinatura.includes(SEGREDO), 'segredo no SQL da assinatura');
    assert.equal(fs.existsSync(path.join(v.vm, 'pgpass-gravado')), false, 'passfile ainda existe no banco_novo');
  } finally {
    v.limpar();
  }
});

test('trocar: senha com espaço, aspas, barra e dois-pontos vai escapada ao passfile e fica fora da conninfo e das saídas', () => {
  const v = criarVm({ senha: SEGREDO_DIFICIL });
  try {
    const r = trocar(v);
    assert.equal(r.status, 0, r.stderr);
    // O conteúdo gravado chega à `pgpass-removido` pelo dublê (o arquivo sai do contêiner no sucesso).
    const pgpass = fs.readFileSync(path.join(v.vm, 'pgpass-removido'), 'utf8');
    assert.equal(pgpass, `banco:5432:phati:replicador:${SEGREDO_DIFICIL_ESCAPADO}\n`);
    assert.equal(fs.statSync(path.join(v.vm, 'pgpass-removido')).mode & 0o777, 0o600, 'passfile fora do modo 0600');
    const sqlAssinatura = fs.readFileSync(path.join(v.vm, 'assinatura.sql'), 'utf8');
    assert.ok(!sqlAssinatura.includes('password='), 'conninfo com password=');
    for (const texto of [SEGREDO_DIFICIL, SEGREDO_DIFICIL_ESCAPADO]) {
      assert.ok(!sqlAssinatura.includes(texto), 'senha no SQL da assinatura');
      assert.ok(!r.stdout.includes(texto) && !r.stderr.includes(texto), 'senha em saída');
      assert.ok(!v.registro().includes(texto), 'senha no registro');
      assert.ok(!v.lerChamadas().some((linha) => linha.includes(texto)), 'senha em argumento de chamada');
    }
  } finally {
    v.limpar();
  }
});

test('trocar: falha ao gravar o passfile aborta antes da assinatura, sem vazar a senha', () => {
  const v = criarVm({ senha: SEGREDO_DIFICIL });
  try {
    const r = trocar(v, { DUBLE_PGPASS_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /não consegui gravar o arquivo de senha no banco_novo: nada trocado/);
    assert.equal(v.contar('#sql:assinatura'), 0, 'assinatura criada sem passfile');
    assert.equal(v.contar('-c PAUSE'), 0);
    assert.equal(v.contar('rm -f /tmp/phati-replicador.pgpass'), 1, 'passfile não removido no aborto');
    nadaTrocado(v);
    assert.ok(!r.stdout.includes(SEGREDO_DIFICIL) && !r.stderr.includes(SEGREDO_DIFICIL));
  } finally {
    v.limpar();
  }
});

test('trocar: falha ao remover o passfile no sucesso vira AVISO e o arquivo fica para a limpeza à mão', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_PGPASS_REMOVE_FALHA: '1' });
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stderr, /AVISO: não consegui remover \/tmp\/phati-replicador\.pgpass no banco_novo/);
    assert.equal(fs.existsSync(path.join(v.vm, 'pgpass-gravado')), true, 'dublê devia ter deixado o arquivo');
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

test('trocar já feito (banco-ativo e .env=banco_novo): sai ok sem chamar o Docker nem pausar', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco_novo\n');
    fs.appendFileSync(path.join(v.vm, '.env'), 'PHATI_BANCO_DESTINO=banco_novo\n');
    const r = trocar(v);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /^trocar_ok ja_trocado=1$/m);
    assert.deepEqual(v.lerChamadas(), []);
    assert.match(v.registro(), /troca-banco trocar OK ja_trocado=1$/m);
  } finally {
    v.limpar();
  }
});

test('trocar recusa wal_level que não é logical antes de subir o banco_novo', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['trocar', '--modo', 'logica'], { DUBLE_WAL: 'off' });
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

test('trocar: destino já com tabelas de usuário recusa antes da publicação e do PAUSE (tentativa anterior abortada)', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_TABELAS_DESTINO: '3' });
    assert.equal(r.status, 1, r.stdout);
    assert.match(r.stderr, /ERRO: banco_novo já tem tabelas de usuário em public: remova o volume dados_banco_novo antes de repetir o modo lógico \(nada foi alterado\)/);
    assert.equal(v.contar('--schema-only'), 0, 'esquema não deve ser aplicado');
    assert.equal(v.contar('#sql:publicacao'), 0, 'publicação não criada');
    assert.equal(v.contar('#sql:assinatura'), 0, 'assinatura não criada');
    assert.equal(v.contar('-c PAUSE'), 0, 'nada pausado');
    nadaTrocado(v);
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
    assert.equal(v.contar('rm -f /tmp/phati-replicador.pgpass'), 1, 'passfile não removido no aborto');
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar: lag só passa quando o slot da origem confirma (a barreira é o confirmed_flush, não o received)', () => {
  const v = criarVm();
  try {
    // O slot responde `f` nas duas primeiras consultas: o destino já recebeu (pré-condição `t`), mas a origem ainda não confirmou.
    const r = trocar(v, { DUBLE_LAG_SLOT_APOS: '2', PHATI_TENTATIVAS: '5' });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contar('pg_stat_subscription'), 3, 'pré-condição no destino a cada tentativa');
    assert.equal(v.contar('pg_replication_slots'), 3, 'slot consultado na origem até confirmar');
    assert.ok(v.indice('pg_replication_slots') < v.indice(DIREITO), 'host trocado antes da confirmação do slot');
    assert.equal(v.contar(DIREITO), 2);
  } finally {
    v.limpar();
  }
});

test('trocar: received_lsn já alcançou mas o slot nunca confirmou: RESUME, aborta sem trocar o host e remove o passfile', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_LAG_SLOT: 'f', PHATI_TENTATIVAS: '3' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /destino não alcançou o LSN da origem com PAUSE ativo: nada trocado/);
    assert.equal(v.contar('pg_stat_subscription'), 3, 'o received alcançou nas três tentativas');
    assert.equal(v.contar('pg_replication_slots'), 3);
    assert.equal(v.contar('-c RESUME'), 2, 'RESUME nos dois PgBouncer');
    assert.equal(v.contar(DIREITO), 0, 'host novo escrito sem confirmação');
    assert.equal(v.contar('sed -i'), 0);
    assert.equal(v.contar('rm -f /tmp/phati-replicador.pgpass'), 1);
    assert.equal(fs.existsSync(path.join(v.vm, 'pgpass-removido')), true, 'passfile não chegou ao banco_novo');
    nadaTrocado(v);
    semSegredo(v, r);
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

test('trocar: payload errado do verificador chega ao destino, não confere e aborta antes do PAUSE', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_PAYLOAD_ERRADO: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /verificador de app no banco_novo difere da origem: nada pausado/);
    // Prova que o payload trocado de fato foi aplicado no destino (não só o hash inventado).
    assert.match(fs.readFileSync(path.join(v.vm, 'verificador-recebido.sql'), 'utf8'), /outro-salt/);
    assert.equal(v.contar('-c PAUSE'), 0, 'pausou com payload errado');
    assert.equal(v.contar('sed -i'), 0, 'host alterado com payload errado');
    nadaTrocado(v);
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
    assert.match(r.stderr, /assinatura não criada no banco_novo: nada pausado/);
    assert.equal(v.contar('-c PAUSE'), 0);
    assert.equal(v.contar('#sql:limpa'), 0, 'assinatura que não foi criada não tem o que remover');
    assert.equal(v.contar('rm -f /tmp/phati-replicador.pgpass'), 1, 'passfile gravado e não removido no aborto');
    assert.equal(fs.existsSync(path.join(v.vm, 'pgpass-gravado')), false, 'passfile sobrou no banco_novo');
    nadaTrocado(v);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

// ---- modo da troca (S2a, spec 009 R15): `fisica` ainda não existe; `logica` soma compose.troca-logica.yaml ----

// ---- modo físico (S2b): standby por pg_basebackup, sem preparar e sem reiniciar a origem ----
const fisica = (v, extra = {}) => v.rodar(['trocar'], extra);
const sobeOrigem = (v) => v.lerChamadas().filter((linha) => /up -d --no-deps banco( |$)/.test(linha)).length;
// Prova de que o slot saiu: o dublê de `pg_drop_replication_slot` só cria `.slot-removido` quando o drop passa.
const slotRemovido = (v) => fs.existsSync(path.join(v.vm, '.slot-removido'));

test('trocar --modo fisica feliz: ordem exata, sem preparar, sem setval, sem verificador, origem sem restart, sem segredo', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['trocar', '--modo', 'fisica']);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /^trocar_ok pausa_ms=\d+$/m);
    const trechos = ['pg_dump', 'printf', 'pg_basebackup', 'up -d --no-deps banco_novo', 'pg_stat_wal_receiver', '-c PAUSE',
      'pg_wal_lsn_diff', 'pg_promote', 'sed -i', '-c RELOAD', '-c RESUME', 'pg_drop_replication_slot'];
    const ordem = trechos.map((t) => v.indice(t));
    for (let i = 0; i < ordem.length; i++) assert.ok(ordem[i] >= 0, `falta ${trechos[i]}: ${ordem}`);
    for (let i = 1; i < ordem.length; i++) assert.ok(ordem[i] > ordem[i - 1], `ordem quebrada em ${trechos[i]}: ${ordem}`);
    assert.equal(v.contar('-e PHATI_BANCO_REPLICADOR_SENHA'), 1, 'papeis.sql roda uma vez na origem no modo físico');
    assert.ok(v.indice('-e PHATI_BANCO_REPLICADOR_SENHA') < v.indice('pg_basebackup'), 'papel antes do basebackup');
    assert.ok(slotRemovido(v), 'slot precisa sair de fato');
    assert.equal(v.contar('#sql:setval'), 0);
    assert.equal(v.contar('#sql:leitura-verificador'), 0);
    assert.equal(v.contar('#sql:verificador'), 0);
    assert.equal(sobeOrigem(v), 0, 'a origem não sobe nem reinicia');
    assert.match(v.registro(), /troca-banco trocar OK modo=fisica pausa_ms=\d+ destino=banco_novo/);
    assert.ok(v.env().includes('PHATI_BANCO_DESTINO=banco_novo'));
    assert.equal(v.bancoAtivo(), 'banco_novo\n');
    semSegredo(v, r);
    semVerificador(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar sem --modo é físico: roda o standby e não pede o override lógico', () => {
  const v = criarVm();
  try {
    const r = fisica(v);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contar('troca-logica'), 0);
    assert.equal(v.contar('up -d --no-deps banco_novo'), 1);
  } finally {
    v.limpar();
  }
});

test('trocar físico recusa volume não vazio antes do backup e de qualquer PAUSE', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_VOLUME_CHEIO: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /dados_banco_novo não está vazio/);
    assert.equal(v.contar('pg_dump'), 0);
    assert.equal(v.contar('pg_basebackup'), 0);
    assert.equal(v.contar('-c PAUSE'), 0);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar físico recusa major diferente da imagem, sem backup e sem PAUSE', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_VERSAO_NOVO: '17.2' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /major diferente: use --modo logica/);
    assert.equal(v.contar('pg_dump'), 0);
    assert.equal(v.contar('pg_basebackup'), 0);
    assert.equal(v.contar('-c PAUSE'), 0);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar físico sem a senha do replicador recusa antes de qualquer chamada de troca', () => {
  const v = criarVm({ comSenha: false });
  try {
    const r = fisica(v);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /PHATI_BANCO_REPLICADOR_SENHA ausente/);
    assert.equal(v.contar('pg_basebackup'), 0);
    assert.equal(v.contar('-c PAUSE'), 0);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar físico: regra do pg_hba que não entra aborta antes do basebackup, sem PAUSE', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_HBA_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /não consegui acrescentar a regra de replicação/);
    assert.equal(v.contar('pg_basebackup'), 0);
    assert.equal(v.contar('-c PAUSE'), 0);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar físico: pg_basebackup falha sem vazar a senha, remove o slot e avisa o volume; nada pausado', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_BASE_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /pg_basebackup falhou/);
    assert.match(r.stderr, /remova o volume dados_banco_novo/);
    assert.equal(v.contar('up -d --no-deps banco_novo'), 0);
    assert.ok(slotRemovido(v), 'slot parcial precisa ser removido');
    assert.equal(v.contar('stop banco_novo'), 0, 'standby não iniciado: sem parada');
    assert.equal(v.contar('-c PAUSE'), 0);
    nadaTrocado(v);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar físico: banco_novo que não entra em recovery aborta sem PAUSE e remove o slot', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_SEM_RECOVERY: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /não entrou em recovery/);
    assert.equal(v.contar('-c PAUSE'), 0);
    assert.ok(v.indice('stop banco_novo') >= 0 && v.indice('stop banco_novo') < v.indice('pg_drop_replication_slot'), 'standby parado antes do drop');
    assert.ok(slotRemovido(v), 'slot não foi removido de fato');
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar físico: atraso que não chega a zero faz RESUME, não promove nem troca o host, e remove o slot', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_LAG_FISICO: '5' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /atraso do banco_novo não chegou a zero/);
    assert.equal(v.contar('-c RESUME'), 2, 'RESUME nos dois PgBouncer');
    assert.equal(v.indice('pg_promote'), -1, 'não promove com atraso');
    assert.equal(v.indice('sed -i'), -1, 'não troca o host');
    assert.ok(v.indice('stop banco_novo') >= 0 && v.indice('stop banco_novo') < v.indice('pg_drop_replication_slot'), 'standby parado antes do drop');
    assert.ok(slotRemovido(v), 'slot não foi removido de fato');
    assert.equal(v.contar('rm -sfv'), 1, 'banco_novo removido no aborto');
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar físico: pg_promote falha: RESUME, host original, AVISO de descarte e banco_novo não removido', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_PROMOTE_FALHA: '1' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /pg_promote falhou: nada trocado/);
    assert.equal(v.indice('sed -i'), -1, 'host não trocado');
    assert.equal(v.contar('-c RESUME'), 2);
    assert.match(r.stderr, /AVISO: banco_novo foi promovido/);
    assert.equal(v.contar('rm -sfv'), 0, 'promovido não é removido sem o descarte');
    assert.equal(v.contar(REMOVE_DESTINO), 1, 'destino gravado antes do promote é removido no aborto');
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar físico: sed do host falha depois do promote: host restaurado, RESUME e AVISO de descarte', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_FALHA_UMA: 'sed -i' });
    assert.equal(r.status, 1);
    assert.ok(v.contar('s/host=banco_novo /host=banco /') >= 1, 'host volta ao original');
    assert.equal(v.contar('-c RESUME'), 2);
    assert.match(r.stderr, /descarte/);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('modo recusado sem Docker: valor fora de fisica e logica, --modo sem valor e argumento a mais em preparar', () => {
  const v = criarVm();
  try {
    for (const args of [['trocar', '--modo', 'xyz'], ['trocar', '--modo', ''], ['trocar', '--modo=LOGICA'], ['trocar', '--modo']]) {
      const r = v.rodar(args);
      assert.equal(r.status, 1, JSON.stringify(args));
      assert.match(r.stderr, /modo inválido|--modo exige valor/, JSON.stringify(args));
    }
    const extra = v.rodar(['preparar', '--modo', 'logica']);
    assert.equal(extra.status, 1);
    assert.match(extra.stderr, /preparar não aceita argumentos/);
    assert.deepEqual(v.lerChamadas(), []);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('PHATI_TROCA_MODO: logica basta sem a opção; a opção --modo tem prioridade; valor inválido recusa', () => {
  const v = criarVm();
  try {
    const pelaVariavel = v.rodar(['trocar'], { PHATI_TROCA_MODO: 'logica', DUBLE_WAL: 'logical' });
    assert.equal(pelaVariavel.status, 0, pelaVariavel.stderr);
    const prioridade = v.rodar(['trocar', '--modo', 'logica'], { PHATI_TROCA_MODO: 'fisica', DUBLE_WAL: 'logical' });
    assert.equal(prioridade.status, 0, `a variável fisica não pode vencer --modo logica: ${prioridade.stderr}`);
    const invalido = v.rodar(['trocar'], { PHATI_TROCA_MODO: 'xyz' });
    assert.equal(invalido.status, 1);
    assert.match(invalido.stderr, /modo inválido/);
  } finally {
    v.limpar();
  }
});

test('trocar --modo logica: o up do banco_novo e o wal_level levam o override depois dos dois arquivos de sempre', () => {
  const v = criarVm();
  try {
    const r = trocar(v);
    assert.equal(r.status, 0, r.stderr);
    const sobe = v.lerChamadas().find((linha) => linha.includes('up -d --no-deps banco_novo'));
    assert.ok(sobe, 'banco_novo não subiu');
    assert.match(sobe, /compose\.implantacao\.yaml .*compose\.troca-logica\.yaml/);
    const wal = v.lerChamadas().filter((linha) => linha.includes('SHOW wal_level'));
    assert.ok(wal.length > 0);
    for (const linha of wal) assert.match(linha, /compose\.troca-logica\.yaml/);
  } finally {
    v.limpar();
  }
});

test('preparar é sempre lógico: o up do banco e o wal_level levam o override, sem --modo', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['preparar']);
    assert.equal(r.status, 0, r.stderr);
    const sobe = v.lerChamadas().find((linha) => linha.includes('up -d --no-deps banco'));
    assert.match(sobe, /compose\.implantacao\.yaml .*compose\.troca-logica\.yaml/);
    for (const linha of v.lerChamadas().filter((l) => l.includes('SHOW wal_level'))) {
      assert.match(linha, /compose\.troca-logica\.yaml/);
    }
  } finally {
    v.limpar();
  }
});

// ---- destino no volume pgb_cfg (achado P1): gravado depois do RELOAD e antes do RESUME; removido no aborto ----
// O arquivo `/cfg/banco-destino` é lido pelo entrypoint do PgBouncer ao subir: sem ele o contêiner volta à origem.
const GRAVA_DESTINO = 'banco_novo > /cfg/banco-destino';
const REMOVE_DESTINO = 'rm -f /cfg/banco-destino';

test('trocar logica: grava banco-destino pelo pgb_auth depois do RELOAD e antes do RESUME', () => {
  const v = criarVm();
  try {
    const r = trocar(v);
    assert.equal(r.status, 0, r.stderr);
    const reload = v.indice('-c RELOAD');
    const grava = v.indice(GRAVA_DESTINO);
    const resume = v.indice('-c RESUME');
    assert.ok(reload >= 0 && grava > reload, `gravação ${grava} antes do RELOAD ${reload}`);
    assert.ok(resume > grava, `RESUME ${resume} antes da gravação ${grava}`);
    assert.equal(v.contar(GRAVA_DESTINO), 1, 'gravado uma vez');
    const linha = v.lerChamadas().find((l) => l.includes(GRAVA_DESTINO));
    assert.match(linha, /run --rm --no-deps .*--entrypoint sh pgb_auth -c/, 'one-off do pgb_auth, sem subir dependências');
    assert.equal(v.contar(REMOVE_DESTINO), 0, 'no sucesso o arquivo fica');
    assert.equal(r.stdout.match(/trocar_ok/g).length, 1);
  } finally {
    v.limpar();
  }
});

test('trocar fisica: grava banco-destino depois do RELOAD e antes do RESUME', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['trocar', '--modo', 'fisica']);
    assert.equal(r.status, 0, r.stderr);
    // E4: a gravação sai logo antes do promote (com o banco_novo ainda standby), não depois do RELOAD.
    const lag = v.indice('pg_last_wal_replay_lsn');
    const grava = v.indice(GRAVA_DESTINO);
    const promove = v.indice('pg_promote');
    const reload = v.indice('-c RELOAD');
    assert.ok(lag >= 0 && grava > lag, `gravação ${grava} antes do atraso zero ${lag}`);
    assert.ok(promove > grava, `pg_promote ${promove} antes da gravação ${grava}`);
    assert.ok(reload > promove, `RELOAD ${reload} antes do promote ${promove}`);
    assert.ok(v.indice('-c RESUME') > grava, 'RESUME depois da gravação');
    assert.equal(v.contar(GRAVA_DESTINO), 1);
    assert.equal(v.contar(REMOVE_DESTINO), 0);
  } finally {
    v.limpar();
  }
});

test('trocar logica: falha da gravação aborta com host restaurado, arquivo removido e RESUME', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_GRAVA_FALHA: '1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /não consegui gravar o destino/);
    assert.equal(v.contar(RESTAURA), 2, 'host volta ao original nos dois PgBouncer');
    const restaura = v.indice(RESTAURA);
    const removeu = v.indice(REMOVE_DESTINO);
    assert.ok(removeu > restaura, 'arquivo removido depois do sed de volta');
    assert.ok(v.indice('-c RESUME') > removeu, 'RESUME depois da remoção');
    assert.equal(v.contar('-c RESUME'), 2);
    nadaTrocado(v);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar fisica: falha da gravação antes do promote aborta sem trocar o host, remove o arquivo e faz RESUME', () => {
  const v = criarVm();
  try {
    const r = v.rodar(['trocar', '--modo', 'fisica'], { DUBLE_GRAVA_FALHA: '1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(v.contar(RESTAURA), 0, 'host nunca foi trocado: nada a restaurar');
    assert.equal(v.indice('pg_promote'), -1, 'não promove sem destino gravado');
    assert.equal(v.contar(REMOVE_DESTINO), 1, 'arquivo removido no aborto');
    assert.equal(v.contar('-c RESUME'), 2);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar logica: RELOAD que falha antes da gravação restaura o host sem rm (gravação não tentada)', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_FALHA_UMA: '-c RELOAD' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(v.contar(GRAVA_DESTINO), 0, 'a gravação nunca ocorreu');
    assert.equal(v.contar(RESTAURA), 2, 'host volta ao original');
    assert.equal(v.contar(REMOVE_DESTINO), 0, 'sem tentativa de gravação o aborto não chama o one-off de remoção');
    assert.equal(v.contar('-c RESUME'), 2);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar logica: falha do rm no aborto vira AVISO, sem mudar o rc da falha original', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_GRAVA_FALHA: '1', DUBLE_REMOVE_FALHA: '1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /AVISO: não consegui remover \/cfg\/banco-destino/);
    assert.equal(v.contar('-c RESUME'), 2, 'RESUME mesmo com a remoção falha');
  } finally {
    v.limpar();
  }
});

// ---- Correções da revisão B1 (ensaio real e achados da PR #81) ----

test('trocar físico: build do banco_novo roda antes do volume e da versão; progresso no stdout do run não quebra a troca', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_PROGRESSO: '1' });
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.match(r.stdout, /^trocar_ok pausa_ms=\d+$/m);
    const build = v.indice('build banco_novo');
    assert.ok(build >= 0, 'build do banco_novo não ocorreu');
    assert.ok(build < v.indice('ls -A /var/lib/postgresql'), 'build depois do volume');
    assert.ok(build < v.indice('postgres --version'), 'build depois da versão');
  } finally {
    v.limpar();
  }
});

test('trocar físico: build do banco_novo que falha recusa antes do volume, sem backup e sem PAUSE', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_BUILD_FALHA: '1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /ERRO: build do banco_novo falhou: nada foi alterado/);
    assert.equal(v.contar('ls -A'), 0);
    assert.equal(v.contar('pg_dump'), 0);
    assert.equal(v.contar('pg_basebackup'), 0);
    assert.equal(v.contar('-c PAUSE'), 0);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('trocar físico: ALTER SYSTEM RESET do primary_conninfo vem depois do promote e antes do host', () => {
  const v = criarVm();
  try {
    const r = fisica(v);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(v.contar('#sql:conninfo'), 1, 'RESET aplicado uma vez no banco_novo');
    const promote = v.indice('pg_promote');
    const reset = v.indice('#sql:conninfo');
    const host = v.indice('sed -i');
    assert.ok(promote >= 0 && reset > promote, `RESET antes do promote: ${promote} ${reset}`);
    assert.ok(host > reset, `host antes do RESET: ${reset} ${host}`);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar físico: falha do ALTER SYSTEM RESET vira AVISO com o comando de recuperação e a troca segue', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_CONNINFO_FALHA: '1' });
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.match(r.stdout, /^trocar_ok pausa_ms=\d+$/m);
    assert.match(r.stderr, /AVISO: não consegui limpar primary_conninfo no banco_novo: rode ALTER SYSTEM RESET primary_conninfo; ALTER SYSTEM RESET primary_slot_name; SELECT pg_reload_conf\(\); no banco_novo/);
    assert.equal(v.contar(DIREITO), 2, 'host trocado: o banco_novo já é primário');
    assert.equal(v.contar('-c RESUME'), 2);
    assert.equal(v.bancoAtivo(), 'banco_novo\n');
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar lógico: PHATI_BANCO_NOME (phati_hml) vai a todas as conexões e à assinatura, sem phati fixo', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { PHATI_BANCO_NOME: 'phati_hml' });
    assert.equal(r.status, 0, r.stdout + r.stderr);
    const fixo = v.lerChamadas().filter((l) => /-d phati(?![a-z_])/.test(l));
    assert.deepEqual(fixo, [], 'conexão com phati fixo');
    assert.equal(v.contar('--schema-only -d phati_hml'), 1, 'pg_dump no banco configurado');
    assert.ok(v.contar('-d phati_hml') >= 5, 'conexões no banco configurado');
    const sqlAssinatura = fs.readFileSync(path.join(v.vm, 'assinatura.sql'), 'utf8');
    assert.match(sqlAssinatura, /dbname=phati_hml user=/);
    assert.doesNotMatch(sqlAssinatura, /dbname=phati(?![a-z_])/);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('trocar lógico: sem PHATI_BANCO_NOME no ambiente, o nome vem do .env; sem nada, o padrão é phati', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, '.env'), `PHATI_BANCO_NOME=phati_env\nPHATI_BANCO_APP_USUARIO=app\nPHATI_BANCO_REPLICADOR_SENHA=${SEGREDO}\n`, { mode: 0o640 });
    const r = trocar(v);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.ok(v.contar('-d phati_env') >= 1, 'nome do .env nas conexões');
    assert.equal(v.contar('-d phati '), 0, 'sem phati fixo');
  } finally {
    v.limpar();
  }
  const padrao = criarVm();
  try {
    const r = trocar(padrao);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.ok(padrao.contar('-d phati ') >= 1, 'padrão phati quando não há nome');
  } finally {
    padrao.limpar();
  }
});

test('trocar lógico: PHATI_BANCO_NOME inválido (ponto e vírgula) recusa antes de qualquer chamada Docker', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { PHATI_BANCO_NOME: 'phati;drop' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /ERRO: PHATI_BANCO_NOME inválido/);
    assert.equal(v.lerChamadas().length, 0, 'nenhuma chamada ao Docker');
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

// ---- Lote C (review do CodeRabbit): restauração parcial do host, limite no PAUSE, temporários, estado parcial e marcador ----
const chamadaPgb = (v, svc, sql) => v.lerChamadas().filter((l) => l.includes(`exec -T ${svc} `) && l.includes(`-c ${sql}`)).length;
const temporarios = (v, prefixo) => fs.readdirSync(v.vm).filter((nome) => nome.startsWith(prefixo));
// `mv` de mentira no PATH: falha quando o último argumento termina em DUBLE_MV_FALHA (o destino da gravação atômica).
function shimMv(v) {
  const real = fs.existsSync('/usr/bin/mv') ? '/usr/bin/mv' : '/bin/mv';
  const dir = path.join(v.vm, 'shim');
  fs.mkdirSync(dir);
  fs.writeFileSync(
    path.join(dir, 'mv'),
    `#!/usr/bin/env bash\nif [[ -n "\${DUBLE_MV_FALHA:-}" && "\${@: -1}" == *"/$DUBLE_MV_FALHA" ]]; then exit 1; fi\nexec ${real} "$@"\n`,
    { mode: 0o755 },
  );
  return unix(dir);
}

test('C1: restauração do host falha só em pgb1 → RESUME só no pgb2 e AVISO com o comando de recuperação', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_GRAVA_FALHA: '1', DUBLE_RESTAURA_FALHA: 'pgb1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(chamadaPgb(v, 'pgb1', 'RESUME'), 0, 'pgb1 com host trocado não confirmado foi retomado');
    assert.equal(chamadaPgb(v, 'pgb2', 'RESUME'), 1, 'pgb2 com host de volta não foi retomado');
    assert.match(r.stderr, /AVISO: pgb1 segue em PAUSE/);
    assert.ok(r.stderr.includes("sed -i 's/host=banco_novo /host=banco /' /tmp/pgb/pgb1/pgbouncer.ini"), r.stderr);
    assert.ok(r.stderr.includes('-c RESUME'), 'AVISO sem o RESUME de recuperação');
    nadaTrocado(v);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('C1: restauração confirmada nas duas instâncias → RESUME nas duas e sem AVISO de host', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_GRAVA_FALHA: '1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(chamadaPgb(v, 'pgb1', 'RESUME'), 1);
    assert.equal(chamadaPgb(v, 'pgb2', 'RESUME'), 1);
    assert.doesNotMatch(r.stderr, /segue em PAUSE/);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('C2: PAUSE pendurado estoura o limite → aborta com RESUME nas duas e host intacto', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_PAUSE_PENDURA: 'pgb1', PHATI_PAUSA_LIMITE: '1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /não consegui pausar pgb1 pelo console/);
    assert.equal(chamadaPgb(v, 'pgb1', 'RESUME'), 1, 'pgb1 não retomado depois do estouro');
    assert.equal(chamadaPgb(v, 'pgb2', 'RESUME'), 1, 'pgb2 não retomado depois do aborto');
    assert.equal(v.contar(DIREITO), 0, 'host trocado com PAUSE sem confirmação');
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('C2: PHATI_PAUSA_LIMITE inválido recusa antes de qualquer chamada Docker', () => {
  for (const valor of ['abc', '0', '1.5']) {
    const v = criarVm();
    try {
      const r = trocar(v, { PHATI_PAUSA_LIMITE: valor });
      assert.equal(r.status, 1, valor);
      assert.match(r.stderr, /ERRO: PHATI_PAUSA_LIMITE inválida/, valor);
      assert.equal(v.lerChamadas().length, 0, `chamada Docker com limite ${valor}`);
    } finally {
      v.limpar();
    }
  }
});

test('C2: PAUSE leva PHATI_PAUSA_LIMITE e RESUME leva 20 s, pelo comando de PHATI_TIMEOUT', () => {
  const v = criarVm();
  try {
    const espiao = path.join(v.vm, 'timeout-espiao.sh');
    fs.writeFileSync(espiao, '#!/usr/bin/env bash\necho "limite $*" >> "$CHAMADAS"\nshift\nexec "$@"\n', { mode: 0o755 });
    const r = trocar(v, { PHATI_TIMEOUT: unix(espiao), PHATI_PAUSA_LIMITE: '30' });
    assert.equal(r.status, 0, r.stdout + r.stderr);
    const linhas = v.lerChamadas();
    assert.equal(linhas.filter((l) => l.startsWith('limite 30 ') && l.includes('-c PAUSE')).length, 2, 'PAUSE sem o limite');
    assert.equal(linhas.filter((l) => l.startsWith('limite 20 ') && l.includes('-c RESUME')).length, 2, 'RESUME sem o limite');
  } finally {
    v.limpar();
  }
});

test('C2: sem o comando de timeout, AVISO e segue sem limite', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { PHATI_TIMEOUT: 'nao-existe-timeout-9x' });
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.match(r.stderr, /AVISO: 'nao-existe-timeout-9x' ausente: sem limite de tempo/);
    assert.match(r.stdout, /^trocar_ok /m);
  } finally {
    v.limpar();
  }
});

test('C3: mv do .env falha → temporário removido e .env intacto', () => {
  const v = criarVm();
  try {
    const original = v.env();
    const r = trocar(v, { PATH: `${shimMv(v)}:${process.env.PATH}`, DUBLE_MV_FALHA: '.env' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(v.env(), original, '.env alterado');
    assert.deepEqual(temporarios(v, '.env.'), [], 'temporário do .env sobrou');
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('C3: mv do banco-ativo falha → temporário removido e nada persistido', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { PATH: `${shimMv(v)}:${process.env.PATH}`, DUBLE_MV_FALHA: 'banco-ativo' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.deepEqual(temporarios(v, '.banco-ativo.'), [], 'temporário do banco-ativo sobrou');
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('C4: .env com banco_novo e banco-ativo ausente → completa o banco-ativo, sem Docker nem pausa', () => {
  const v = criarVm();
  try {
    fs.appendFileSync(path.join(v.vm, '.env'), 'PHATI_BANCO_DESTINO=banco_novo\n');
    const r = trocar(v);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.match(r.stdout, /^trocar_ok ja_trocado=1 completou=banco-ativo$/m);
    assert.deepEqual(v.lerChamadas(), []);
    assert.equal(v.bancoAtivo(), 'banco_novo\n');
    assert.match(v.registro(), /troca-banco trocar OK ja_trocado=1 completou=banco-ativo$/m);
  } finally {
    v.limpar();
  }
});

test('C4: banco-ativo com banco_novo e .env sem destino → completa o .env, sem Docker nem pausa', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco_novo\n');
    const r = trocar(v);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.match(r.stdout, /^trocar_ok ja_trocado=1 completou=env$/m);
    assert.deepEqual(v.lerChamadas(), []);
    assert.match(v.env(), /^PHATI_BANCO_DESTINO=banco_novo$/m);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('C4: falha ao gravar o .env depois do banco-ativo → a próxima execução completa o .env', () => {
  const v = criarVm();
  try {
    const r1 = trocar(v, { PATH: `${shimMv(v)}:${process.env.PATH}`, DUBLE_MV_FALHA: '.env' });
    assert.equal(r1.status, 1, r1.stdout + r1.stderr);
    assert.equal(v.bancoAtivo(), 'banco_novo\n', 'banco-ativo deveria ter sido gravado antes do .env');
    assert.doesNotMatch(v.env(), /PHATI_BANCO_DESTINO=/);
    const antes = v.lerChamadas().length;
    const r2 = trocar(v);
    assert.equal(r2.status, 0, r2.stdout + r2.stderr);
    assert.match(r2.stdout, /^trocar_ok ja_trocado=1 completou=env$/m);
    assert.equal(v.lerChamadas().length, antes, 'a completagem chamou o Docker');
    assert.match(v.env(), /^PHATI_BANCO_DESTINO=banco_novo$/m);
    assert.equal(fs.existsSync(path.join(v.vm, 'troca-banco-em-curso')), false, 'marcador sobrou depois de completar');
  } finally {
    v.limpar();
  }
});

test('C4: marcador de troca interrompida recusa sem Docker e não é removido', () => {
  const v = criarVm();
  try {
    const marcador = path.join(v.vm, 'troca-banco-em-curso');
    fs.writeFileSync(marcador, 'modo=logica passo=pausa\n');
    const r = trocar(v);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(
      r.stderr,
      /troca anterior interrompida \(marcador .*troca-banco-em-curso\): confira os PgBouncer \(SHOW DATABASES, estado de pausa\), a origem e o banco_novo, e remova o marcador depois de reconciliar/,
    );
    assert.equal(v.lerChamadas().length, 0, 'chamada Docker com marcador presente');
    assert.ok(fs.existsSync(marcador), 'o marcador foi removido pela recusa');
  } finally {
    v.limpar();
  }
});

test('C4: marcador some no sucesso da troca', () => {
  const v = criarVm();
  try {
    const r = trocar(v);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.equal(fs.existsSync(path.join(v.vm, 'troca-banco-em-curso')), false);
  } finally {
    v.limpar();
  }
});

test('C4: marcador some no aborto completo (RESUME feito, sem o ponto sem volta)', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_LAG: 'f' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(fs.existsSync(path.join(v.vm, 'troca-banco-em-curso')), false, 'marcador sobrou no aborto completo');
  } finally {
    v.limpar();
  }
});

test('C4: marcador sobra quando o RESUME falha depois do ponto sem volta (esperado)', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_RESUME_FALHA: 'pgb1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(fs.existsSync(path.join(v.vm, 'troca-banco-em-curso')), true, 'marcador removido com troca comitada');
  } finally {
    v.limpar();
  }
});

// ---- Lote E (review): físico sem papel, sinais, slot, destino antes do promote, banco-logico, .env, lag, RESUME, remoção ----
const RELOAD_PGB1 = 'exec -T pgb1 psql -X -q -h /tmp/pgb/pgb1 -p 6432 -U pgbouncer pgbouncer -c RELOAD';
const RESUME_PGB1 = 'exec -T pgb1 psql -X -q -h /tmp/pgb/pgb1 -p 6432 -U pgbouncer pgbouncer -c RESUME';
const RESUME_PGB2 = 'exec -T pgb2 psql -X -q -h /tmp/pgb/pgb2 -p 6432 -U pgbouncer pgbouncer -c RESUME';
const escreverEnv = (v, linhas) => fs.writeFileSync(path.join(v.vm, '.env'), `${linhas.join('\n')}\n`, { mode: 0o640 });
const pgpassRemovido = (v) => fs.readFileSync(path.join(v.vm, 'pgpass-removido'), 'utf8');

test('E1: físico aplica o papeis.sql na origem antes do basebackup (origem sem o papel até o SQL)', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_REPLICADOR: '0' });
    assert.equal(r.status, 0, r.stderr);
    const sql = v.indice('-e PHATI_BANCO_REPLICADOR_SENHA');
    const checa = v.indice('rolreplication');
    const base = v.indice('pg_basebackup');
    assert.ok(sql >= 0 && checa > sql && base > checa, `ordem: ${sql} ${checa} ${base}`);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('E1: SQL do papel replicador falha → aborta antes do PAUSE e do basebackup, saída suprimida sem a senha', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_SQL_FALHA: '1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /SQL do papel replicador falhou \(saída suprimida: contém a senha\): nada pausado/);
    assert.equal(v.contar('pg_basebackup'), 0);
    assert.equal(v.contar('-c PAUSE'), 0);
    nadaTrocado(v);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('E2: SIGTERM depois do primeiro RELOAD → host restaurado nos dois PgBouncer antes do RESUME, rc 1', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_SINAL: RELOAD_PGB1 });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /ERRO: interrompido por sinal/);
    assert.equal(v.contar(RESTAURA), 2, 'host volta ao original nos dois PgBouncer');
    assert.ok(v.indice(RESTAURA) > v.indice(RELOAD_PGB1), 'restauração depois do RELOAD interrompido');
    assert.ok(v.indice('-c RESUME') > v.indice(RESTAURA), 'RESUME depois da restauração');
    assert.equal(v.contar('-c RESUME'), 2);
    nadaTrocado(v);
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('E2: sinal com restauração que falha em pgb2 → RESUME só em pgb1 e AVISO de pgb2 em PAUSE', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_SINAL: RELOAD_PGB1, DUBLE_RESTAURA_FALHA: 'pgb2' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(chamadaPgb(v, 'pgb1', 'RESUME'), 1, 'pgb1 com host confirmado foi retomado');
    assert.equal(chamadaPgb(v, 'pgb2', 'RESUME'), 0, 'pgb2 sem host confirmado não foi retomado');
    assert.match(r.stderr, /AVISO: pgb2 segue em PAUSE/);
  } finally {
    v.limpar();
  }
});

test('E2: sinal depois do ponto sem volta (RESUME iniciado) não restaura o host e deixa o marcador', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_SINAL: RESUME_PGB1 });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /ERRO: interrompido por sinal/);
    assert.equal(v.contar(RESTAURA), 0, 'depois do ponto sem volta o host não volta');
    assert.equal(fs.existsSync(path.join(v.vm, 'troca-banco-em-curso')), true, 'marcador fica com a troca comitada');
  } finally {
    v.limpar();
  }
});

test('E3: aborto com standby iniciado para o standby, espera o slot ficar inativo e só então remove o slot', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_LAG_FISICO: '5' });
    assert.equal(r.status, 1, r.stderr);
    const para = v.indice('stop banco_novo');
    const espera = v.indice('SELECT active FROM pg_replication_slots');
    const drop = v.indice('pg_drop_replication_slot');
    assert.ok(para >= 0 && espera > para && drop > espera, `ordem: ${para} ${espera} ${drop}`);
    assert.ok(slotRemovido(v), 'slot precisa sair de fato');
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('E3: slot que não fica inativo depois de parar o standby não é zerado: AVISO com o comando, drop não tentado', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_LAG_FISICO: '5', DUBLE_SLOT_ATIVO: '1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /AVISO: não consegui remover o slot phati_troca_slot na origem/);
    assert.match(r.stderr, /SELECT pg_drop_replication_slot\('phati_troca_slot'\);/);
    assert.equal(slotRemovido(v), false, 'slot não foi removido');
    assert.equal(v.contar('pg_drop_replication_slot'), 0, 'drop não tentado com slot ativo');
  } finally {
    v.limpar();
  }
});

test('E4: pg_promote falha depois de a gravação do destino → arquivo removido e host intacto', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_PROMOTE_FALHA: '1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.ok(v.indice(GRAVA_DESTINO) < v.indice('pg_promote'), 'destino antes do promote');
    assert.equal(v.contar(REMOVE_DESTINO), 1, 'arquivo removido no aborto depois do promote');
    assert.equal(v.indice('sed -i'), -1, 'host não trocado');
  } finally {
    v.limpar();
  }
});

test('E5: trocar lógica com sucesso grava banco-logico; física não grava; lógica abortada não grava', () => {
  const v = criarVm();
  try {
    const r = trocar(v);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.equal(fs.existsSync(path.join(v.vm, 'banco-logico')), true, 'banco-logico ausente no sucesso lógico');
  } finally {
    v.limpar();
  }
  const f = criarVm();
  try {
    const r = fisica(f);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(fs.existsSync(path.join(f.vm, 'banco-logico')), false, 'físico não grava banco-logico');
  } finally {
    f.limpar();
  }
  const a = criarVm();
  try {
    const r = trocar(a, { DUBLE_LAG: 'f' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(fs.existsSync(path.join(a.vm, 'banco-logico')), false, 'aborto não grava banco-logico');
  } finally {
    a.limpar();
  }
});

test('E6: ler_env tira aspas duplas que cercam o valor, preserva espaço interno e não imprime a senha', () => {
  const v = criarVm();
  try {
    escreverEnv(v, ['PHATI_BANCO_NOME=phati', 'PHATI_BANCO_APP_USUARIO=app', 'PHATI_BANCO_REPLICADOR_SENHA="valor com espaço"']);
    const r = trocar(v);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.match(pgpassRemovido(v), /:replicador:valor com espaço\n/);
    assert.ok(!r.stdout.includes('valor com espaço') && !r.stderr.includes('valor com espaço'), 'senha impressa');
  } finally {
    v.limpar();
  }
});

test('E6: ler_env tira aspas simples que cercam o valor; a senha chega ao passfile sem as aspas', () => {
  const v = criarVm();
  try {
    escreverEnv(v, ['PHATI_BANCO_NOME=phati', 'PHATI_BANCO_APP_USUARIO=app', `PHATI_BANCO_REPLICADOR_SENHA='${SEGREDO}'`]);
    const r = trocar(v);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.match(pgpassRemovido(v), new RegExp(`:replicador:${SEGREDO}\\n`));
    assert.ok(!pgpassRemovido(v).includes("'"), 'aspas sobraram no passfile');
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('E6: ler_env sem aspas e com o nome do banco entre aspas duplas (phati_hml) vai a todas as conexões', () => {
  const v = criarVm();
  try {
    escreverEnv(v, ['PHATI_BANCO_NOME="phati_hml"', 'PHATI_BANCO_APP_USUARIO=app', `PHATI_BANCO_REPLICADOR_SENHA=${SEGREDO}`]);
    const r = trocar(v);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.ok(v.lerChamadas().some((l) => l.includes('-d phati_hml')), 'nome sem aspas nas conexões');
    assert.ok(!v.lerChamadas().some((l) => l.includes('"phati_hml"')), 'aspas sobraram no nome');
    semSegredo(v, r);
  } finally {
    v.limpar();
  }
});

test('E6: ler_env com destino entre aspas: o valor sem aspas é o que a recusa mostra; senha vazia entre aspas é ausente', () => {
  const v = criarVm();
  try {
    escreverEnv(v, ['PHATI_BANCO_NOME=phati', 'PHATI_BANCO_APP_USUARIO=app', `PHATI_BANCO_REPLICADOR_SENHA=${SEGREDO}`, 'PHATI_BANCO_DESTINO="banco_novo"']);
    const r = trocar(v);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /PHATI_BANCO_DESTINO é 'banco_novo', esperado banco/);
    assert.equal(v.contar('-c PAUSE'), 0, 'nada pausado');
    assert.equal(v.contar('up -d'), 0, 'nenhum contêiner subido');
  } finally {
    v.limpar();
  }
  const w = criarVm();
  try {
    escreverEnv(w, ['PHATI_BANCO_NOME=phati', 'PHATI_BANCO_APP_USUARIO=app', 'PHATI_BANCO_REPLICADOR_SENHA=""']);
    const r = trocar(w);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /PHATI_BANCO_REPLICADOR_SENHA ausente ou vazia/);
    assert.equal(w.lerChamadas().length, 0);
  } finally {
    w.limpar();
  }
});

test('E7: .env ilegível na gravação do destino aborta sem publicar o temporário; .env original intacto', () => {
  const v = criarVm();
  try {
    fs.writeFileSync(path.join(v.vm, 'banco-ativo'), 'banco_novo\n');
    const original = v.env();
    fs.chmodSync(path.join(v.vm, '.env'), 0o000);
    let r;
    try {
      r = trocar(v);
    } finally {
      fs.chmodSync(path.join(v.vm, '.env'), 0o640);
    }
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /não consegui ler o \.env: nada gravado/);
    assert.equal(v.env(), original, '.env alterado');
    assert.deepEqual(temporarios(v, '.env.'), [], 'temporário sobrou');
  } finally {
    v.limpar();
  }
});

test('E8: atraso negativo (replay à frente do LSN da origem) conta como zero no físico', () => {
  const v = criarVm();
  try {
    const r = fisica(v, { DUBLE_LAG_FISICO: '-3' });
    assert.equal(r.status, 0, r.stderr);
    assert.ok(v.indice('pg_promote') >= 0);
  } finally {
    v.limpar();
  }
});

test('E8: diff vazio ou texto não passa como zero: atraso não confirmado faz RESUME e aborta sem promover', () => {
  for (const valor of ['', 'x']) {
    const v = criarVm();
    try {
      const r = fisica(v, { DUBLE_LAG_FISICO: valor });
      assert.equal(r.status, 1, JSON.stringify(valor));
      assert.match(r.stderr, /atraso do banco_novo não chegou a zero/);
      assert.equal(v.indice('pg_promote'), -1, 'não promove sem atraso zero');
    } finally {
      v.limpar();
    }
  }
});

test('E9: RESUME que falha só em pgb2 → o EXIT tenta de novo só pgb2, sem repetir pgb1', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_FALHA_UMA: RESUME_PGB2 });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stderr, /AVISO: RESUME falhou em: pgb2/);
    assert.equal(chamadaPgb(v, 'pgb1', 'RESUME'), 1, 'pgb1 retomado uma vez');
    assert.equal(chamadaPgb(v, 'pgb2', 'RESUME'), 2, 'pgb2 tentado de novo, só ele');
  } finally {
    v.limpar();
  }
});

test('E10: remoção do destino falha 3 vezes → marcador da troca permanece e AVISO', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_GRAVA_FALHA: '1', DUBLE_REMOVE_FALHA: '1' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(v.contar(REMOVE_DESTINO), 3, 'três tentativas de remoção');
    assert.equal(fs.existsSync(path.join(v.vm, 'troca-banco-em-curso')), true, 'marcador saiu com o destino no volume');
    assert.match(r.stderr, /AVISO: não consegui remover \/cfg\/banco-destino/);
  } finally {
    v.limpar();
  }
});

test('E10: remoção do destino falha 1 vez e passa na 2ª → sem AVISO e o marcador sai', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_GRAVA_FALHA: '1', DUBLE_FALHA_UMA: REMOVE_DESTINO });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(v.contar(REMOVE_DESTINO), 2, 'segunda tentativa de remoção');
    assert.doesNotMatch(r.stderr, /AVISO: não consegui remover/);
    assert.equal(fs.existsSync(path.join(v.vm, 'troca-banco-em-curso')), false, 'marcador sobrou');
  } finally {
    v.limpar();
  }
});

test('E11: sed de restauração falha, mas o ini já está em host=banco → pgb2 confirmado e retomado', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_GRAVA_FALHA: '1', DUBLE_RESTAURA_FALHA: 'pgb2', DUBLE_INI_PGB2: 'banco' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(chamadaPgb(v, 'pgb2', 'RESUME'), 1, 'pgb2 com host já original não foi retomado');
    assert.doesNotMatch(r.stderr, /segue em PAUSE/);
    assert.ok(v.lerChamadas().some((l) => l.includes('grep -q host=banco ')), 'leitura do ini não foi feita');
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});

test('E11: sed de restauração falha e o ini está em host=banco_novo → pgb2 segue presa, com AVISO', () => {
  const v = criarVm();
  try {
    const r = trocar(v, { DUBLE_GRAVA_FALHA: '1', DUBLE_RESTAURA_FALHA: 'pgb2', DUBLE_INI_PGB2: 'banco_novo' });
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(chamadaPgb(v, 'pgb2', 'RESUME'), 0, 'pgb2 com host trocado não confirmado foi retomado');
    assert.match(r.stderr, /AVISO: pgb2 segue em PAUSE/);
    nadaTrocado(v);
  } finally {
    v.limpar();
  }
});
