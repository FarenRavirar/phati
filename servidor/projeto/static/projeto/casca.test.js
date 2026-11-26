// Executa o casca.js real com um DOM mínimo: gaveta, seletor de escopo, Esc e a ausência de casca. Sem pacote novo: `node:test`.
const test = require('node:test');
const assert = require('node:assert/strict');
const { iniciarCasca } = require('./casca.js');

// Nó mínimo: `hidden`, atributos e ouvintes; `querySelector` devolve o filho previsto, `closest` vale para o alvo do clique.
function no(tipo, { filhos = {}, atributos = {}, hidden = false, pai = null } = {}) {
  const ouvintes = {};
  const n = {
    tipo, hidden, atributos, dataset: {}, filhos, pai, foco: 0,
    setAttribute(nome, valor) { n.atributos[nome] = String(valor); },
    removeAttribute(nome) { delete n.atributos[nome]; },
    hasAttribute(nome) { return nome in n.atributos; },
    addEventListener(evento, funcao) { (ouvintes[evento] = ouvintes[evento] || []).push(funcao); },
    dispara(evento, alvo = n) { for (const f of ouvintes[evento] || []) f({ key: evento.replace('keydown', ''), target: alvo }); },
    focus() { n.foco += 1; },
    querySelector(seletor) { return filhos[seletor] || null; },
    closest(seletor) {
      for (let atual = n; atual; atual = atual.pai) if (atual.tipo === seletor) return atual;
      return null;
    },
  };
  return n;
}

// Documento com a casca: botão Abrir menu, fundo, sidebar com um link, botão e lista do seletor.
function casca() {
  const link = no('a');
  const abrir = no('button', { atributos: { 'data-abrir-menu': '' }, hidden: true });
  const fundo = no('div');
  const botao = no('button', { hidden: true });
  const lista = no('div', { hidden: true });
  const resumo = no('summary');
  // Link do seletor de escopo, escondido: o foco da gaveta não pode cair nele (o `a` genérico responde a ele).
  const linkEscondido = no('a', { hidden: true });
  const sidebar = no('aside', { filhos: { '.ag-nav-principal a': link, a: linkEscondido } });
  link.pai = sidebar;
  const raiz = no('div', { filhos: {
    '[data-abrir-menu]': abrir, '[data-gaveta-fundo]': fundo, '.ag-sidebar': sidebar,
    '[data-escopo-abrir]': botao, '[data-escopo-lista]': lista, '.ag-sidebar-resumo': resumo,
  } });
  const ouvintesDoDocumento = {};
  const documento = {
    querySelector(seletor) { return seletor === '.ag-casca' ? raiz : null; },
    addEventListener(evento, funcao) { (ouvintesDoDocumento[evento] = ouvintesDoDocumento[evento] || []).push(funcao); },
    tecla(tecla) { for (const f of ouvintesDoDocumento.keydown || []) f({ key: tecla }); },
  };
  return { documento, raiz, abrir, fundo, botao, lista, link, linkEscondido, sidebar, resumo };
}

test('a gaveta abre pelo botão, leva o foco ao primeiro link e marca a casca', () => {
  const c = casca();
  iniciarCasca(c.documento);
  assert.equal(c.raiz.dataset.js, '');
  assert.equal(c.abrir.hidden, false);
  assert.equal(c.resumo.hidden, true);
  c.abrir.dispara('click');
  assert.equal(('gaveta' in c.raiz.dataset), true);
  assert.equal(c.abrir.atributos['aria-expanded'], 'true');
  assert.equal(c.link.foco, 1);
  assert.equal(c.linkEscondido.foco, 0); // negativo: link escondido não recebe foco
});

test('escolher um item fecha a gaveta, sem devolver o foco ao botão', () => {
  const c = casca();
  iniciarCasca(c.documento);
  c.abrir.dispara('click');
  c.sidebar.dispara('click', c.link); // o clique sobe da link até a sidebar, onde o ouvinte está
  assert.equal(('gaveta' in c.raiz.dataset), false);
  assert.equal(c.abrir.foco, 0);
});

test('clique no fundo fecha a gaveta e devolve o foco ao botão que a abriu', () => {
  const c = casca();
  iniciarCasca(c.documento);
  c.abrir.dispara('click');
  c.fundo.dispara('click');
  assert.equal(('gaveta' in c.raiz.dataset), false);
  assert.equal(c.abrir.foco, 1);
});

test('Esc fecha a gaveta aberta e devolve o foco ao botão', () => {
  const c = casca();
  iniciarCasca(c.documento);
  c.abrir.dispara('click');
  c.documento.tecla('Escape');
  assert.equal(('gaveta' in c.raiz.dataset), false);
  assert.equal(c.abrir.foco, 1);
});

test('Esc sem nada aberto não mexe em foco nem estado (negativo)', () => {
  const c = casca();
  iniciarCasca(c.documento);
  c.documento.tecla('Escape');
  assert.equal(c.abrir.foco, 0);
  assert.equal(c.botao.foco, 0);
});

test('tecla que não é Esc não fecha a gaveta (negativo)', () => {
  const c = casca();
  iniciarCasca(c.documento);
  c.abrir.dispara('click');
  c.documento.tecla('Enter');
  assert.equal(('gaveta' in c.raiz.dataset), true);
});

test('o seletor de escopo abre e fecha pelo botão e marca aria-expanded', () => {
  const c = casca();
  iniciarCasca(c.documento);
  c.botao.dispara('click');
  assert.equal(c.lista.hidden, false);
  assert.equal(c.botao.atributos['aria-expanded'], 'true');
  c.botao.dispara('click');
  assert.equal(c.lista.hidden, true);
  assert.equal(c.botao.atributos['aria-expanded'], 'false');
});

test('Esc fecha o seletor e devolve o foco ao botão dele, sem tocar na gaveta', () => {
  const c = casca();
  iniciarCasca(c.documento);
  c.botao.dispara('click');
  c.abrir.dispara('click');
  c.documento.tecla('Escape');
  assert.equal(c.lista.hidden, true);
  assert.equal(c.botao.foco, 1);
  assert.equal(('gaveta' in c.raiz.dataset), true);
});

test('sem casca na página, nada é ligado e nada quebra (negativo)', () => {
  const sem = { querySelector: () => null, addEventListener() { throw new Error('não deveria ligar ouvinte'); } };
  assert.equal(iniciarCasca(sem), null);
});
