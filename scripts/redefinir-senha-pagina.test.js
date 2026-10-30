// Executa o script real de servidor/projeto/templates/redefinir_senha.html contra um DOM mínimo (Codex e Greptile, PR #17:
// teste que procura texto no HTML passa mesmo com o script quebrado). Sem pacote novo: `node:vm` e `node:test`.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const HTML = fs.readFileSync(path.join(__dirname, '..', 'servidor', 'projeto', 'templates', 'redefinir_senha.html'), 'utf8');
const SCRIPT = HTML.match(/<script>([\s\S]*?)<\/script>/)[1];

function elemento(hidden = false) {
  const ouvintes = {};
  return { hidden, textContent: '', value: '', disabled: false, ouvintes, addEventListener(nome, funcao) { ouvintes[nome] = funcao; } };
}

function abrir(hash, respostas) {
  const el = {
    mensagem: elemento(true), formulario: elemento(true), senha_nova: elemento(), repeticao: elemento(), salvar: elemento(),
  };
  const chamadas = [];
  const substituicoes = [];
  const fila = [...respostas];
  const contexto = {
    URLSearchParams, JSON, Promise,
    document: { getElementById: (id) => el[id] },
    location: { hash, pathname: '/redefinir-senha' },
    history: { replaceState: (...argumentos) => substituicoes.push(argumentos) },
    fetch: (url, opcoes) => {
      chamadas.push({ url, corpo: JSON.parse(opcoes.body), cabecalhos: opcoes.headers });
      return fila.shift()();
    },
  };
  vm.runInNewContext(SCRIPT, contexto);
  const enviar = async (senha = 'uma frase longa e incomum', repeticao = senha) => {
    el.senha_nova.value = senha;
    el.repeticao.value = repeticao;
    await el.formulario.ouvintes.submit({ preventDefault() {} });
  };
  return { el, chamadas, substituicoes, enviar };
}

const resposta = (status, corpo = {}) => () => Promise.resolve({ status, json: () => Promise.resolve(corpo) });

test('lê o segredo do fragmento, apaga o fragmento do histórico e mostra o formulário', () => {
  const pagina = abrir('#segredo=abc123', []);
  assert.deepEqual(JSON.parse(JSON.stringify(pagina.substituicoes)), [[null, '', '/redefinir-senha']]);
  assert.equal(pagina.el.formulario.hidden, false);
  assert.equal(pagina.el.mensagem.hidden, true);
});

test('sem segredo no fragmento mostra link inválido e não mostra o formulário', () => {
  const pagina = abrir('', []);
  assert.equal(pagina.el.formulario.hidden, true);
  assert.match(pagina.el.mensagem.textContent, /não vale mais/);
});

test('senhas diferentes não chamam a API', async () => {
  const pagina = abrir('#segredo=abc123', []);
  await pagina.enviar('uma frase longa e incomum', 'outra coisa');
  assert.equal(pagina.chamadas.length, 0);
  assert.match(pagina.el.mensagem.textContent, /não são iguais/);
});

test('sucesso envia segredo e senha em JSON, esconde o formulário e fica final', async () => {
  const pagina = abrir('#segredo=abc123', [resposta(204)]);
  await pagina.enviar();
  // JSON na ida e na volta: objeto criado dentro do `vm` tem outro protótipo e o `deepEqual` estrito recusaria.
  assert.deepEqual(JSON.parse(JSON.stringify(pagina.chamadas[0])), {
    url: '/api/v1/redefinir-senha/confirmar',
    corpo: { segredo: 'abc123', senha_nova: 'uma frase longa e incomum' },
    cabecalhos: { 'Content-Type': 'application/json' },
  });
  assert.equal(pagina.el.formulario.hidden, true);
  assert.match(pagina.el.mensagem.textContent, /Senha alterada/);
  assert.equal(pagina.el.salvar.disabled, true);
});

test('link inválido esconde o formulário', async () => {
  const pagina = abrir('#segredo=velho', [resposta(400, { detalhe: 'link_invalido' })]);
  await pagina.enviar();
  assert.equal(pagina.el.formulario.hidden, true);
  assert.match(pagina.el.mensagem.textContent, /não vale mais/);
});

test('senha recusada mostra o motivo e libera nova tentativa', async () => {
  const pagina = abrir('#segredo=abc123', [resposta(400, { detalhe: 'senha_curta' })]);
  await pagina.enviar();
  assert.match(pagina.el.mensagem.textContent, /curta demais/);
  assert.equal(pagina.el.formulario.hidden, false);
  assert.equal(pagina.el.salvar.disabled, false);
});

test('falha de conexão avisa, não deixa a página muda e libera nova tentativa (Qodo e Greptile, PR #17)', async () => {
  const pagina = abrir('#segredo=abc123', [() => Promise.reject(new TypeError('Failed to fetch'))]);
  await pagina.enviar();
  assert.match(pagina.el.mensagem.textContent, /Sem conexão/);
  assert.equal(pagina.el.formulario.hidden, false);
  assert.equal(pagina.el.salvar.disabled, false);
});

test('segundo envio enquanto o primeiro corre não chama a API de novo e o sucesso não vira erro (Codex, PR #17)', async () => {
  let liberar;
  const lenta = () => new Promise((resolver) => { liberar = () => resolver({ status: 204, json: () => Promise.resolve({}) }); });
  const pagina = abrir('#segredo=abc123', [lenta, resposta(400, { detalhe: 'link_invalido' })]);
  const primeiro = pagina.enviar();
  await pagina.enviar();
  liberar();
  await primeiro;
  assert.equal(pagina.chamadas.length, 1);
  assert.match(pagina.el.mensagem.textContent, /Senha alterada/);
});
