// Telas de camadas do Administrador (008 T4.1): envio, prévia e publicação. Cada tela chama os endpoints da API do catálogo
// (`catalogo/api.py`); nenhuma regra de permissão ou de domínio mora aqui. Texto que vem do arquivo entra só por
// `textContent` (R21): marcação do arquivo aparece como texto, nunca como HTML.

const TEXTO_DO_DETALHE = {
  nao_encontrado: 'Este envio não está disponível: ele pode ter expirado ou você não tem acesso. Envie o arquivo de novo.',
  negado: 'Você não tem permissão para esta ação.',
  entrada_invalida: 'Algum campo está inválido. Confira o formulário.',
  troca_de_senha_obrigatoria: 'Troque a senha antes de continuar.',
};
// Igual ao `ENVIO_MODELO` de `camadas_paginas.py`: as URLs das telas levam este id no lugar do envio.
const ENVIO_MODELO = '00000000-0000-0000-0000-000000000000';

function mensagemDoErro(status, corpo) {
  if (corpo && Array.isArray(corpo.erros) && corpo.erros.length > 0) return corpo.erros.map(String).join(' ');
  if (corpo && TEXTO_DO_DETALHE[corpo.detalhe]) return TEXTO_DO_DETALHE[corpo.detalhe];
  if (status === 413) return 'O arquivo é grande demais. Reduza o arquivo e envie de novo.';
  return 'Não foi possível concluir. Tente de novo.';
}

function urlDoEnvio(modelo, envioId) {
  return modelo.replace(ENVIO_MODELO, envioId);
}

// Corpo de `catalogo_publicar` (EntradaPublicacao). Com divisão por coluna, o nó vem do nome da coluna (D119) e `nos` fica
// vazio. Sem ela, vai a sugestão de nó da prévia, feição por feição; o servidor recusa o que faltar.
// Acima deste número de itens a revisão não vira lista de selects: a divisão por coluna é o caminho (R7 e R12, tela leve).
const LIMITE_DE_ITENS_DE_REVISAO = 50;
const ROTULO_PROPRIA_FAZENDA = 'Própria fazenda';
const ROTULO_ESCOLHA_NO = 'Escolha o nó';

// Nó de cada feição para a publicação. Feição da revisão recebe a escolha da pessoa (`null` = própria fazenda); as demais, a
// sugestão da prévia. Sem escolha, vale a sugestão.
function montarNos(previa, escolhas) {
  return (previa.nos_sugeridos || []).map((sugerido, indice) => (
    Object.hasOwn(escolhas, indice + 1) ? escolhas[indice + 1] : sugerido
  ));
}

function montarPublicacao(campos, previa) {
  return {
    estudo_id: Number(campos.estudo_id),
    metadados: { nome: campos.nome, tema: campos.tema, origem: campos.origem },
    camada_id: campos.camada_id || null,
    ocultos: campos.ocultos,
    coluna_no: campos.coluna_no || null,
    nos: campos.coluna_no ? [] : montarNos(previa, campos.escolhas || {}),
    sistema_confirmado: Boolean(campos.sistema_confirmado),
  };
}

// Opções do select de uma feição: a própria fazenda (nó nulo) e os nós ativos da fazenda, vindos do servidor.
function opcoesDeNo(nosDaFazenda) {
  return [{ valor: '', rotulo: ROTULO_PROPRIA_FAZENDA }, ...nosDaFazenda.map((no) => ({ valor: String(no.no), rotulo: no.nome }))];
}

// Texto da feição na revisão, sem interpretar nada do arquivo: o motivo vem do servidor (`sugerir_no`).
function rotuloDaRevisao(item) {
  if (item.motivo === 'sem_intersecao' || item.motivo === 'abaixo_do_limiar') return `Feição ${item.indice}: fora de todos os nós. Fica na própria fazenda.`;
  if (item.motivo === 'empate') return `Feição ${item.indice}: empate entre os dois maiores nós. Escolha o nó.`;
  return `Feição ${item.indice}: cruza ${item.areas.length} nós. Confira o nó sugerido.`;
}

