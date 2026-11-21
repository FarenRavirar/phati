#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

// Versões ficam só em `package.json` e `package-lock.json` desta pasta. O wrapper não conhece versão nenhuma.
const DIR_MCP = __dirname;

const SERVIDORES = Object.freeze({
  context7: Object.freeze({ pacote: '@upstash/context7-mcp', exigeChave: false }),
  magic: Object.freeze({ pacote: '@21st-dev/magic', exigeChave: true }),
});

// Só o que o Node e o npm precisam para achar o executável e o cache. Variável fora desta lista (token do Git, segredo de
// outro serviço) não chega a pacote de terceiros; a chave do Magic entra à parte, só no processo do Magic.
const VARIAVEIS_BASE = Object.freeze(['PATH', 'SystemRoot', 'ComSpec', 'APPDATA', 'HOME', 'USERPROFILE', 'TEMP', 'TMP']);

const COMANDO_CHAVE_WINDOWS = "[Environment]::GetEnvironmentVariable('API_KEY_21ST','User')";

function envMinimo(ambiente) {
  const env = {};
  for (const nome of VARIAVEIS_BASE) {
    if (typeof ambiente[nome] === 'string') env[nome] = ambiente[nome];
  }
  return env;
}

function buscarChaveMagicWindows(executar) {
  const resultado = executar(
    'powershell.exe',
    ['-NoProfile', '-NonInteractive', '-Command', COMANDO_CHAVE_WINDOWS],
    {
      encoding: 'utf8',
      shell: false,
      stdio: ['ignore', 'pipe', 'ignore'],
      windowsHide: true,
    },
  );
  if (resultado.error || resultado.status !== 0 || typeof resultado.stdout !== 'string') return null;
  const chave = resultado.stdout.trim();
  return chave || null;
}

// Lê o `bin` do pacote já instalado. Um único `bin` (texto ou objeto de uma entrada) é o caso dos dois pacotes fixados.
function resolverBinario(pacote, dir = DIR_MCP) {
  const pasta = path.join(dir, 'node_modules', pacote);
  const meta = JSON.parse(fs.readFileSync(path.join(pasta, 'package.json'), 'utf8'));
  const bin = typeof meta.bin === 'string' ? meta.bin : Object.values(meta.bin ?? {})[0];
  if (typeof bin !== 'string' || !bin) throw new Error('bin ausente');
  return path.join(pasta, bin);
}

// Windows: `npm` é `npm.cmd`, que só roda por cmd.exe. Sem `windowsVerbatimArguments` o Node cita o argumento e
// troca as aspas internas por `\"`, e o npm recebe `--prefix \"dir\"`. Com a flag, o texto segue cru e `cmd /s`
// tira só as aspas externas (doc oficial do Node, child_process: "No quoting or escaping of arguments is done").
function montarInstalacao(plataforma, env, dir) {
  if (plataforma === 'win32') {
    return {
      comando: env.ComSpec,
      argumentos: ['/d', '/s', '/c', `"npm ci --ignore-scripts --prefix "${dir}""`],
      opcoes: { env, shell: false, stdio: 'inherit', windowsHide: true, windowsVerbatimArguments: true },
    };
  }
  return {
    comando: 'npm',
    argumentos: ['ci', '--ignore-scripts', '--prefix', dir],
    opcoes: { env, shell: false, stdio: 'inherit' },
  };
}

// shortcut: só confere se a pasta node_modules existe; instalação corrompida exige apagar a pasta à mão.
// Subir quando houver atualização automática de dependências: comparar com o package-lock.json.
function instalarDependencias(executar, plataforma, env, dir) {
  if (plataforma === 'win32' && !env.ComSpec) return 'ComSpec ausente.';
  const { comando, argumentos, opcoes } = montarInstalacao(plataforma, env, dir);
  const resultado = executar(comando, argumentos, opcoes);
  if (resultado.error || resultado.status !== 0) return 'falha ao instalar dependências do MCP.';
  return null;
}

function executarServidor(
  id,
  {
    plataforma = process.platform,
    ambiente = process.env,
    executar = spawnSync,
    existe = fs.existsSync,
    resolverBin = (pacote) => resolverBinario(pacote, DIR_MCP),
    dir = DIR_MCP,
  } = {},
) {
  const servidor = SERVIDORES[id];
  if (!servidor) return { codigo: 64, erro: 'servidor MCP desconhecido.' };

  const env = envMinimo(ambiente);
  const envInstalacao = { ...env }; // cópia antes da chave: o npm ci não recebe o segredo do Magic
  if (servidor.exigeChave) {
    let chave = typeof ambiente.API_KEY_21ST === 'string' && ambiente.API_KEY_21ST.length > 0
      ? ambiente.API_KEY_21ST
      : null;
    if (!chave && plataforma === 'win32') chave = buscarChaveMagicWindows(executar);
    if (!chave) return { codigo: 1, erro: 'API_KEY_21ST ausente.' };
    env.API_KEY_21ST = chave;
  }

  if (!existe(path.join(dir, 'node_modules'))) {
    const erroInstalacao = instalarDependencias(executar, plataforma, envInstalacao, dir);
    if (erroInstalacao) return { codigo: 1, erro: erroInstalacao };
  }

  let bin;
  try {
    bin = resolverBin(servidor.pacote);
  } catch {
    return { codigo: 1, erro: 'binário do MCP não encontrado.' };
  }

  const resultado = executar(process.execPath, [bin], { env, shell: false, stdio: 'inherit' });

  if (resultado.error) return { codigo: 1, erro: 'falha ao iniciar o servidor MCP.' };
  if (!Number.isInteger(resultado.status)) return { codigo: 1, erro: 'servidor MCP terminou sem código de saída.' };
  return { codigo: resultado.status, erro: resultado.status === 0 ? null : 'servidor MCP terminou com falha.' };
}

if (require.main === module) {
  const resultado = executarServidor(process.argv[2]);
  if (resultado.erro) process.stderr.write(`[mcp] ${resultado.erro}\n`);
  process.exitCode = resultado.codigo;
}

module.exports = { executarServidor, montarInstalacao };
