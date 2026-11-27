// Comportamento dos componentes AgriOn que precisam de JS (spec 012, R37): fechar aviso, arrastar e soltar na zona de envio, diálogo nativo e linha de tabela clicável.
// Sem este script: o botão Fechar aviso segue escondido, arrastar e soltar não funciona, o link de diálogo vai para a página de formulário e a linha só vale pelo link da primeira célula.
// A zona de envio é um <label> ligado ao input de arquivo: clique e teclado são do navegador, sem código aqui.
function fecharAviso(botao) {
  const aviso = botao.closest('.ag-aviso');
  if (aviso) aviso.hidden = true;
  return aviso !== null;
}

// Controles e rótulos cuidam do próprio clique; o resto da linha é do link da primeira célula.
const INTERATIVOS = ['a', 'button', 'input', 'label', 'summary', 'select', 'textarea'];

// Linha clicável (R37, telas.md §3): clique no corpo da linha vai ao link da primeira célula. Ctrl, meta e shift abrem em
// nova aba, como o link; botão não primário e texto selecionado seguem o navegador.
function aoClicarLinha(documento, evento) {
  if (evento.button) return false;
  const alvo = evento.target;
  if (INTERATIVOS.some((tag) => alvo.closest(tag))) return false;
  const linha = alvo.closest('[data-clicavel]');
  if (!linha || documento.getSelection?.()?.toString()) return false;
  const link = linha.querySelector('td:first-child a');
  if (!link) return false;
  if (evento.ctrlKey || evento.metaKey || evento.shiftKey) documento.defaultView.open(link.href, '_blank', 'noopener');
  else link.click();
  return true;
}

function aoClicar(documento, evento) {
  const alvo = evento.target;
  const botaoFechar = alvo.closest('.ag-aviso-fechar');
  if (botaoFechar) return fecharAviso(botaoFechar);
  const abrir = alvo.closest('[data-dialogo-abrir]');
  if (abrir) {
    const dialogo = documento.getElementById(abrir.dataset.dialogoAbrir);
    if (typeof dialogo?.showModal === 'function') {
      evento.preventDefault();
      dialogo.showModal();
      return true;
    }
    return false;
  }
  const fecharDialogo = alvo.closest('[data-dialogo-fechar]');
  if (fecharDialogo) {
    fecharDialogo.closest('dialog').close();
    return true;
  }
  // Clique no fundo: o alvo é o próprio <dialog>, já que o conteúdo ocupa a caixa.
  if (alvo.localName === 'dialog') {
    alvo.close();
    return true;
  }
  return aoClicarLinha(documento, evento);
}

function aoArrastar(evento, entrando) {
  const zona = evento.target.closest('.ag-envio');
  if (!zona) return false;
  evento.preventDefault();
  if (entrando) zona.dataset.arrastando = '';
  else delete zona.dataset.arrastando;
  return true;
}

function aoSoltar(evento) {
  const zona = evento.target.closest('.ag-envio');
  if (!zona) return false;
  evento.preventDefault();
  delete zona.dataset.arrastando;
  const entrada = zona.querySelector('input[type="file"]');
  const arquivos = evento.dataTransfer?.files;
  if (!entrada || !arquivos?.length) return false;
  entrada.files = arquivos;
  // Avisa o formulário ou o script do consumidor, como uma escolha pelo seletor de arquivo.
  entrada.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
}

function iniciar(documento) {
  documento.addEventListener('click', (evento) => aoClicar(documento, evento));
  documento.addEventListener('dragover', (evento) => aoArrastar(evento, true));
  documento.addEventListener('dragleave', (evento) => aoArrastar(evento, false));
  documento.addEventListener('drop', aoSoltar);
  // O botão Fechar aviso nasce `hidden` no HTML: sem este script ele não aparece.
  for (const botao of documento.querySelectorAll('.ag-aviso-fechar')) botao.hidden = false;
}

if (typeof module !== 'undefined') {
  module.exports = { fecharAviso, aoClicar, aoClicarLinha, aoArrastar, aoSoltar, iniciar };
} else {
  iniciar(document);
}
