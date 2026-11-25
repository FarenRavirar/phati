'use strict';
// Suíte do `estado-implantacao.sh` (spec 009, R16): mostra ativa, candidata, SHAs, último registro e destino do nginx.
// Roda com: node --test scripts/estado-implantacao.test.js
// Só leitura: cada teste monta uma pasta de mentira em tmp, roda o script e confere a saída e a árvore antes/depois.
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const SCRIPT = path.join(__dirname, 'estado-implantacao.sh');
const unix = (caminho) => caminho.replace(/\\/g, '/');
const SHA_A = '0123456789abcdef0123456789abcdef01234567';
const SHA_B = 'fedcba9876543210fedcba9876543210fedcba98';
const ALVO_AZUL = 'set $alvo app_azul;\nset $pilha azul;';
const ALVO_VERDE = 'set $alvo app_verde;\nset $pilha verde;';

const raizes = [];
after(() => {
  for (const raiz of raizes) fs.rmSync(raiz, { recursive: true, force: true });
});

// Monta uma pasta de implantação de mentira: `arquivos` mapeia caminho relativo → conteúdo.
function criarDir(arquivos = {}) {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), 'estado-implantacao-'));
  raizes.push(raiz);
  const dir = path.join(raiz, 'phati');
  fs.mkdirSync(dir);
  for (const [relativo, conteudo] of Object.entries(arquivos)) {
    const alvo = path.join(dir, relativo);
    fs.mkdirSync(path.dirname(alvo), { recursive: true });
    fs.writeFileSync(alvo, conteudo);
  }
  return dir;
}

function rodar(dir, extra = {}) {
  return spawnSync('bash', [unix(SCRIPT)], {
    env: { ...process.env, PHATI_DIR: unix(dir), PHATI_ALVO_DIR: '', ...extra },
    encoding: 'utf8',
  });
}

const linhas = (resultado) => resultado.stdout.split('\n').filter(Boolean);
const valor = (resultado, chave) => {
  const achada = linhas(resultado).find((linha) => linha.startsWith(`${chave}=`));
  return achada === undefined ? undefined : achada.slice(chave.length + 1);
};

// Foto da árvore (caminho, tamanho, mtime e conteúdo): prova que o script não escreve nada.
function fotografar(dir) {
  const saida = [];
  const andar = (pasta) => {
    for (const nome of fs.readdirSync(pasta).sort()) {
      const caminho = path.join(pasta, nome);
      const info = fs.statSync(caminho);
      if (info.isDirectory()) {
        saida.push(`${caminho}/`);
        andar(caminho);
      } else {
        saida.push(`${caminho}|${info.size}|${info.mtimeMs}|${fs.readFileSync(caminho, 'base64')}`);
      }
    }
  };
  andar(dir);
  return saida.join('\n');
}

const implantacaoFeliz = () =>
  criarDir({
    ativa: 'azul\n',
    'pilha-azul.sha': `${SHA_A}\n`,
    'pilha-verde.sha': `${SHA_B}\n`,
    'implantacoes.log': '2026-11-19T10:00:00Z 1111 inicio\n2026-11-20T11:00:00Z 2222 OK ativa=azul\n',
    'alvo/alvo.conf': ALVO_AZUL,
  });

test('feliz: azul ativa, dois SHAs, último registro e destino do nginx', () => {
  const r = rodar(implantacaoFeliz());
  assert.equal(r.status, 0, r.stderr);
  assert.equal(valor(r, 'ativa'), 'azul');
  assert.equal(valor(r, 'candidata'), 'verde');
  assert.equal(valor(r, 'sha-azul'), SHA_A.slice(0, 12));
  assert.equal(valor(r, 'sha-verde'), SHA_B.slice(0, 12));
  assert.equal(valor(r, 'ultimo'), '2026-11-20T11:00:00Z 2222 OK ativa=azul');
  assert.equal(valor(r, 'destino-nginx'), 'app_azul');
  assert.equal(linhas(r).some((linha) => linha.startsWith('AVISO')), false);
});

test('feliz: verde ativa vira candidata azul e alvo verde', () => {
  const dir = criarDir({ ativa: 'verde', 'alvo/alvo.conf': ALVO_VERDE });
  const r = rodar(dir);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(valor(r, 'ativa'), 'verde');
  assert.equal(valor(r, 'candidata'), 'azul');
  assert.equal(valor(r, 'destino-nginx'), 'app_verde');
});

test('primeira implantação: sem arquivos vira nenhuma/nenhum, não erro', () => {
  const r = rodar(criarDir());
  assert.equal(r.status, 0, r.stderr);
  assert.equal(valor(r, 'ativa'), 'nenhuma');
  assert.equal(valor(r, 'candidata'), 'azul');
  assert.equal(valor(r, 'sha-azul'), 'nenhum');
  assert.equal(valor(r, 'sha-verde'), 'nenhum');
  assert.equal(valor(r, 'ultimo'), 'nenhum');
  assert.equal(valor(r, 'destino-nginx'), 'nenhum');
  assert.equal(r.stderr, '');
});

