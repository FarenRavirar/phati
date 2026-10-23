'use strict';
// Suíte do verificar-vazamento. Roda com: node --test .githooks/
// Valores sensíveis são MONTADOS por concatenação: o literal inteiro no arquivo
// faria o próprio hook bloquear o commit desta suíte.

const test = require('node:test');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { verificar, verificarCaminho, ipv4Publico } = require('./verificar-vazamento.js');

const juntar = (...partes) => partes.join('');
const CHAVE_PRIVADA = juntar('-----BEGIN ', 'RSA PRIVATE KEY-----');
const TOKEN_GITHUB = juntar('gh', 'p_', 'a'.repeat(36));
const CHAVE_AWS = juntar('AKIA', 'ABCDEFGHIJKLMNOP');
const IP_PUBLICO = [8, 8, 8, 8].join('.');
const SENHA_ATRIBUIDA = juntar('senha', ' = "', 'abcd1234efgh', '"');
const CONEXAO = juntar('postgres', '://', 'usuario', ':', 'segredo123', '@', 'host.exemplo', '/banco');

const regrasDe = (achados) => achados.map((a) => a.regra);
const sobre = (conteudo, caminho = 'src/exemplo.js', termos = []) =>
  verificar({ caminhos: [caminho], lerConteudo: () => Buffer.from(conteudo, 'utf8'), termos });

test('caminhos proibidos são bloqueados', () => {
  const proibidos = [
    '.env',
    'api/.env.producao',
    'certificados/servidor.pem',
    'chaves/app.key',
    '.ssh/id_rsa',
    'mapas/ortofoto.tif',
    'mapas/limite.shp',
    'dados/fazenda.gpkg',
    'banco/copia.dump',
    'banco/local.sqlite',
    'relatorio.pdf',
    'planilha.xlsx',
    'DEFINIÇÃO FUNCIONAL.md',
    'DEFINICAO.md', // regressão: o arquivo foi renomeado e escapou do padrão antigo
    'definicao-v2.md',
    'docs/DEFINIÇÃO.md',
    'docs/definicao-funcional-v2.md'.replace('definicao-funcional-v2', 'DEFINICAO FUNCIONAL'),
    '.claude/settings.local.json',
    'dados/qualquer.txt',
    'segredos/token.txt',
  ];
  for (const caminho of proibidos) {
    assert.ok(verificarCaminho(caminho).length > 0, `deveria bloquear: ${caminho}`);
  }
});

test('caminhos legítimos passam', () => {
  const permitidos = [
    'AGENTS.md',
    'src/camadas/revisao.js',
    '.env.example',
    '.env.exemplo',
    'specs/001-arquitetura/spec.md',
    'migracoes/001_criar_fazenda.sql',
    'docs/pesquisa/00-arquitetura-base.md',
    '.githooks/verificar-vazamento.js',
  ];
  for (const caminho of permitidos) {
    assert.deepEqual(verificarCaminho(caminho), [], `deveria passar: ${caminho}`);
  }
});

test('conteúdo com segredo é bloqueado, regra por regra', () => {
  assert.ok(regrasDe(sobre(CHAVE_PRIVADA)).includes('chave privada'));
  assert.ok(regrasDe(sobre(`token: ${TOKEN_GITHUB}`)).includes('token do GitHub'));
  assert.ok(regrasDe(sobre(`aws ${CHAVE_AWS}`)).includes('chave AWS'));
  assert.ok(regrasDe(sobre(SENHA_ATRIBUIDA)).includes('senha ou segredo atribuído'));
  assert.ok(regrasDe(sobre(CONEXAO)).includes('string de conexão com senha'));
  assert.ok(regrasDe(sobre(`servidor ${IP_PUBLICO}`)).includes('endereço IP público'));
});

test('a mensagem aponta arquivo e linha e nunca repete o valor', () => {
  const achados = sobre(`linha limpa\n${SENHA_ATRIBUIDA}`, 'config/app.js');
  assert.equal(achados.length, 1);
  assert.equal(achados[0].arquivo, 'config/app.js');
  assert.equal(achados[0].linha, 2);
  assert.ok(!JSON.stringify(achados).includes('abcd1234efgh'));
});

