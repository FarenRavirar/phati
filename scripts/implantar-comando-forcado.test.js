'use strict';
// Comando forçado da chave SSH da VM (spec 009, R14; spec 006 R6): o `implantar.sh` recebe o pedido em SSH_ORIGINAL_COMMAND
// e só aceita "<sha>" ou "<sha> --sem-migracao". Aqui o pedido chega como texto: nada pode virar shell nem disparar o docker.
// Roda com: node --test scripts/ (o CI roda scripts/*.test.js). O docker é um dublê que grava o sentinela, e o pedido
// hostil também grava o mesmo sentinela se o shell o executar: sentinela ausente = nada executou.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { unix } = require('./ajuda-teste');

const IMPLANTAR = path.join(__dirname, 'implantar.sh');
const SHA = '0123456789abcdef0123456789abcdef01234567';

// Diretório de trabalho sem `.env`: um SHA aceito para no `.env ausente`, antes de qualquer passo que toque a VM.
function ambiente() {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), 'comando-forcado-'));
  const sentinela = path.join(raiz, 'executou');
  const docker = path.join(raiz, 'docker');
  fs.writeFileSync(docker, `#!/usr/bin/env bash\ntouch "${unix(sentinela)}"\n`, { mode: 0o755 });
  return { raiz, sentinela, docker };
}

function rodar(amb, comando) {
  const r = spawnSync('bash', [unix(IMPLANTAR)], {
    env: { PATH: process.env.PATH, PHATI_DIR: unix(amb.raiz), DOCKER: unix(amb.docker), SSH_ORIGINAL_COMMAND: comando },
    encoding: 'utf8',
    timeout: 20000,
  });
  return { ...r, executou: fs.existsSync(amb.sentinela) };
}

// Pedido hostil: o sentinela só existe se o shell executar o trecho.
const injetar = (amb, pedido) => pedido.replace('SENTINELA', `touch "${unix(amb.sentinela)}"`);

test('comando forçado aceita SHA completo, com e sem --sem-migracao (passa o portão e para no .env)', () => {
  for (const pedido of [SHA, `${SHA} --sem-migracao`]) {
    const amb = ambiente();
    try {
      const r = rodar(amb, pedido);
      assert.equal(r.status, 1, r.stderr);
      assert.doesNotMatch(r.stderr, /SHA completo|opção desconhecida/);
      assert.match(r.stderr, /\.env ausente/);
      assert.equal(r.executou, false);
    } finally {
      fs.rmSync(amb.raiz, { recursive: true, force: true });
    }
  }
});

test('comando forçado recusa o que não é SHA completo, vazio ou com opção fora da lista (rc != 0, nada executa)', () => {
  const casos = [
    ['bash -c "id"', /SHA completo/],
    ['', /SHA completo/],
    ['   ', /SHA completo/],
    [SHA.slice(0, 7), /SHA completo/],
    [`${SHA}0`, /SHA completo/],
    [SHA.toUpperCase(), /SHA completo/],
    ['não-é-sha', /SHA completo/],
    ['rm -rf /', /SHA completo/],
    ['SENTINELA', /SHA completo/],
    [`${SHA}; SENTINELA`, /SHA completo/],
    [`$(SENTINELA)`, /SHA completo/],
    ['`SENTINELA`', /SHA completo/],
    [`${SHA} --sem-migracao; SENTINELA`, /opção desconhecida/],
    [`${SHA} --outra`, /opção desconhecida/],
    [`${SHA} --sem-migracao --sem-migracao`, /opção desconhecida/],
    [`${SHA} $(SENTINELA)`, /opção desconhecida/],
  ];
  for (const [modelo, esperado] of casos) {
    const amb = ambiente();
    try {
      const r = rodar(amb, injetar(amb, modelo));
      assert.notEqual(r.status, 0, `aceitou o pedido: ${modelo}`);
      assert.match(r.stderr, esperado, `pedido ${modelo}`);
      assert.equal(r.executou, false, `executou algo do pedido: ${modelo}`);
    } finally {
      fs.rmSync(amb.raiz, { recursive: true, force: true });
    }
  }
});

test('comando forçado com quebra de linha ou CR recusa o pedido inteiro (rc != 0, mensagem em português, nada executa)', () => {
  // Antes: o `read -r` parava na quebra de linha e o SHA passava o portão. Agora a recusa vem antes de qualquer leitura.
  const casos = [
    `${SHA}\nSENTINELA`,
    `\n${SHA}`,
    `${SHA}\r`,
    `${SHA}\r\nSENTINELA`,
    `${SHA} --sem-migracao\nSENTINELA`,
  ];
  for (const modelo of casos) {
    const amb = ambiente();
    try {
      const r = rodar(amb, injetar(amb, modelo));
      assert.notEqual(r.status, 0, `aceitou o pedido: ${JSON.stringify(modelo)}`);
      assert.match(r.stderr, /quebra de linha ou CR recusado: nada foi executado/, JSON.stringify(modelo));
      assert.doesNotMatch(r.stderr, /\.env ausente/, 'não pode chegar ao .env');
      assert.equal(r.executou, false, `executou algo do pedido: ${JSON.stringify(modelo)}`);
    } finally {
      fs.rmSync(amb.raiz, { recursive: true, force: true });
    }
  }
});
