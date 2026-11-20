// Funções puras de `camadas.js` (T4.1) e o molde das três telas. Sem pacote novo: `node:test`, como `redefinir-senha.test.js`.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const {
  mensagemDoErro, urlDoEnvio, montarPublicacao, linhasDoResumo, contarNos, textoDosNos, criarNo,
} = require('./camadas.js');

const PROJETO = path.join(__dirname, '..', '..');
const TEMPLATES = path.join(PROJETO, 'templates');
const ENVIO = '11111111-2222-3333-4444-555555555555';

test('erro com lista de recusas junta as mensagens, sem valor de atributo nem caminho interno', () => {
  const corpo = { detalhe: 'recusado', erros: ['envio expirado: envie o arquivo de novo', 'feição 3: anel aberto'] };
  assert.equal(mensagemDoErro(422, corpo), 'envio expirado: envie o arquivo de novo feição 3: anel aberto');
});

test('erro conhecido da API vira texto em português; detalhe desconhecido cai na mensagem genérica', () => {
  assert.match(mensagemDoErro(404, { detalhe: 'nao_encontrado' }), /expirado ou você não tem acesso/);
  assert.equal(mensagemDoErro(403, { detalhe: 'negado' }), 'Você não tem permissão para esta ação.');
  assert.equal(mensagemDoErro(500, { detalhe: 'algo_inesperado' }), 'Não foi possível concluir. Tente de novo.');
});

test('arquivo grande demais (413) tem mensagem própria, mesmo sem corpo JSON', () => {
  assert.match(mensagemDoErro(413, {}), /grande demais/);
  assert.match(mensagemDoErro(413, null), /grande demais/);
});

test('URL da prévia troca o id modelo pelo id real do envio', () => {
  const modelo = '/empresa/1/fazenda/2/camadas/envio/00000000-0000-0000-0000-000000000000';
  assert.equal(urlDoEnvio(modelo, ENVIO), `/empresa/1/fazenda/2/camadas/envio/${ENVIO}`);
  assert.equal(urlDoEnvio('/sem/modelo/', ENVIO), '/sem/modelo/');
});

test('publicação sem divisão por coluna leva a sugestão de nó da prévia, feição por feição', () => {
  const campos = {
    estudo_id: '7', camada_id: '', nome: 'Solos sintéticos', tema: 'Solo', origem: 'Levantamento sintético',
    ocultos: ['cpf_sintetico'], coluna_no: '', sistema_confirmado: true,
  };
  const corpo = montarPublicacao(campos, { nos_sugeridos: [4, null, 9] });
  assert.deepEqual(corpo, {
    estudo_id: 7, metadados: { nome: 'Solos sintéticos', tema: 'Solo', origem: 'Levantamento sintético' },
    camada_id: null, ocultos: ['cpf_sintetico'], coluna_no: null, nos: [4, null, 9], sistema_confirmado: true,
  });
});

test('publicação com divisão por coluna manda nós vazios: o servidor deriva o nó do nome da coluna (D119)', () => {
  const corpo = montarPublicacao({ estudo_id: '1', camada_id: 'abc', coluna_no: 'talhao', ocultos: [], sistema_confirmado: false },
    { nos_sugeridos: [4, 4] });
  assert.deepEqual(corpo.nos, []);
  assert.equal(corpo.coluna_no, 'talhao');
  assert.equal(corpo.camada_id, 'abc');
  assert.equal(corpo.sistema_confirmado, false);
});

test('prévia sem nós sugeridos ou sem confirmação de sistema não quebra a montagem', () => {
  const corpo = montarPublicacao({ estudo_id: '1', ocultos: [], coluna_no: '' }, {});
  assert.deepEqual(corpo.nos, []);
  assert.equal(corpo.sistema_confirmado, false);
});

test('resumo mostra ausente como "Sem dados" e zero como zero (R10: ausente nunca vira zero)', () => {
  const linhas = Object.fromEntries(linhasDoResumo({ formato: 'shapefile', sistema: null, contagem: 0, transformacao: '' }));
  assert.equal(linhas['Sistema de referência'], 'Sem dados');
  assert.equal(linhas.Feições, '0');
  assert.equal(linhas.Transformação, '');
  assert.equal(linhas.Formato, 'shapefile');
});

test('contagem de nós separa feição com sugestão de feição sem nó', () => {
  assert.deepEqual(contarNos([1, null, 2, null]), { comNo: 2, semNo: 2 });
  assert.equal(textoDosNos([1, 2]), '2 feições com nó sugerido.');
  assert.match(textoDosNos([null]), /0 feições com nó sugerido e 1 sem nó/);
  assert.equal(textoDosNos([]), '0 feições com nó sugerido.');
});

test('texto vindo do arquivo com marcação entra como texto, nunca como HTML (R21)', () => {
  const documento = { createElement: (marcador) => ({ tagName: marcador, textContent: '', innerHTML: '' }) };
  const hostil = '<script>alert("x")</script><img src=x onerror=alert(1)>';
  const no = criarNo(documento, 'li', hostil);
  assert.equal(no.textContent, hostil);
  assert.equal(no.innerHTML, '');
  assert.equal(no.tagName, 'li');
});

test('as três telas carregam camadas.js por src, com nonce, e não levam script inline', () => {
  for (const nome of ['camadas_envio.html', 'camadas_previa.html', 'camadas_confirmacao.html']) {
    const html = fs.readFileSync(path.join(TEMPLATES, nome), 'utf8');
    assert.match(html, /<script src="\{% static 'projeto\/camadas\.js' %\}" \{% csp_nonce_attr %\}><\/script>/, nome);
    assert.doesNotMatch(html, /<script>(?!<\/script>)/, nome);
  }
});