test('texto limpo passa', () => {
  assert.deepEqual(sobre('const total = somarAreas(camadas);\n// comentário normal'), []);
  assert.deepEqual(sobre('Versão 3.6.0 do PostGIS e 22.04.5 do Ubuntu.'), []);
  assert.deepEqual(sobre('Veja https://github.com/FarenRavirar/phati.git'), []);
  assert.deepEqual(sobre('const senha = lerDoAmbiente("SENHA_BANCO");'), []);
});

test('IPs privados, de teste e de loopback passam; públicos não', () => {
  for (const ip of ['127.0.0.1', '10.0.0.5', '192.168.1.10', '172.16.0.1', '172.31.255.1', '169.254.1.1', '203.0.113.7', '198.51.100.9', '192.0.2.3', '0.0.0.0']) {
    assert.deepEqual(sobre(`host ${ip}`), [], `deveria passar: ${ip}`);
  }
  for (const ip of [juntar('8.8.', '8.8'), juntar('172.32.', '0.1'), juntar('1.1.', '1.1')]) {
    assert.ok(regrasDe(sobre(`host ${ip}`)).includes('endereço IP público'), `deveria bloquear: ${ip}`);
  }
  assert.equal(ipv4Publico([999, 1, 1, 1]), false);
});

test('termos sensíveis locais: sem acento, sem diferença de caixa, no texto e no nome', () => {
  const termos = ['Fazenda Modelo', '# comentário ignorado pelo leitor'.slice(0, 0)];
  assert.ok(regrasDe(sobre('visita à FAZENDA modelo ontem', 'notas.md', termos)).includes('termo da lista sensível local'));
  assert.ok(regrasDe(sobre('fazenda módelo', 'notas.md', ['fazenda modelo'])).includes('termo da lista sensível local'));
  assert.ok(regrasDe(sobre('texto neutro', 'relatorio-fazenda-modelo.md', ['fazenda modelo'])).includes('termo da lista sensível local no nome'));
  assert.deepEqual(sobre('texto neutro', 'notas.md', ['fazenda modelo']), []);
  assert.deepEqual(sobre('qualquer coisa', 'notas.md', ['']), []);
});

test('arquivo binário não tem o conteúdo varrido', () => {
  const binario = Buffer.concat([Buffer.from([0, 1, 2, 3]), Buffer.from(CHAVE_PRIVADA)]);
  const achados = verificar({ caminhos: ['imagem.png'], lerConteudo: () => binario });
  assert.deepEqual(achados, []);
});

test('integração: commit com segredo falha, commit limpo passa, nada vaza na saída', () => {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), 'phati-vazamento-'));
  const git = (...args) => execFileSync('git', args, { cwd: raiz, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  const hook = path.join(__dirname, 'verificar-vazamento.js');
  const rodar = () => {
    try {
      execFileSync(process.execPath, [hook], { cwd: raiz, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
      return { codigo: 0, erro: '' };
    } catch (e) {
      return { codigo: e.status, erro: String(e.stderr) };
    }
  };
  try {
    git('init', '-q');
    fs.writeFileSync(path.join(raiz, 'limpo.txt'), 'nada sensível aqui\n');
    git('add', 'limpo.txt');
    assert.equal(rodar().codigo, 0);

    fs.writeFileSync(path.join(raiz, 'segredo.txt'), `${SENHA_ATRIBUIDA}\n`);
    git('add', 'segredo.txt');
    const resultado = rodar();
    assert.equal(resultado.codigo, 1);
    assert.ok(resultado.erro.includes('COMMIT BLOQUEADO'));
    assert.ok(resultado.erro.includes('segredo.txt:1'));
    assert.ok(!resultado.erro.includes('abcd1234efgh'));

    git('rm', '-q', '--cached', 'segredo.txt');
    fs.mkdirSync(path.join(raiz, '.githooks'));
    fs.writeFileSync(path.join(raiz, '.githooks', 'termos-sensiveis.local'), '# lista\nCliente Ficticio\n');
    fs.writeFileSync(path.join(raiz, 'nota.txt'), 'reunião com o cliente ficticio\n');
    git('add', 'nota.txt');
    const comTermo = rodar();
    assert.equal(comTermo.codigo, 1);
    assert.ok(comTermo.erro.includes('termo da lista sensível local'));
    assert.ok(!comTermo.erro.toLowerCase().includes('ficticio'));
  } finally {
    fs.rmSync(raiz, { recursive: true, force: true });
  }
});
