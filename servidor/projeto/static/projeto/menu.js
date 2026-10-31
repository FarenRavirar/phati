// Menu recolhível em largura estreita (R17). Sem este script o menu fica sempre visível e o botão fica escondido.
(function () {
  const botao = document.getElementById('menu-alternar');
  const menu = document.getElementById('menu-lateral');
  if (!botao || !menu) return;
  const estreito = window.matchMedia('(max-width: 48rem)');
  let aberto = false;

  function aplicar() {
    botao.hidden = !estreito.matches;
    menu.hidden = estreito.matches && !aberto;
    botao.setAttribute('aria-expanded', String(!menu.hidden));
  }

  botao.addEventListener('click', () => { aberto = !aberto; aplicar(); });
  estreito.addEventListener('change', aplicar);
  aplicar();
})();
