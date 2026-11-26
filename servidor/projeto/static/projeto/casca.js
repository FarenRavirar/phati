// Casca autenticada (spec 012, R15 e R17): gaveta abaixo de 64rem, seletor de escopo e Esc. Sem JS, o menu fica no <details>.
// Esc fecha o que estiver aberto e devolve o foco ao botão que abriu. A casca não tem script inline: tudo vem deste arquivo, com nonce.

function iniciarCasca(documento) {
  const casca = documento.querySelector('.ag-casca');
  if (!casca) return null;
  casca.dataset.js = '';

  const abrirMenu = casca.querySelector('[data-abrir-menu]');
  const fundo = casca.querySelector('[data-gaveta-fundo]');
  const sidebar = casca.querySelector('.ag-sidebar');
  const botaoEscopo = casca.querySelector('[data-escopo-abrir]');
  const listaEscopo = casca.querySelector('[data-escopo-lista]');
  for (const no of [abrirMenu, botaoEscopo]) if (no) no.hidden = false;
  const resumo = casca.querySelector('.ag-sidebar-resumo');
  if (resumo) resumo.hidden = true; // com JS, a gaveta substitui o resumo do <details>

  const gavetaAberta = () => 'gaveta' in casca.dataset;
  const fecharGaveta = (devolverFoco) => {
    delete casca.dataset.gaveta;
    if (abrirMenu) abrirMenu.setAttribute('aria-expanded', 'false');
    if (devolverFoco && abrirMenu) abrirMenu.focus();
  };
  const abrirGaveta = () => {
    casca.dataset.gaveta = '';
    if (abrirMenu) abrirMenu.setAttribute('aria-expanded', 'true');
    // O seletor de escopo também tem links, escondidos até abrir: o foco vai ao primeiro item do menu, que é visível.
    sidebar?.querySelector('.ag-nav-principal a')?.focus();
  };
  const escopoAberto = () => listaEscopo && !listaEscopo.hidden;
  const fecharEscopo = (devolverFoco) => {
    if (listaEscopo) listaEscopo.hidden = true;
    if (botaoEscopo) botaoEscopo.setAttribute('aria-expanded', 'false');
    if (devolverFoco && botaoEscopo) botaoEscopo.focus();
  };

  if (abrirMenu) abrirMenu.addEventListener('click', () => (gavetaAberta() ? fecharGaveta(true) : abrirGaveta()));
  if (fundo) fundo.addEventListener('click', () => fecharGaveta(true));
  // Escolher um item fecha a gaveta; o foco segue para a página nova, não para o botão.
  if (sidebar) sidebar.addEventListener('click', (evento) => {
    if (evento.target?.closest?.('a')) fecharGaveta(false);
  });
  if (botaoEscopo) botaoEscopo.addEventListener('click', () => {
    const abrir = !escopoAberto();
    listaEscopo.hidden = !abrir;
    botaoEscopo.setAttribute('aria-expanded', String(abrir));
  });
  documento.addEventListener('keydown', (evento) => {
    if (evento.key !== 'Escape') return;
    if (escopoAberto()) fecharEscopo(true);
    else if (gavetaAberta()) fecharGaveta(true);
  });
  return { fecharGaveta, fecharEscopo, gavetaAberta, escopoAberto };
}

if (typeof module !== 'undefined') module.exports = { iniciarCasca };
if (typeof document !== 'undefined') iniciarCasca(document);