// Pares rótulo e valor do resumo. Valor ausente vira "Sem dados", nunca zero (R10).
function linhasDoResumo(previa) {
  const campos = [
    ['Formato', previa.formato],
    ['Tipo de geometria', previa.tipo],
    ['Sistema de referência', previa.sistema],
    ['Origem do sistema', previa.origem_sistema],
    ['Transformação', previa.transformacao],
    ['Feições', previa.contagem],
  ];
  return campos.map(([rotulo, valor]) => [rotulo, valor === null || valor === undefined ? 'Sem dados' : String(valor)]);
}

function contarNos(nosSugeridos) {
  const semNo = nosSugeridos.filter((no) => no === null).length;
  return { comNo: nosSugeridos.length - semNo, semNo };
}

function textoDosNos(nosSugeridos) {
  const { comNo, semNo } = contarNos(nosSugeridos);
  if (semNo === 0) return `${comNo} feições com nó sugerido.`;
  return `${comNo} feições com nó sugerido e ${semNo} sem nó: ficam na própria fazenda; troque o nó na lista abaixo se quiser.`;
}

// Nó de texto com `textContent`: é o único jeito de pôr texto do arquivo na tela (R21).
function criarNo(documento, marcador, texto) {
  const no = documento.createElement(marcador);
  no.textContent = texto;
  return no;
}

async function buscarJson(url, opcoes = {}) {
  const resposta = await fetch(url, { credentials: 'same-origin', ...opcoes });
  const corpo = await resposta.json().catch(() => ({}));
  return { status: resposta.status, corpo };
}

function tokenCsrf(formulario) {
  return formulario.querySelector('input[name="csrfmiddlewaretoken"]').value;
}

function mostrarAviso(documento, id, texto) {
  const caixa = documento.getElementById(id);
  caixa.querySelector('.aviso-texto').textContent = texto;
  caixa.hidden = false;
}

function iniciarEnvio(documento, secao) {
  const formulario = documento.getElementById('formulario-envio');
  const botao = documento.getElementById('enviar');
  formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    const arquivo = documento.getElementById('campo_arquivo').files[0];
    if (!arquivo) return mostrarAviso(documento, 'aviso-envio', 'Escolha um arquivo para enviar.');
    botao.disabled = true;
    botao.textContent = 'Enviando…';
    try {
      const corpo = new FormData();
      corpo.append('arquivo', arquivo);
      const { status, corpo: dados } = await buscarJson(secao.dataset.apiCriar, {
        method: 'POST', body: corpo, headers: { 'X-CSRFToken': tokenCsrf(formulario) },
      });
      if (status === 201) return globalThis.location.assign(urlDoEnvio(secao.dataset.urlPrevia, dados.envio_id));
      mostrarAviso(documento, 'aviso-envio', mensagemDoErro(status, dados));
    } catch {
      mostrarAviso(documento, 'aviso-envio', 'Sem conexão com o servidor. Tente de novo.');
    }
    botao.disabled = false;
    botao.textContent = 'Enviar para prévia';
  });
}

// Lê a prévia pela API. Falha de rede vira erro na tela, não promise sem tratamento; o aviso de carregamento sai nos dois casos.
async function carregarPrevia(documento, secao, idCarregando) {
  try {
    const { status, corpo } = await buscarJson(secao.dataset.apiPrevia);
    documento.getElementById(idCarregando).hidden = true;
    if (status !== 200) return { previa: null, erro: mensagemDoErro(status, corpo) };
    return { previa: corpo, erro: null };
  } catch {
    documento.getElementById(idCarregando).hidden = true;
    return { previa: null, erro: 'Sem conexão com o servidor. Recarregue a página.' };
  }
}

function desenharPrevia(documento, previa) {
  const resumo = documento.getElementById('previa-resumo');
  resumo.replaceChildren(...linhasDoResumo(previa).flatMap(([rotulo, valor]) => [
    criarNo(documento, 'dt', rotulo), criarNo(documento, 'dd', valor),
  ]));
  documento.getElementById('previa-avisos').replaceChildren(...previa.avisos.map((aviso) => criarNo(documento, 'li', aviso)));
  documento.getElementById('previa-colunas').replaceChildren(...previa.colunas.map((coluna) => criarNo(documento, 'li', coluna)));
  documento.getElementById('previa-nos').textContent = textoDosNos(previa.nos_sugeridos);
  documento.getElementById('previa-conteudo').hidden = false;
}