test('valor hostil em ativa: não é ecoado cru, vira invalida', () => {
  for (const hostil of ['azul; rm -rf /', 'azul\nrm -rf /', 'x\ny', '']) {
    const r = rodar(criarDir({ ativa: hostil }));
    assert.equal(r.status, 0, r.stderr);
    assert.equal(valor(r, 'ativa'), 'invalida', `valor ${JSON.stringify(hostil)}`);
    assert.equal(valor(r, 'candidata'), 'invalida');
    assert.equal(r.stdout.includes('rm -rf'), false);
    assert.equal(r.stdout.includes(';'), false);
  }
});

test('SHA inválido vira nenhum; SHA de 40 hex vira 12 caracteres', () => {
  const dir = criarDir({
    'pilha-azul.sha': 'nao-e-sha-zzz\n',
    'pilha-verde.sha': `${SHA_B.slice(0, 39)}\n`,
  });
  const r = rodar(dir);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(valor(r, 'sha-azul'), 'nenhum');
  assert.equal(valor(r, 'sha-verde'), 'nenhum');
  const maiusculo = rodar(criarDir({ 'pilha-azul.sha': SHA_A.toUpperCase() }));
  assert.equal(valor(maiusculo, 'sha-azul'), 'nenhum');
});

test('log com controle e linha enorme: sem controle e truncado em 300', () => {
  const ultima = `ok\x1b[31mvermelho\x07\rcortado${'b'.repeat(1000)}`;
  const dir = criarDir({ 'implantacoes.log': `linha antiga\n${ultima}\n` });
  const r = rodar(dir);
  assert.equal(r.status, 0, r.stderr);
  const ultimo = valor(r, 'ultimo');
  assert.ok(ultimo.length <= 300, `tamanho ${ultimo.length}`);
  assert.ok(ultimo.startsWith('ok[31mvermelhocortado'));
  assert.equal(/[\x00-\x08\x0b-\x1f\x7f]/.test(r.stdout), false);
});

test('discordância: ativa azul e alvo verde gera AVISO', () => {
  const dir = criarDir({ ativa: 'azul', 'alvo/alvo.conf': ALVO_VERDE });
  const r = rodar(dir);
  assert.equal(r.status, 0, r.stderr);
  assert.ok(
    linhas(r).includes('AVISO: ativa=azul mas o alvo.conf configura verde (configuração lida do arquivo, não o roteamento efetivo do nginx)'),
    r.stdout,
  );
});

test('diretiva comentada não conta: a efetiva, depois dela, é o destino', () => {
  const r = rodar(criarDir({ 'alvo/alvo.conf': '# set $alvo app_verde;\nset $alvo app_azul;\n' }));
  assert.equal(r.status, 0, r.stderr);
  assert.equal(valor(r, 'destino-nginx'), 'app_azul');
});

test('só diretiva comentada: destino é nenhum', () => {
  const r = rodar(criarDir({ 'alvo/alvo.conf': '  # set $alvo app_verde;\n' }));
  assert.equal(valor(r, 'destino-nginx'), 'nenhum');
});

test('set repetido no alvo.conf: vence o último, como no nginx', () => {
  const r = rodar(criarDir({ 'alvo/alvo.conf': 'set $alvo app_azul;\nset $alvo app_verde;\n' }));
  assert.equal(valor(r, 'destino-nginx'), 'app_verde');
});

test('ativa com 64 bytes (quebras finais) é lida; com 65 é invalida', () => {
  const no_limite = rodar(criarDir({ ativa: `azul${'\n'.repeat(60)}` }));
  assert.equal(valor(no_limite, 'ativa'), 'azul');
  const acima = rodar(criarDir({ ativa: `azul${'\n'.repeat(61)}` }));
  assert.equal(valor(acima, 'ativa'), 'invalida');
  assert.equal(valor(acima, 'candidata'), 'invalida');
});

test('sem discordância: ativa e alvo batem, sem AVISO', () => {
  const r = rodar(criarDir({ ativa: 'verde', 'alvo/alvo.conf': ALVO_VERDE }));
  assert.equal(linhas(r).some((linha) => linha.startsWith('AVISO')), false);
});

test('alvo.conf com destino fora da lista vira nenhum', () => {
  const r = rodar(criarDir({ 'alvo/alvo.conf': 'set $alvo app_outro; rm -rf /;' }));
  assert.equal(r.status, 0, r.stderr);
  assert.equal(valor(r, 'destino-nginx'), 'nenhum');
});

test('PHATI_DIR inexistente sai com 2 e não imprime estado', () => {
  const r = rodar(path.join(os.tmpdir(), 'nao-existe-estado-implantacao-9f3a'));
  assert.equal(r.status, 2);
  assert.equal(r.stdout, '');
  assert.match(r.stderr, /ERRO: PHATI_DIR inexistente/);
});

test('não escreve nada: a árvore fica igual nos casos feliz e hostil', () => {
  for (const montar of [implantacaoFeliz, () => criarDir({ ativa: 'azul; rm -rf /' })]) {
    const dir = montar();
    const antes = fotografar(dir);
    const r = rodar(dir);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(fotografar(dir), antes);
  }
});
