# Contrato de encaixe do mapa (versão 1)

Regiões da página da fazenda (003 R22): **mapa**, **camadas**, **consulta de feição** e **ficha técnica**. A 004 e a spec de
camadas montam o conteúdo dentro delas e entregam, para cada feição consultada, um registro com os campos abaixo. O código
que lê o registro é `ficha.py`; `testes/test_ficha.py` falha se esta lista e o código divergirem.

| Campo | Tipo | Quando falta |
|---|---|---|
| `camada` | texto: nome da camada | "Sem informação" |
| `atributo` | texto: nome do atributo | "Sem informação" |
| `valor` | número ou texto | "Sem informação"; `0` é um valor medido e se mostra como `0` |
| `unidade` | texto | o valor aparece com "(sem informação de unidade)" |
| `fonte` | texto: quem produziu o dado | "Sem informação" |
| `data` | data do dado | "Sem informação" |
| `situacao` | `vigente`, `em análise`, `substituída` ou `arquivada` | não falta: fora da lista é erro |
| `ressalva` | texto livre | "Sem informação" |
| `origem` | `medicao` ou `estimativa` | não falta: fora da lista é erro |

Regras:

- Todo campo existe no registro; sem dado, o valor é `None`. Campo ausente do registro é erro, não "sem informação".
- Valor derivado (interpolação, sensoriamento) vem com `origem: estimativa` e nunca aparece como medição.
- Ficha e ressalva são texto visível, nunca tooltip.
- A cor de cada camada vive em `static/projeto/camadas.css`, nunca em `tokens.css`. Paleta e simbologia vêm da Tatiane; até lá a cor é provisória.
- Estados de cada região: vazio, carregando, erro, sem permissão e sem informação (`componentes/regiao.html`).
