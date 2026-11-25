#!/usr/bin/env node
// Suite do implantacao-gate.
//
// Metade negativa é a maior: um gate que bloqueia leitura, lint ou `gh workflow run` é desligado na
// primeira vez que atrapalha. Os casos liberados existem para isso. Os casos de desembrulho (rtk, sudo,
// bash -c, ssh) existem porque são a forma real de escapar de uma regra que só olha o texto do comando.

'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const HOOK = path.join(__dirname, 'implantacao-gate.js');

// Roda o hook como o Claude Code faz: payload JSON no stdin.
// Devolve { decisao, regra, motivo } ou null (passou). Falha se o hook sair com código diferente de 0.
function rodar(comando, raw) {
  const entrada = raw ?? JSON.stringify({
    hook_event_name: 'PreToolUse',
    tool_name: 'Bash',
    cwd: __dirname,
    tool_input: { command: comando },
  });
  const r = spawnSync('node', [HOOK], { input: entrada, encoding: 'utf8' });
  assert.equal(r.status, 0, `hook saiu com ${r.status}: ${r.stderr}`);
  if (!r.stdout.trim()) return null;
  const saida = JSON.parse(r.stdout).hookSpecificOutput;
  return {
    decisao: saida.permissionDecision,
    regra: saida.permissionDecisionReason.match(/\[implantacao-gate\/([^\]]+)\]/)?.[1] ?? null,
    motivo: saida.permissionDecisionReason,
  };
}

function assertNegado(resultado, comando) {
  assert.ok(resultado, `esperava deny para: ${comando}, hook passou`);
  assert.equal(resultado.decisao, 'deny', comando);
  assert.equal(resultado.regra, 'implantar-direto', comando);
  assert.match(resultado.motivo, /gh workflow run implantar --ref main -f sha=<SHA>/, comando);
}

function assertPergunta(resultado, comando) {
  assert.ok(resultado, `esperava ask para: ${comando}, hook passou`);
  assert.equal(resultado.decisao, 'ask', comando);
  assert.equal(resultado.regra, 'trocar-banco', comando);
}

// --- NEGA: execução direta de implantar.sh, restaurar.sh e backup.sh ---

