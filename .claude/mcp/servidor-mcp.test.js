const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const { executarServidor } = require('./servidor-mcp.js');

const juntar = (...partes) => partes.join('');
const CHAVE_SINTETICA = juntar('chave', '-sintetica');
const VALOR_SINTETICO = juntar('sin', 'tetico');
const DIR_FALSO = '/fake/mcp';
const BIN_FALSO = '/fake/mcp/node_modules/pacote/dist/index.js';

// Padrão de teste: instalação presente, binário resolvido, sem disco real. Cada teste sobrescreve só o que mede.
const base = (extra) => ({
  plataforma: 'linux',
  ambiente: { PATH: '/usr/bin' },
  existe: () => true,
  resolverBin: () => BIN_FALSO,
  dir: DIR_FALSO,
  ...extra,
});

test('Linux executa o binário do Context7 com node, sem shell', () => {
  const chamadas = [];
  const resultado = executarServidor('context7', base({
    executar: (comando, argumentos, opcoes) => {
      chamadas.push({ comando, argumentos, opcoes });
      return { status: 0 };
    },
  }));

  assert.deepEqual(resultado, { codigo: 0, erro: null });
  assert.equal(chamadas.length, 1);
  assert.equal(chamadas[0].comando, process.execPath);
  assert.deepEqual(chamadas[0].argumentos, [BIN_FALSO]);
  assert.equal(chamadas[0].opcoes.shell, false);
});

test('resolve o bin do pacote certo para cada servidor', () => {
  const pedidos = [];
  executarServidor('magic', base({
    ambiente: { PATH: '/usr/bin', API_KEY_21ST: CHAVE_SINTETICA },
    resolverBin: (pacote) => {
      pedidos.push(pacote);
      return BIN_FALSO;
    },
    executar: () => ({ status: 0 }),
  }));

  assert.deepEqual(pedidos, ['@21st-dev/magic']);
});

test('instala quando node_modules falta: npm ci com --ignore-scripts e depois sobe o servidor', () => {
  const chamadas = [];
  const resultado = executarServidor('context7', base({
    existe: () => false,
    executar: (comando, argumentos, opcoes) => {
      chamadas.push({ comando, argumentos, opcoes });
      return { status: 0 };
    },
  }));

  assert.deepEqual(resultado, { codigo: 0, erro: null });
  assert.equal(chamadas.length, 2);
  assert.equal(chamadas[0].comando, 'npm');
  assert.deepEqual(chamadas[0].argumentos, ['ci', '--ignore-scripts', '--prefix', DIR_FALSO]);
  assert.equal(chamadas[0].opcoes.shell, false);
  assert.equal(chamadas[1].comando, process.execPath);
});

test('não reinstala quando node_modules já existe', () => {
  const chamadas = [];
  executarServidor('context7', base({
    existe: (caminho) => {
      assert.equal(caminho, path.join(DIR_FALSO, 'node_modules'));
      return true;
    },
    executar: (comando) => {
      chamadas.push(comando);
      return { status: 0 };
    },
  }));

  assert.deepEqual(chamadas, [process.execPath]);
});

test('npm ci com código de saída diferente de zero falha fechado e não sobe o servidor', () => {
  const chamadas = [];
  const resultado = executarServidor('context7', base({
    existe: () => false,
    executar: (comando) => {
      chamadas.push(comando);
      return { status: 1 };
    },
  }));

  assert.deepEqual(resultado, { codigo: 1, erro: 'falha ao instalar dependências do MCP.' });
  assert.deepEqual(chamadas, ['npm']);
});

test('npm ci que não inicia falha fechado sem vazar o detalhe', () => {
  const chamadas = [];
  const resultado = executarServidor('context7', base({
    existe: () => false,
    executar: (comando) => {
      chamadas.push(comando);
      return { error: new Error('detalhe interno'), status: null };
    },
  }));

  assert.deepEqual(resultado, { codigo: 1, erro: 'falha ao instalar dependências do MCP.' });
  assert.deepEqual(chamadas, ['npm']);
  assert.doesNotMatch(resultado.erro, /detalhe interno/);
});

test('npm ci recebe env mínimo sem a chave do Magic, e o servidor recebe só a chave dele', () => {
  const envs = [];
  executarServidor('magic', base({
    existe: () => false,
    ambiente: { PATH: '/usr/bin', HOME: '/home/teste', API_KEY_21ST: CHAVE_SINTETICA, TOKEN_GIT: VALOR_SINTETICO },
    executar: (_comando, _argumentos, opcoes) => {
      envs.push(opcoes.env);
      return { status: 0 };
    },
  }));

  assert.deepEqual(envs[0], { PATH: '/usr/bin', HOME: '/home/teste' });
  assert.deepEqual(envs[1], { PATH: '/usr/bin', HOME: '/home/teste', API_KEY_21ST: CHAVE_SINTETICA });
});

