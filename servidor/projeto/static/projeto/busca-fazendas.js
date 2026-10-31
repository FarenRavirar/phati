// Busca do seletor de fazenda (R10): filtra no cliente as fazendas que o servidor já autorizou; nada de fora do escopo
// chega à página. Sem este script a lista inteira continua visível.
(function () {
  const raiz = document.querySelector('[data-busca-fazendas]');
  if (!raiz) return;
  const campo = raiz.querySelector('[data-busca-campo]');
  const vazio = raiz.querySelector('[data-busca-vazia]');
  const grupos = Array.from(raiz.querySelectorAll('[data-grupo]'));

  function normalizar(texto) {
    return texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  }

  function filtrar() {
    const termo = normalizar(campo.value.trim());
    let visiveis = 0;
    for (const grupo of grupos) {
      let noGrupo = 0;
      for (const item of grupo.querySelectorAll('[data-fazenda]')) {
        const casa = normalizar(item.textContent).includes(termo);
        item.hidden = !casa;
        if (casa) noGrupo += 1;
      }
      grupo.hidden = noGrupo === 0;
      visiveis += noGrupo;
    }
    vazio.hidden = visiveis > 0;
  }

  campo.addEventListener('input', filtrar);
})();