const NEGADOS = [
  'sudo -n /opt/phati/bin/implantar.sh sha',
  'bash scripts/implantar.sh x',
  'rtk bash -lc "sudo scripts/restaurar.sh"',
  'scripts/implantar.sh abc',
  './scripts/implantar.sh abc',
  '/opt/phati/bin/implantar.sh reverter',
  'rtk sudo /opt/phati/bin/backup.sh cron',
  'sh -c "scripts/implantar.sh x"',
  'sudo -u root /opt/phati/bin/implantar.sh sha',
  'cd /x && sudo -n scripts/implantar.sh sha',
  'echo ok; ./scripts/implantar.sh x',
  'echo "$(bash scripts/backup.sh)"',
  'bash -lc "cd /x && bash scripts/implantar.sh sha"',
  'ssh maruko "sudo /opt/phati/bin/restaurar.sh arq RESTAURAR"',
  'rtk bypass bash scripts/implantar.sh sha',
  'bash scripts/trocar-banco.sh x && bash scripts/implantar.sh y',
  // furos medidos: verbos que executam o argumento, embrulhos, stdin e symlink
  'source scripts/implantar.sh',
  '. scripts/implantar.sh',
  'eval "scripts/implantar.sh x"',
  'timeout 5 scripts/implantar.sh x',
  'echo scripts/implantar.sh | bash',
  'bash <<< "scripts/implantar.sh x"',
  'xargs scripts/implantar.sh',
  'ssh -o RemoteCommand="scripts/implantar.sh x" h',
  'ln -s scripts/implantar.sh /tmp/x; /tmp/x',
  'env -u HOME scripts/implantar.sh x',
  'exec -a nome scripts/implantar.sh x',
  'sudo -u root env -u X bash scripts/implantar.sh x',
  'cat scripts/implantar.sh | sh',
  'bash <(cat scripts/implantar.sh)',
  'source <(cat scripts/implantar.sh)',
  "echo 'scripts/implantar.sh' | bash",
  'sed -i s/a/b/ scripts/implantar.sh',
  'rtk rg --pre bash scripts/implantar.sh x',
  // texto de mensagem não executa, mas a substituição dentro dele executa
  'git commit -m "$(scripts/implantar.sh x)"',
  'gh pr create --body "$(bash scripts/implantar.sh x)"',
  'git commit -F - <<\'FIM\'\n$(scripts/implantar.sh x)\nFIM',
  // segundo segmento executa mesmo com o primeiro sendo git add
  'git add x; scripts/implantar.sh y',
  // checagem de sintaxe com rtk libera só o -n; qualquer outra opção ou o script em execução nega
  'rtk bash scripts/implantar.sh x',
  'rtk bash -c "scripts/implantar.sh x"',
  'rtk bash -x scripts/implantar.sh',
  'rtk bash -n scripts/implantar.sh; rtk bash scripts/implantar.sh x',
  // aspas: o corte respeita aspas, mas o conteúdo citado continua examinado quando é executado
  'echo "a|b"; scripts/implantar.sh x',
  'rtk rg "scripts/implantar.sh|y" f | bash',
  'echo "scripts/implantar.sh x" | bash',
  'bash -c "true; scripts/implantar.sh x"',
  "sh -c 'a | scripts/restaurar.sh'",
  'eval "true; scripts/implantar.sh x"',
  'rg "$(scripts/implantar.sh x)" f',
  'rtk rg "`scripts/implantar.sh x`" f',
  'ssh h "cd x && scripts/implantar.sh y"',
  'ssh h "cat x && scripts/implantar.sh y"',
  'bash -c "cat f | scripts/implantar.sh x"',
  "bash -c 'cat x; scripts/implantar.sh x'",
  'rtk rg "$(cat x; scripts/implantar.sh)" f',
  // aspas não fechadas: falha fechada, nega se citar o script
  'rtk rg "scripts/implantar.sh f',
  "rtk rg 'scripts/implantar.sh f",
  // aspa simples é literal para o shell que lê o texto, mas o texto citado é executado depois: continua negado
  "bash -c '$(scripts/implantar.sh x)'",
  "sh -c 'echo `scripts/restaurar.sh x`'",
  "eval '$(scripts/implantar.sh x)'",
  "ssh h '$(scripts/implantar.sh x)'",
  "echo '$(scripts/implantar.sh x)' | bash",
  "bash <<< '$(scripts/implantar.sh x)'",
  "xargs -I{} sh -c '$(scripts/implantar.sh {})'",
  "timeout 5 bash -c '$(scripts/implantar.sh x)'",
  "rtk sudo bash -lc 'true; scripts/implantar.sh x'",
  "bash <<'FIM'\n$(scripts/implantar.sh x)\nFIM",
  "trap '$(scripts/implantar.sh x)' EXIT",
  // aspa simples não esconde `$(` nem crase: o texto substituído é executado, então falha fechada
  "rtk rg '$(scripts/implantar.sh x)' f",
  "rtk rg '`scripts/implantar.sh x`' f",
];

for (const comando of NEGADOS) {
  test(`nega execução direta: ${comando}`, () => {
    assertNegado(rodar(comando), comando);
  });
}

// --- PERGUNTA: trocar-banco.sh não tem workflow ---

const PERGUNTAS = [
  'sudo -n /opt/phati/bin/trocar-banco.sh trocar',
  'bash scripts/trocar-banco.sh x',
  'ssh maruko "sudo /opt/phati/bin/trocar-banco.sh trocar"',
  'source scripts/trocar-banco.sh x',
  'echo scripts/trocar-banco.sh | sh',
];

for (const comando of PERGUNTAS) {
  test(`pergunta antes do trocar-banco: ${comando}`, () => {
    assertPergunta(rodar(comando), comando);
  });
}

// --- LIBERA: leitura, sintaxe, lint, teste e o próprio workflow ---

