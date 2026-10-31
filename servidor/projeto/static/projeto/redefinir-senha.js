// O segredo vem no fragmento (`#segredo=`): não chega ao servidor nem aos logs. Sai da barra de endereço e do histórico
// antes de qualquer coisa, e só vai adiante no corpo do POST (T5.5g, R5).
const segredo = new URLSearchParams(location.hash.slice(1)).get('segredo');
history.replaceState(null, '', location.pathname);
const mensagem = document.getElementById('mensagem');
const formulario = document.getElementById('formulario');
const TEXTOS = {
  link_invalido: 'Este link não vale mais. Peça um novo link de redefinição.',
  senha_curta: 'A senha é curta demais.',
  senha_longa: 'A senha é longa demais.',
  senha_comum: 'Essa senha é comum demais. Escolha outra.',
  senha_contexto: 'A senha não pode conter seu nome, e-mail ou CPF.',
};
// Sucesso usa a variante verde e `status`; erro, a vermelha e `alert` (o par de classes é o de `componentes/aviso.html`).
function avisar(texto, sucesso = false) {
  mensagem.className = sucesso ? 'aviso aviso-sucesso' : 'aviso aviso-erro';
  mensagem.setAttribute('role', sucesso ? 'status' : 'alert');
  mensagem.textContent = texto;
  mensagem.hidden = false;
}
if (!segredo) {
  avisar(TEXTOS.link_invalido);
} else {
  formulario.hidden = false;
  const botao = document.getElementById('salvar');
  let enviando = false;
  formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    // Um segredo vale uma vez: dois envios seguidos fariam o segundo trocar o aviso de sucesso por "link inválido".
    if (enviando) return;
    const senhaNova = document.getElementById('senha_nova').value;
    if (senhaNova !== document.getElementById('repeticao').value) { avisar('As senhas não são iguais.'); return; }
    enviando = true;
    botao.disabled = true;
    let definitivo = false;
    try {
      const resposta = await fetch('/api/v1/redefinir-senha/confirmar', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ segredo, senha_nova: senhaNova }),
      });
      if (resposta.status === 204) {
        definitivo = true;
        formulario.hidden = true;
        avisar('Senha alterada. Entre no aplicativo com a senha nova.', true);
        return;
      }
      const corpo = await resposta.json().catch(() => ({}));
      avisar(TEXTOS[corpo.detalhe] || 'Não foi possível salvar a senha. Tente de novo.');
      if (corpo.detalhe === 'link_invalido') { definitivo = true; formulario.hidden = true; }
    } catch {
      avisar('Sem conexão com o servidor. A senha pode não ter sido alterada; tente de novo.');
    } finally {
      if (!definitivo) { enviando = false; botao.disabled = false; }
    }
  });
}
