const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const { executarServidor } = require('./servidor-mcp.js');

const juntar = (...partes) => partes.join('');
const CHAVE_SINTETICA = juntar('chave', '-sintetica');

test('Linux executa Context7 por npx sem shell', () => {
  let chamada;
  const resultado = executarServidor('context7', {
    plataforma: 'linux',
    ambiente: {},
    executar: (comando, argumentos, opcoes) => {
      chamada = { comando, argumentos, opcoes };
      return { status: 0 };
    },
  });

  assert.deepEqual(resultado, { codigo: 0, erro: null });
  assert.equal(chamada.comando, 'npx');
  assert.deepEqual(chamada.argumentos, ['-y', '@upstash/context7-mcp@4.4.4']);
  assert.equal(chamada.opcoes.shell, false);
});

test('Windows executa Context7 pelo ComSpec com comando fixo', () => {
  let chamada;
  const resultado = executarServidor('context7', {
    plataforma: 'win32',
    ambiente: { ComSpec: 'C:\\Windows\\System32\\cmd.exe' },
    executar: (comando, argumentos, opcoes) => {
      chamada = { comando, argumentos, opcoes };
      return { status: 0 };
    },
  });

  assert.deepEqual(resultado, { codigo: 0, erro: null });
  assert.equal(chamada.comando, 'C:\\Windows\\System32\\cmd.exe');
  assert.deepEqual(chamada.argumentos, ['/d', '/s', '/c', 'npx -y @upstash/context7-mcp@4.4.4']);
  assert.equal(chamada.opcoes.shell, false);
});

test('ID fora da allowlist falha sem executar processo', () => {
  let executou = false;
  const resultado = executarServidor('outro; comando', {
    executar: () => {
      executou = true;
      return { status: 0 };
    },
  });

  assert.deepEqual(resultado, { codigo: 64, erro: 'servidor MCP desconhecido.' });
  assert.equal(executou, false);
});

test('Magic sem chave falha fechado no Linux', () => {
  let executou = false;
  const resultado = executarServidor('magic', {
    plataforma: 'linux',
    ambiente: {},
    executar: () => {
      executou = true;
      return { status: 0 };
    },
  });

  assert.deepEqual(resultado, { codigo: 1, erro: 'API_KEY_21ST ausente.' });
  assert.equal(executou, false);
});

test('Magic usa fallback do ambiente de usuário no Windows sem imprimir a chave', () => {
  const chamadas = [];
  const resultado = executarServidor('magic', {
    plataforma: 'win32',
    ambiente: { ComSpec: 'cmd.exe' },
    executar: (comando, argumentos, opcoes) => {
      chamadas.push({ comando, argumentos, opcoes });
      if (comando === 'powershell.exe') return { status: 0, stdout: 'chave-sintetica\r\n' };
      return { status: 0 };
    },
  });

  assert.deepEqual(resultado, { codigo: 0, erro: null });
  assert.equal(chamadas.length, 2);
  assert.equal(chamadas[0].opcoes.stdio[1], 'pipe');
  assert.equal(chamadas[1].opcoes.env.API_KEY_21ST, CHAVE_SINTETICA);
  assert.deepEqual(chamadas[1].argumentos, ['/d', '/s', '/c', 'npx -y @21st-dev/magic@0.2.3']);
});

test('Magic usa chave do processo sem consultar PowerShell', () => {
  const comandos = [];
  const resultado = executarServidor('magic', {
    plataforma: 'win32',
    ambiente: { ComSpec: 'cmd.exe', API_KEY_21ST: CHAVE_SINTETICA },
    executar: (comando) => {
      comandos.push(comando);
      return { status: 0 };
    },
  });

  assert.deepEqual(resultado, { codigo: 0, erro: null });
  assert.deepEqual(comandos, ['cmd.exe']);
});

test('falha de spawn é fechada e não expõe detalhe', () => {
  const resultado = executarServidor('context7', {
    plataforma: 'linux',
    ambiente: {},
    executar: () => ({ error: new Error('detalhe interno'), status: null }),
  });

  assert.deepEqual(resultado, { codigo: 1, erro: 'falha ao iniciar o servidor MCP.' });
  assert.doesNotMatch(resultado.erro, /detalhe interno/);
});

test('código de saída do servidor é propagado', () => {
  assert.deepEqual(
    executarServidor('context7', {
      plataforma: 'linux',
      ambiente: {},
      executar: () => ({ status: 7 }),
    }),
    { codigo: 7, erro: 'servidor MCP terminou com falha.' },
  );
});

test('.mcp.json usa o mesmo wrapper com IDs fixos', () => {
  const config = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', '.mcp.json'), 'utf8'));
  const caminho = '.claude/mcp/servidor-mcp.js';

  assert.deepEqual(config.mcpServers.context7, {
    type: 'stdio',
    command: 'node',
    args: [caminho, 'context7'],
    env: {},
  });
  assert.deepEqual(config.mcpServers.magic, {
    type: 'stdio',
    command: 'node',
    args: [caminho, 'magic'],
  });
});