const LIBERADOS = [
  'rtk rg implantar.sh scripts',
  'bash -n scripts/implantar.sh',
  'bash -n /opt/phati/bin/implantar.sh',
  'rtk bash -n scripts/implantar.sh',
  'rtk sh -n scripts/restaurar.sh',
  'rtk bash -n -- scripts/implantar.sh',
  'rtk bash -ne scripts/implantar.sh',
  'rtk bash --norc -n scripts/implantar.sh',
  'rtk /bin/bash -n scripts/implantar.sh',
  'rtk bash -n "scripts/implantar.sh"',
  'rtk bash -n scripts/implantar.sh 2>&1',
  'rtk bash -n scripts/implantar.sh && echo ok',
  'rtk bypass bash -n scripts/implantar.sh',
  'rtk sudo bash -n scripts/implantar.sh',
  'gh workflow run implantar -f sha=abc',
  'node --test scripts/implantar.test.js',
  'cat scripts/implantar.sh',
  'shellcheck scripts/implantar.sh',
  'rtk head -20 scripts/restaurar.sh',
  'rtk grep -n "reverter" scripts/implantar.sh',
  'rtk rg "sudo scripts/implantar.sh" scripts',
  'echo "bash scripts/implantar.sh"',
  'ssh maruko cat /opt/phati/bin/implantar.sh',
  'ssh maruko docker ps',
  'rtk git status',
  // leitura com script citado, e os caminhos que não citam script
  'rtk read scripts/implantar.sh',
  'sed -n 1,5p scripts/implantar.sh',
  'rtk sed -n 1,5p scripts/implantar.sh',
  'git log -p -- scripts/implantar.sh',
  'git diff --cached -- scripts/trocar-banco.sh',
  'shellcheck scripts/implantar.sh && echo ok',
  'echo "scripts/implantar.sh"',
  "echo 'bash scripts/implantar.sh'",
  'cat scripts/implantar.sh; make build',
  'gh workflow run implantar --ref main -f sha=abc',
  'gh workflow run implantar --ref main -f sha=<SHA>',
  // fluxo de git e de PR que só cita o nome do script como caminho ou como texto de mensagem
  'git add scripts/implantar.sh',
  'git commit -m "fix: implantar.sh não executa nada"',
  'git commit -F - <<\'FIM\'\nfix: corpo cita scripts/implantar.sh\nFIM',
  'git push -u origin fix/spec-009-fechamento',
  'git status',
  'git restore scripts/implantar.sh',
  'git checkout -- scripts/implantar.sh',
  'git checkout origin/dev -- scripts/implantar.sh',
  'gh pr create --title "fix: implantar.sh" --body "corpo cita scripts/implantar.sh"',
  'gh pr edit 12 --body-file /tmp/corpo.md',
  'gh pr view 12',
  'gh pr checks 12',
  // verbo que não é leitura: só o texto de --body/--title tira o nome do script do caminho de execução
  'gh pr comment 12 --body "corpo cita scripts/implantar.sh"',
  'gh issue create --title "x" --body "scripts/implantar.sh"',
  // aspas e escape: `;`, `|`, `&&` dentro de aspas ou escapados são texto do argumento, não corte
  'rtk rg -c "if false|elif false" scripts/implantar.sh',
  'rtk rg -n "a;b" scripts/implantar.sh',
  "grep -E 'x||y&&z' scripts/restaurar.sh",
  'rtk bash -n scripts/implantar.sh; echo "bash -n rc=$?"; rtk rg -c "if false|elif false" scripts/implantar.sh',
  'rtk rg a\\; scripts/implantar.sh',
];

for (const comando of LIBERADOS) {
  test(`libera sem execução: ${comando}`, () => {
    assert.equal(rodar(comando), null, comando);
  });
}

// --- CAMINHO INFELIZ: payload ruim não bloqueia trabalho ---

test('payload que não é JSON passa sem saída', () => {
  assert.equal(rodar(null, 'não é json'), null);
});

test('comando vazio passa sem saída', () => {
  assert.equal(rodar(''), null);
});

test('payload sem tool_input passa sem saída', () => {
  assert.equal(rodar(null, JSON.stringify({ tool_name: 'Bash' })), null);
});

test('comando que não é texto passa sem saída', () => {
  assert.equal(rodar(null, JSON.stringify({ tool_input: { command: 5 } })), null);
});

// --- decidir() direto: corpo de heredoc, pipe e git grep -O (sem executar comando real) ---

const { decidir } = require(HOOK);

// O corpo de heredoc executa quando quem o recebe é shell, source, eval, xargs ou ssh (ou comando desconhecido).
const HEREDOC_QUE_EXECUTA = [
  "bash <<'EOF'\nscripts/implantar.sh x\nEOF",
  'bash <<EOF\nscripts/implantar.sh x\nEOF',
  "ssh maruko <<'EOF'\nscripts/implantar.sh x\nEOF",
  "cat <<EOF | bash\nscripts/implantar.sh x\nEOF",
  "cat <<EOF |& bash\nscripts/implantar.sh x\nEOF",
  "(cat <<EOF | bash)\nscripts/implantar.sh x\nEOF",
  "sudo bash <<EOF\nscripts/implantar.sh x\nEOF",
  "xargs bash <<EOF\nscripts/implantar.sh x\nEOF",
  "eval \"$(cat)\" <<EOF\nscripts/implantar.sh x\nEOF",
  "python3 <<EOF\nscripts/implantar.sh x\nEOF",
];

