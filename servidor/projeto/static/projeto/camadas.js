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
function montarPublicacao(campos, previa) {
  return {
    estudo_id: Number(campos.estudo_id),
    metadados: { nome: campos.nome, tema: campos.tema, origem: campos.origem },
    camada_id: campos.camada_id || null,
    ocultos: campos.ocultos,
    coluna_no: campos.coluna_no || null,
    nos: campos.coluna_no ? [] : previa.nos_sugeridos || [],
    sistema_confirmado: Boolean(campos.sistema_confirmado),
  };
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
  return `${comNo} feições com nó sugerido e ${semNo} sem nó: a publicação só passa com divisão por coluna ou com nó para cada uma.`;
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

async function iniciarConfirmacao(documento, secao) {
  const { previa, erro } = await carregarPrevia(documento, secao, 'publicacao-carregando');
  if (erro) return mostrarAviso(documento, 'publicacao-erro', erro);
  marcarOcultos(documento, previa.colunas);
  preencherDivisao(documento, previa.colunas);
  const formulario = documento.getElementById('formulario-publicacao');
  formulario.hidden = false;
  const botao = documento.getElementById('publicar');
  formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    botao.disabled = true;
    botao.textContent = 'Publicando…';
    try {
      const { status, corpo } = await buscarJson(secao.dataset.apiPublicar, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': tokenCsrf(formulario) },
        body: JSON.stringify(montarPublicacao(lerCampos(documento), previa)),
      });
      if (status === 201) {
        mostrarAviso(documento, 'publicacao-sucesso', `Versão ${corpo.versao} criada em análise.`);
        formulario.hidden = true;
        return;
      }
      mostrarAviso(documento, 'publicacao-erro', mensagemDoErro(status, corpo));
    } catch {
      mostrarAviso(documento, 'publicacao-erro', 'Sem conexão com o servidor. A publicação pode não ter sido feita; confira antes de tentar de novo.');
    }
    botao.disabled = false;
    botao.textContent = 'Publicar em análise';
  });
}

function iniciar(documento) {
  const secao = documento.querySelector('[data-camadas]');
  if (!secao) return;
  if (secao.dataset.camadas === 'envio') iniciarEnvio(documento, secao);
  if (secao.dataset.camadas === 'previa') iniciarPrevia(documento, secao);
  if (secao.dataset.camadas === 'confirmacao') iniciarConfirmacao(documento, secao);
}

if (typeof document !== 'undefined') iniciar(document);
if (typeof module !== 'undefined') {
  module.exports = { mensagemDoErro, urlDoEnvio, montarPublicacao, linhasDoResumo, contarNos, textoDosNos, criarNo };
}
