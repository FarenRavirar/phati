// Executa o agrion-componentes.js real: fechar aviso, arrastar e soltar na zona de envio, e diálogo nativo.
const test = require('node:test');
const assert = require('node:assert/strict');
const componentes = require('./agrion-componentes.js');

function camel(texto) {
  return texto.replace(/-([a-z])/g, (_, letra) => letra.toUpperCase());
}

// Casa só os seletores que o script usa: `.classe`, `[data-x-y]` e tag simples.
function casa(no, seletor) {
  if (seletor.startsWith('.')) return no.classes.includes(seletor.slice(1));
  const dado = /^\[data-([a-z-]+)\]$/.exec(seletor);
  if (dado) return camel(dado[1]) in no.dataset;
  return no.localName === seletor;
}

// Nó mínimo: `closest` sobe pelos pais; `querySelector` devolve o filho previsto no teste.
function no(tipo, { classes = [], pai = null, dataset = {}, filhos = {}, ...resto } = {}) {
  const n = {
    localName: tipo, classes, pai, dataset, filhos, atributos: {}, hidden: false, cliques: 0, fechado: 0, abertos: 0,
    ...resto,
    closest(seletor) {
      for (let atual = n; atual; atual = atual.pai) if (casa(atual, seletor)) return atual;
      return null;
    },
    querySelector: (seletor) => filhos[seletor] || null,
    setAttribute(nome, valor) { n.atributos[nome] = valor; },
    removeAttribute(nome) { delete n.atributos[nome]; },
    click() { n.cliques += 1; },
    close() { n.fechado += 1; },
    showModal() { n.abertos += 1; },
    dispatchEvent(evento) { n.disparado = evento.type; },
  };
  return n;
}

function evento(alvo, resto = {}) {
  const e = { target: alvo, prevenido: 0, ...resto };
  e.preventDefault = () => { e.prevenido += 1; };
  return e;
}

function documento(dialogos = {}, botoesFechar = []) {
  return {
    getElementById: (id) => dialogos[id] || null,
    querySelectorAll: (seletor) => (seletor === '.ag-aviso-fechar' ? botoesFechar : []),
    addEventListener() {},
  };
}

test('Fechar aviso esconde o aviso que contém o botão; botão sem aviso não faz nada', () => {
  const aviso = no('div', { classes: ['ag-aviso'] });
  const botao = no('button', { classes: ['ag-aviso-fechar'], pai: aviso });
  assert.equal(componentes.fecharAviso(botao), true);
  assert.equal(aviso.hidden, true);
  assert.equal(componentes.fecharAviso(no('button', { classes: ['ag-aviso-fechar'] })), false);
});

test('ao carregar, o script libera o botão Fechar aviso que nasce hidden', () => {
  const botao = no('button', { classes: ['ag-aviso-fechar'], hidden: true });
  componentes.iniciar(documento({}, [botao]));
  assert.equal(botao.hidden, false);
});

test('clique na zona de envio (label) não é tratado aqui: o navegador abre o seletor sozinho (negativo)', () => {
  const zona = no('label', { classes: ['ag-envio'] });
  const e = evento(no('span', { pai: zona }));
  assert.equal(componentes.aoClicar(documento(), e), false);
  assert.equal(e.prevenido, 0);
});

test('arrastar sobre a zona marca; soltar o arquivo põe no input e avisa a troca', () => {
  const entrada = no('input');
  const zona = no('label', { classes: ['ag-envio'], filhos: { 'input[type="file"]': entrada } });
  const arrasto = evento(zona);
  assert.equal(componentes.aoArrastar(arrasto, true), true);
  assert.equal(zona.dataset.arrastando, '');
  assert.equal(arrasto.prevenido, 1);
  const arquivos = [{ name: 'camada.zip' }];
  componentes.aoSoltar(evento(zona, { dataTransfer: { files: arquivos } }));
  assert.equal(entrada.files, arquivos);
  assert.equal(entrada.disparado, 'change');
  assert.equal('arrastando' in zona.dataset, false);
});

test('soltar sem arquivo não troca o input; arrastar fora da zona não é tratado', () => {
  const entrada = no('input');
  const zona = no('label', { classes: ['ag-envio'], filhos: { 'input[type="file"]': entrada } });
  componentes.aoSoltar(evento(zona, { dataTransfer: { files: [] } }));
  assert.equal(entrada.files, undefined);
  assert.equal(entrada.disparado, undefined);
  const fora = evento(no('div'));
  assert.equal(componentes.aoArrastar(fora, true), false);
  assert.equal(fora.prevenido, 0);
});

test('soltar sem dataTransfer (navegador sem arquivo no evento) não quebra', () => {
  const entrada = no('input');
  const zona = no('label', { classes: ['ag-envio'], filhos: { 'input[type="file"]': entrada } });
  assert.equal(componentes.aoSoltar(evento(zona)), false);
  assert.equal(entrada.disparado, undefined);
});

test('link com data-dialogo-abrir abre o diálogo nativo e impede a navegação', () => {
  const dialogo = no('dialog');
  const link = no('a', { dataset: { dialogoAbrir: 'convidar' } });
  const e = evento(link);
  assert.equal(componentes.aoClicar(documento({ convidar: dialogo }), e), true);
  assert.equal(dialogo.abertos, 1);
  assert.equal(e.prevenido, 1);
});

test('sem showModal (navegador sem <dialog>) o link segue para a página de formulário', () => {
  const link = no('a', { dataset: { dialogoAbrir: 'convidar' } });
  const e = evento(link);
  assert.equal(componentes.aoClicar(documento({ convidar: {} }), e), false);
  assert.equal(e.prevenido, 0);
});

test('link para diálogo que não existe na página não abre nada', () => {
  const link = no('a', { dataset: { dialogoAbrir: 'nao-existe' } });
  const e = evento(link);
  assert.equal(componentes.aoClicar(documento(), e), false);
  assert.equal(e.prevenido, 0);
});

test('Fechar e clique no fundo fecham o diálogo; clique comum dentro dele não', () => {
  const dialogo = no('dialog');
  const botao = no('button', { dataset: { dialogoFechar: '' }, pai: dialogo });
  componentes.aoClicar(documento(), evento(botao));
  assert.equal(dialogo.fechado, 1);
  componentes.aoClicar(documento(), evento(dialogo));
  assert.equal(dialogo.fechado, 2);
  const texto = evento(no('p', { pai: dialogo }));
  assert.equal(componentes.aoClicar(documento(), texto), false);
  assert.equal(dialogo.fechado, 2);
});