async function iniciarPrevia(documento, secao) {
  const { previa, erro } = await carregarPrevia(documento, secao, 'previa-carregando');
  if (erro) return mostrarAviso(documento, 'previa-erro', erro);
  desenharPrevia(documento, previa);
}

function marcarOcultos(documento, colunas) {
  const fieldset = documento.getElementById('campo-ocultos');
  colunas.forEach((coluna, indice) => {
    const rotulo = documento.createElement('label');
    rotulo.className = 'campo-caixa';
    const caixa = documento.createElement('input');
    caixa.type = 'checkbox';
    caixa.name = 'ocultos';
    caixa.value = coluna;
    caixa.id = `oculto_${indice}`;
    rotulo.append(caixa, ` ${coluna}`);
    fieldset.append(rotulo);
  });
}

function preencherDivisao(documento, colunas) {
  const seletor = documento.getElementById('campo_coluna_no');
  colunas.forEach((coluna) => {
    const opcao = documento.createElement('option');
    opcao.value = coluna;
    opcao.textContent = coluna;
    seletor.append(opcao);
  });
}

function lerCampos(documento) {
  const valor = (id) => documento.getElementById(id).value;
  return {
    estudo_id: valor('campo_estudo_id'), camada_id: valor('campo_camada_id'), nome: valor('campo_nome'), tema: valor('campo_tema'),
    origem: valor('campo_origem'), coluna_no: valor('campo_coluna_no'),
    ocultos: [...documento.querySelectorAll('input[name="ocultos"]:checked')].map((caixa) => caixa.value),
    sistema_confirmado: documento.getElementById('campo_sistema_confirmado').checked,
  };
}

// Some com os dois avisos da publicação: o de erro e o de sucesso de uma tentativa anterior.
function esconderAvisosDePublicacao(documento) {
  for (const id of ['publicacao-erro', 'publicacao-sucesso']) documento.getElementById(id).hidden = true;
}

// Mostra o resultado de uma tentativa: 201 é a versão criada em análise; qualquer outro status é o erro dela.
function resultadoDaPublicacao(documento, status, corpo) {
  esconderAvisosDePublicacao(documento);
  if (status === 201) return mostrarAviso(documento, 'publicacao-sucesso', `Versão ${corpo.versao} criada em análise.`);
  return mostrarAviso(documento, 'publicacao-erro', mensagemDoErro(status, corpo));
}

// Feições em empate sem escolha: a publicação não sai (R7). Conta só o que falta; o servidor recusa o mesmo caso.
function pendenciasDeEscolha(documento) {
  return [...documento.querySelectorAll('#revisao-nos select[data-empate="true"]')].filter((seletor) => seletor.value === '').length;
}

// Texto que bloqueia a publicação no cliente (antes da API), ou null. O servidor recusa o mesmo caso (R7).
function avisoDeBloqueio(documento) {
  return pendenciasDeEscolha(documento) > 0 ? 'Escolha o nó das feições em empate antes de publicar.' : null;
}

// Um item da revisão: o rótulo aponta ao select pelo `for`/`id`, para o leitor de tela anunciar o nome do campo.
function montarItemDeRevisao(documento, item, nosDaFazenda) {
  const campo = documento.createElement('div');  // o mesmo molde dos outros campos da tela (componentes/campo.html)
  campo.className = 'campo';
  const seletor = documento.createElement('select');
  seletor.className = 'campo-controle';
  seletor.id = `revisao_no_${item.indice}`;
  seletor.dataset.indice = String(item.indice);
  const empate = item.motivo === 'empate';
  seletor.dataset.empate = String(empate);
  if (empate) { // sem sugestão: a pessoa escolhe; "Escolha o nó" fica pré-selecionado e não pode ser escolhido de novo
    const escolha = documento.createElement('option');
    escolha.value = '';
    escolha.textContent = ROTULO_ESCOLHA_NO;
    escolha.disabled = true;
    seletor.append(escolha);
  }
  for (const opcao of opcoesDeNo(nosDaFazenda)) {
    const elemento = documento.createElement('option');
    elemento.value = opcao.valor;
    elemento.textContent = opcao.rotulo;
    seletor.append(elemento);
  }
  seletor.value = empate || item.sugerido === null ? '' : String(item.sugerido);
  const rotulo = criarNo(documento, 'label', rotuloDaRevisao(item));
  rotulo.className = 'campo-rotulo';
  rotulo.htmlFor = seletor.id;
  campo.append(rotulo, seletor);
  return campo;
}

