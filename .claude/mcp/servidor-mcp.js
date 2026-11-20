#!/usr/bin/env node

const { spawnSync } = require('node:child_process');

const SERVIDORES = Object.freeze({
  context7: Object.freeze({
    argumentos: Object.freeze(['-y', '@upstash/context7-mcp@4.4.4']),
    comandoWindows: 'npx -y @upstash/context7-mcp@4.4.4',
    exigeChave: false,
  }),
  magic: Object.freeze({
    argumentos: Object.freeze(['-y', '@21st-dev/magic@0.2.3']),
    comandoWindows: 'npx -y @21st-dev/magic@0.2.3',
    exigeChave: true,
  }),
});

// Só o que o npx precisa para achar o Node e o cache. Variável fora desta lista (token do Git, segredo de outro serviço)
// não chega a pacote de terceiros; a chave do Magic entra à parte, só quando o servidor a exige.
const VARIAVEIS_BASE = Object.freeze(['PATH', 'SystemRoot', 'ComSpec', 'APPDATA', 'HOME', 'USERPROFILE', 'TEMP', 'TMP']);

const COMANDO_CHAVE_WINDOWS ="[Environment]::GetEnvironmentVariable('API_KEY_21ST','User')";

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

function executarServidor(
  id,
  {
    plataforma = process.platform,
    ambiente = process.env,
    executar = spawnSync,
  } = {},
) {
  const servidor = SERVIDORES[id];
  if (!servidor) return { codigo: 64, erro: 'servidor MCP desconhecido.' };

  const env = {};
  for (const nome of VARIAVEIS_BASE) {
    if (typeof ambiente[nome] === 'string') env[nome] = ambiente[nome];
  }
  if (servidor.exigeChave) {
    let chave = typeof ambiente.API_KEY_21ST === 'string' && ambiente.API_KEY_21ST.length > 0
      ? ambiente.API_KEY_21ST
      : null;
    if (!chave && plataforma === 'win32') chave = buscarChaveMagicWindows(executar);
    if (!chave) return { codigo: 1, erro: 'API_KEY_21ST ausente.' };
    env.API_KEY_21ST = chave;
  }

  let resultado;
  if (plataforma === 'win32') {
    const comspec = env.ComSpec;
    if (!comspec) return { codigo: 1, erro: 'ComSpec ausente.' };
    resultado = executar(
      comspec,
      ['/d', '/s', '/c', servidor.comandoWindows],
      { env, shell: false, stdio: 'inherit', windowsHide: true },
    );
  } else {
    resultado = executar(
      'npx',
      [...servidor.argumentos],
      { env, shell: false, stdio: 'inherit' },
    );
  }

  if (resultado.error) return { codigo: 1, erro: 'falha ao iniciar o servidor MCP.' };
  if (!Number.isInteger(resultado.status)) return { codigo: 1, erro: 'servidor MCP terminou sem código de saída.' };
  return { codigo: resultado.status, erro: resultado.status === 0 ? null : 'servidor MCP terminou com falha.' };
}

if (require.main === module) {
  const resultado = executarServidor(process.argv[2]);
  if (resultado.erro) process.stderr.write(`[mcp] ${resultado.erro}\n`);
  process.exitCode = resultado.codigo;
}

module.exports = { executarServidor };
