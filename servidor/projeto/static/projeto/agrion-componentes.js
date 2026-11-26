// Comportamento dos componentes AgriOn que precisam de JS (spec 012, R37): fechar aviso, arrastar e soltar na zona de envio e diálogo nativo.
// Sem este script: o botão Fechar aviso segue escondido, arrastar e soltar não funciona e o link de diálogo vai para a página de formulário.
// A zona de envio é um <label> ligado ao input de arquivo: clique e teclado são do navegador, sem código aqui.
function fecharAviso(botao) {
  const aviso = botao.closest('.ag-aviso');
  if (aviso) aviso.hidden = true;
  return aviso !== null;
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
  return false;
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
  module.exports = { fecharAviso, aoClicar, aoArrastar, aoSoltar, iniciar };
} else {
  iniciar(document);
}