// Lista de revisão: um select por feição, com a sugestão como valor inicial. Acima do limite, só o aviso.
function montarRevisao(documento, previa) {
  const lista = documento.getElementById('revisao-nos');
  if (!previa.revisao || previa.revisao.length === 0) return;
  documento.getElementById('revisao-bloco').hidden = false;
  if (previa.revisao.length > LIMITE_DE_ITENS_DE_REVISAO) {
    const aviso = documento.getElementById('revisao-aviso');
    aviso.textContent = `Há ${previa.revisao.length} feições para revisar: acima de ${LIMITE_DE_ITENS_DE_REVISAO}, use a divisão por coluna.`;
    aviso.hidden = false;
    return;
  }
  lista.replaceChildren(...previa.revisao.map((item) => montarItemDeRevisao(documento, item, previa.nos_da_fazenda || [])));
}

// Escolhas da pessoa: `{indice: no ou null}`. Só as feições da revisão entram; o resto vai pela sugestão da prévia.
function lerEscolhasDeNo(documento) {
  return Object.fromEntries([...documento.querySelectorAll('#revisao-nos select')].map((seletor) => [
    Number(seletor.dataset.indice), seletor.value === '' ? null : Number(seletor.value),
  ]));
}

async function iniciarConfirmacao(documento, secao) {
  const { previa, erro } = await carregarPrevia(documento, secao, 'publicacao-carregando');
  if (erro) return mostrarAviso(documento, 'publicacao-erro', erro);
  marcarOcultos(documento, previa.colunas);
  preencherDivisao(documento, previa.colunas);
  montarRevisao(documento, previa);
  const formulario = documento.getElementById('formulario-publicacao');
  formulario.hidden = false;
  const botao = documento.getElementById('publicar');
  formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    esconderAvisosDePublicacao(documento); // aviso de uma tentativa anterior não fica na tela
    const bloqueio = avisoDeBloqueio(documento);
    if (bloqueio) return mostrarAviso(documento, 'publicacao-erro', bloqueio);
    botao.disabled = true;
    botao.textContent = 'Publicando…';
    try {
      const { status, corpo } = await buscarJson(secao.dataset.apiPublicar, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': tokenCsrf(formulario) },
        body: JSON.stringify(montarPublicacao({ ...lerCampos(documento), escolhas: lerEscolhasDeNo(documento) }, previa)),
      });
      resultadoDaPublicacao(documento, status, corpo);
      if (status === 201) formulario.hidden = true;
    } catch {
      mostrarAviso(documento, 'publicacao-erro', 'Sem conexão com o servidor. A publicação pode não ter sido feita; confira antes de tentar de novo.');
    }
    botao.disabled = false;
    botao.textContent = 'Publicar em análise';
  });
}

// Falha que escapa do fluxo (DOM fora do molde, resposta de forma inesperada) vira aviso na tela, nunca promise sem tratamento.
function tratarFalha(promessa, documento, idAviso) {
  return promessa.catch(() => mostrarAviso(documento, idAviso, 'Não foi possível concluir. Tente de novo.'));
}

function iniciar(documento) {
  const secao = documento.querySelector('[data-camadas]');
  if (!secao) return;
  if (secao.dataset.camadas === 'envio') iniciarEnvio(documento, secao);
  if (secao.dataset.camadas === 'previa') tratarFalha(iniciarPrevia(documento, secao), documento, 'previa-erro');
  if (secao.dataset.camadas === 'confirmacao') tratarFalha(iniciarConfirmacao(documento, secao), documento, 'publicacao-erro');
}

if (typeof document !== 'undefined') iniciar(document);
if (typeof module !== 'undefined') {
  module.exports = { mensagemDoErro, urlDoEnvio, montarPublicacao, linhasDoResumo, contarNos, textoDosNos, criarNo, tratarFalha, resultadoDaPublicacao, esconderAvisosDePublicacao, montarItemDeRevisao, montarNos, opcoesDeNo, rotuloDaRevisao, pendenciasDeEscolha, avisoDeBloqueio, LIMITE_DE_ITENS_DE_REVISAO };
}