for (const comando of HEREDOC_QUE_EXECUTA) {
  test(`heredoc que executa o corpo nega o script citado no corpo: ${JSON.stringify(comando)}`, () => {
    const r = decidir(comando);
    assert.ok(r, `esperava nega para: ${comando}`);
    assert.equal(r.regra.nome, 'implantar-direto', comando);
    assert.equal(r.alvo, 'implantar.sh', comando);
  });
}

// Corpo de heredoc que só grava, repassa ou envia texto: o script citado é dado, não executa.
const HEREDOC_QUE_E_DADO = [
  "git commit -F - <<'FIM'\nfix: corpo cita scripts/implantar.sh\nFIM",
  "cat <<EOF > notas.md\nscripts/implantar.sh\nEOF",
  "cat <<'EOF' | tee notas.md\nscripts/implantar.sh\nEOF",
  "gh pr edit 12 --body-file - <<'FIM'\nvê scripts/implantar.sh\nFIM",
];

for (const comando of HEREDOC_QUE_E_DADO) {
  test(`heredoc de consumidor de texto não nega pelo corpo: ${JSON.stringify(comando)}`, () => {
    assert.equal(decidir(comando), null, comando);
  });
}

// git grep -O / --open-files-in-pager roda um programa sobre os arquivos: não conta como leitura.
const GIT_GREP_COM_PAGER = [
  'git grep -O less scripts/implantar.sh',
  'git grep -Oless scripts/implantar.sh',
  'git grep --open-files-in-pager=sh scripts/implantar.sh',
  'git grep --open-files-in-pager scripts/implantar.sh',
];

for (const comando of GIT_GREP_COM_PAGER) {
  test(`git grep com pager nega o script citado: ${comando}`, () => {
    const r = decidir(comando);
    assert.ok(r, `esperava nega para: ${comando}`);
    assert.equal(r.regra.nome, 'implantar-direto', comando);
  });
}

test('git grep sem pager segue leitura e não nega', () => {
  assert.equal(decidir('git grep -n implantar scripts/implantar.sh'), null);
});

// --- instalação de script protegido em /opt/phati/bin: PERGUNTA na forma exata; resto segue negando ---

const INSTALACAO_QUE_PERGUNTA = [
  'install -o root -g root -m 755 scripts/implantar.sh /opt/phati/bin/',
  'install -o root -g root -m 755 scripts/implantar.sh scripts/restaurar.sh /opt/phati/bin',
  'rtk install -o root -g root -m 755 scripts/backup.sh /opt/phati/bin/',
  'sudo -n install -o root -g root -m 755 scripts/trocar-banco.sh /opt/phati/bin/',
  'rtk sudo -n install -o root -g root -m 755 scripts/implantar.sh /opt/phati/bin/',
  'install -o root -g root -m 755 scripts/implantar.sh /opt/phati/bin/ && echo ok',
];

for (const comando of INSTALACAO_QUE_PERGUNTA) {
  test(`pergunta a instalação na forma exata: ${comando}`, () => {
    const r = decidir(comando);
    assert.ok(r, `esperava ask para: ${comando}, hook passou`);
    assert.equal(r.regra.decisao, 'ask', comando);
    assert.equal(r.regra.nome, 'instalar-script', comando);
  });
}

test('pergunta de instalação diz o que será instalado e onde', () => {
  const r = decidir('install -o root -g root -m 755 scripts/implantar.sh scripts/restaurar.sh /opt/phati/bin/');
  assert.equal(r.alvo, 'instalar scripts/implantar.sh, scripts/restaurar.sh em /opt/phati/bin/');
});