test('context7 recebe só a lista fixa de variáveis e nunca a chave do Magic', () => {
  let env;
  executarServidor('context7', base({
    ambiente: { PATH: '/usr/bin', HOME: '/home/teste', API_KEY_21ST: CHAVE_SINTETICA, TOKEN_GIT: VALOR_SINTETICO },
    executar: (_comando, _argumentos, opcoes) => {
      env = opcoes.env;
      return { status: 0 };
    },
  }));

  assert.deepEqual(env, { PATH: '/usr/bin', HOME: '/home/teste' });
});

test('Magic sem chave falha fechado antes de instalar nada', () => {
  let executou = false;
  const resultado = executarServidor('magic', base({
    existe: () => false,
    ambiente: {},
    executar: () => {
      executou = true;
      return { status: 0 };
    },
  }));

  assert.deepEqual(resultado, { codigo: 1, erro: 'API_KEY_21ST ausente.' });
  assert.equal(executou, false);
});

test('Magic usa fallback do ambiente de usuário no Windows sem imprimir a chave', () => {
  const chamadas = [];
  const resultado = executarServidor('magic', base({
    plataforma: 'win32',
    ambiente: { ComSpec: 'cmd.exe' },
    executar: (comando, argumentos, opcoes) => {
      chamadas.push({ comando, argumentos, opcoes });
      if (comando === 'powershell.exe') return { status: 0, stdout: 'chave-sintetica\r\n' };
      return { status: 0 };
    },
  }));

  assert.deepEqual(resultado, { codigo: 0, erro: null });
  assert.equal(chamadas.length, 2);
  assert.equal(chamadas[0].opcoes.stdio[1], 'pipe');
  assert.equal(chamadas[1].comando, process.execPath);
  assert.equal(chamadas[1].opcoes.env.API_KEY_21ST, CHAVE_SINTETICA);
});

test('Magic usa chave do processo sem consultar PowerShell', () => {
  const comandos = [];
  const resultado = executarServidor('magic', base({
    plataforma: 'win32',
    ambiente: { ComSpec: 'cmd.exe', API_KEY_21ST: CHAVE_SINTETICA },
    executar: (comando) => {
      comandos.push(comando);
      return { status: 0 };
    },
  }));

  assert.deepEqual(resultado, { codigo: 0, erro: null });
  assert.deepEqual(comandos, [process.execPath]);
});

test('Windows instala pelo ComSpec com comando fixo e sem shell', () => {
  const chamadas = [];
  executarServidor('context7', base({
    plataforma: 'win32',
    existe: () => false,
    ambiente: { ComSpec: 'C:\\Windows\\System32\\cmd.exe' },
    executar: (comando, argumentos, opcoes) => {
      chamadas.push({ comando, argumentos, opcoes });
      return { status: 0 };
    },
  }));

  assert.equal(chamadas[0].comando, 'C:\\Windows\\System32\\cmd.exe');
  assert.equal(chamadas[0].argumentos[0], '/d');
  assert.match(chamadas[0].argumentos[3], /^npm ci --ignore-scripts --prefix "\/fake\/mcp"$/);
  assert.equal(chamadas[0].opcoes.shell, false);
});

test('Windows sem ComSpec falha fechado na instalação sem executar processo', () => {
  let executou = false;
  const resultado = executarServidor('context7', base({
    plataforma: 'win32',
    existe: () => false,
    ambiente: {},
    executar: () => {
      executou = true;
      return { status: 0 };
    },
  }));

  assert.deepEqual(resultado, { codigo: 1, erro: 'ComSpec ausente.' });
  assert.equal(executou, false);
});

test('binário ausente ou sem bin legível falha fechado sem subir o servidor', () => {
  let executou = false;
  const resultado = executarServidor('context7', base({
    resolverBin: () => {
      throw new Error('ENOENT detalhe');
    },
    executar: () => {
      executou = true;
      return { status: 0 };
    },
  }));

  assert.deepEqual(resultado, { codigo: 1, erro: 'binário do MCP não encontrado.' });
  assert.equal(executou, false);
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

test('falha de spawn do servidor é fechada e não expõe detalhe', () => {
  const resultado = executarServidor('context7', base({
    executar: () => ({ error: new Error('detalhe interno'), status: null }),
  }));

  assert.deepEqual(resultado, { codigo: 1, erro: 'falha ao iniciar o servidor MCP.' });
  assert.doesNotMatch(resultado.erro, /detalhe interno/);
});

test('código de saída do servidor é propagado', () => {
  assert.deepEqual(
    executarServidor('context7', base({ executar: () => ({ status: 7 }) })),
    { codigo: 7, erro: 'servidor MCP terminou com falha.' },
  );
});

test('dependências do MCP fixadas em versão exata e com lockfile', () => {
  const pasta = path.join(__dirname);
  const pacote = JSON.parse(fs.readFileSync(path.join(pasta, 'package.json'), 'utf8'));
  assert.deepEqual(pacote.dependencies, {
    '@upstash/context7-mcp': '4.4.4',
    '@21st-dev/magic': '0.2.3',
  });
  const lock = fs.readFileSync(path.join(pasta, 'package-lock.json'), 'utf8');
  assert.match(lock, /"node_modules\/@upstash\/context7-mcp"/);
  assert.match(lock, /"node_modules\/@21st-dev\/magic"/);
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
