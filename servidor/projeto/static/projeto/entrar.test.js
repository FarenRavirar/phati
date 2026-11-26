'use strict';
// Script real da tela Entrar (`entrar.js`) contra elementos mínimos: campo vazio não envia, envio ocupa o botão.
const test = require('node:test');
const assert = require('node:assert/strict');
const { aoEnviar, ocupar, liberar, MENSAGEM_VAZIO } = require('./entrar.js');

function elemento(atributos = {}) {
  const el = {
    value: '', disabled: false, hidden: false, textContent: '', filhos: [], atributos: {},
    setAttribute(nome, valor) { this.atributos[nome] = String(valor); },
    removeAttribute(nome) { delete this.atributos[nome]; },
    prepend(filho) { this.filhos.unshift(filho); },
    querySelector() { return this.filhos.find((f) => f.className === 'ag-giro') ?? null; },
    ...atributos,
  };
  el.ownerDocument = { createElement: () => ({ className: '', atributos: {}, setAttribute(n, v) { this.atributos[n] = v; }, remove() { el.filhos = el.filhos.filter((f) => f !== this); } }) };
  return el;
}

function montar(cpf, senha) {
  const aviso = elemento({ hidden: true });
  aviso.querySelector = () => elemento({ textContent: '' });
  return {
    cpf: elemento({ value: cpf }),
    senha: elemento({ value: senha }),
    aviso,
    botao: elemento(),
  };
}

function evento() {
  return { prevenido: false, preventDefault() { this.prevenido = true; } };
}

test('campo vazio bloqueia o envio e mostra a mensagem', () => {
  const campos = montar('', 'senha');
  const e = evento();
  assert.equal(aoEnviar(e, campos), false);
  assert.equal(e.prevenido, true);
  assert.equal(campos.aviso.hidden, false);
});

test('senha vazia também bloqueia e mostra a mensagem certa', () => {
  const campos = montar('52998224725', '');
  const texto = elemento();
  campos.aviso.querySelector = () => texto;
  assert.equal(aoEnviar(evento(), campos), false);
  assert.equal(texto.textContent, MENSAGEM_VAZIO);
});

test('CPF só de espaços conta como vazio', () => {
  assert.equal(aoEnviar(evento(), montar('   ', 'senha')), false);
});

test('campos preenchidos deixam o envio seguir e ocupam o botão', () => {
  const campos = montar('52998224725', 'senha');
  const e = evento();
  assert.equal(aoEnviar(e, campos), true);
  assert.equal(e.prevenido, false);
  assert.equal(campos.botao.disabled, true);
  assert.equal(campos.botao.atributos['aria-busy'], 'true');
  assert.equal(campos.botao.filhos.length, 1);
});

test('liberar desfaz o giro e o aria-busy (volta pelo histórico)', () => {
  const botao = elemento();
  ocupar(botao);
  liberar(botao);
  assert.equal(botao.disabled, false);
  assert.equal('aria-busy' in botao.atributos, false);
  assert.equal(botao.filhos.length, 0);
});

test('controle negativo: sem a checagem o vazio enviaria (o teste reprova esse caso)', () => {
  const campos = montar('', '');
  // Mutação manual conferida: trocar `&&` por `||` em entrar.js faz `aoEnviar` aceitar o envio e este teste falha.
  assert.equal(aoEnviar(evento(), campos), false);
});
