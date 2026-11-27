// Tela de entrada (spec 012, R18): com JS, campo vazio mostra o aviso sem enviar, e o envio ganha o giro no botão.
// Sem JS a entrada segue igual: os campos `required` barram o vazio no navegador e o servidor responde ao resto.
const MENSAGEM_VAZIO = 'Informe CPF e senha para entrar.';

function ocupar(botao) {
  botao.disabled = true;
  botao.setAttribute('aria-busy', 'true');
  const giro = botao.ownerDocument.createElement('span');
  giro.className = 'ag-giro';
  giro.setAttribute('aria-hidden', 'true');
  botao.prepend(giro);
}

function liberar(botao) {
  botao.disabled = false;
  botao.removeAttribute('aria-busy');
  botao.querySelector('.ag-giro')?.remove();
}

// Devolve true quando o envio segue; false quando o aviso bloqueia o envio.
function aoEnviar(evento, { cpf, senha, aviso, botao }) {
  if (cpf.value.trim() !== '' && senha.value !== '') {
    ocupar(botao);
    return true;
  }
  evento.preventDefault();
  aviso.querySelector('.ag-aviso-texto').textContent = MENSAGEM_VAZIO;
  aviso.hidden = false;
  return false;
}

function iniciar(documento) {
  const elementos = {
    formulario: documento.getElementById('entrar'),
    cpf: documento.getElementById('cpf'),
    senha: documento.getElementById('senha'),
    aviso: documento.getElementById('aviso-campos'),
    botao: documento.getElementById('entrar-enviar'),
  };
  // O navegador não pode barrar o vazio antes do script: a mensagem da AgriOn é que vale.
  elementos.formulario.noValidate = true;
  elementos.formulario.addEventListener('submit', (evento) => aoEnviar(evento, elementos));
  // Voltar pelo histórico restaura a página com o botão ocupado: libera de novo.
  documento.defaultView.addEventListener('pageshow', (evento) => {
    if (evento.persisted) liberar(elementos.botao);
  });
}

if (typeof module !== 'undefined') {
  module.exports = { aoEnviar, ocupar, liberar, iniciar, MENSAGEM_VAZIO };
} else {
  iniciar(document);
}