const INSTALACAO_QUE_NEGA = [
  // destino, modo, dono, grupo e opção extra diferentes da forma exata
  'install -o root -g root -m 755 scripts/implantar.sh /opt/phati/bin2/',
  'install -o root -g root -m 755 scripts/implantar.sh /tmp/',
  'install -o root -g root -m 777 scripts/implantar.sh /opt/phati/bin/',
  'install -o root -g root -m 0755 scripts/implantar.sh /opt/phati/bin/',
  'install -o nobody -g root -m 755 scripts/implantar.sh /opt/phati/bin/',
  'install -o root -g wheel -m 755 scripts/implantar.sh /opt/phati/bin/',
  'install -o root -g root -m 755 -t /opt/phati/bin scripts/implantar.sh',
  'install -o root -g root -m 755 -D scripts/implantar.sh /opt/phati/bin/x',
  'install -o root -g root -m 755 --strip-program=/bin/sh scripts/implantar.sh /opt/phati/bin/',
  // glob, substituição, redireção e aspas tiram o comando da forma exata
  'install -o root -g root -m 755 scripts/*.sh scripts/implantar.sh /opt/phati/bin/',
  'install -o root -g root -m 755 scripts/implantar.sh /opt/phati/bin/ > /tmp/x',
  'install -o root -g root -m 755 "scripts/implantar.sh" /opt/phati/bin/',
  // a forma exata seguida de execução do script, ou de cópia com cp, nega
  'install -o root -g root -m 755 scripts/implantar.sh /opt/phati/bin/ && /opt/phati/bin/implantar.sh x',
  'cp scripts/implantar.sh /opt/phati/bin/',
  'bash -c "install -o root -g root -m 755 scripts/implantar.sh /opt/phati/bin/"',
  // com heredoc no comando, a análise de instalação não roda: segue como hoje (nega)
  'install -o root -g root -m 755 scripts/implantar.sh /opt/phati/bin/\nbash <<EOF\nx\nEOF',
  '/opt/phati/bin/implantar.sh x',
];

for (const comando of INSTALACAO_QUE_NEGA) {
  test(`nega a instalação fora da forma exata: ${JSON.stringify(comando)}`, () => {
    const r = decidir(comando);
    assert.ok(r, `esperava deny para: ${comando}, hook passou`);
    assert.equal(r.regra.decisao, 'deny', comando);
    assert.equal(r.regra.nome, 'implantar-direto', comando);
  });
}

// --- substituição `$(...)` ou crase que cita script protegido: quem a consome decide. Consumidor de leitura
// passa. Consumidor que não é de leitura, ou substituição na posição de comando, executa o resultado: nega ---

const SUBSTITUICAO_QUE_EXECUTA = [
  'install -o root -g root -m 755 $(echo scripts/implantar.sh) /opt/phati/bin/',
  'install -o root -g root -m 755 `echo scripts/implantar.sh` /opt/phati/bin/',
  'install -o root -g root -m "$(echo scripts/implantar.sh)" /opt/phati/bin/',
  'rtk install -o root -g root -m 755 $(echo scripts/implantar.sh) /opt/phati/bin/',
  'install -o root -g root -m 755 $(echo scripts/implantar.sh) /opt/phati/bin/ && echo ok',
  'bash -c "install -o root -g root -m 755 $(echo scripts/implantar.sh) /opt/phati/bin/"',
  '$(echo scripts/implantar.sh) x',
  '"$(echo scripts/implantar.sh)" x',
  '`echo scripts/implantar.sh` x',
  'sudo $(echo scripts/implantar.sh) x',
  'bash $(echo scripts/implantar.sh)',
  'rtk rg x "$(echo scripts/implantar.sh)" | bash',
  // aspa aberta depois da substituição: falha fechada
  'install -o root -g root -m 755 "$(echo scripts/implantar.sh) /opt/phati/bin/',
];

for (const comando of SUBSTITUICAO_QUE_EXECUTA) {
  test(`nega o resultado de substituição que executa: ${JSON.stringify(comando)}`, () => {
    const r = decidir(comando);
    assert.ok(r, `esperava deny para: ${comando}, hook passou`);
    assert.equal(r.regra.decisao, 'deny', comando);
    assert.equal(r.regra.nome, 'implantar-direto', comando);
    assert.equal(r.alvo, 'implantar.sh', comando);
  });
}

const SUBSTITUICAO_QUE_LE_OU_E_MENSAGEM = [
  'echo "$(cat scripts/implantar.sh)"',
  'rtk rg -c "$(echo scripts/implantar.sh)" scripts',
  'git add $(echo scripts/implantar.sh)',
  'git commit -m "$(echo scripts/implantar.sh)"',
  'gh pr create --body "$(cat scripts/implantar.sh)"',
  'bash -n $(echo scripts/implantar.sh)',
  "git commit -m \"$(cat <<'FIM'\nfix: implantar.sh\nFIM\n)\"",
];

for (const comando of SUBSTITUICAO_QUE_LE_OU_E_MENSAGEM) {
  test(`substituição que só lê ou vira mensagem não nega: ${JSON.stringify(comando)}`, () => {
    assert.equal(decidir(comando), null, comando);
  });
}
