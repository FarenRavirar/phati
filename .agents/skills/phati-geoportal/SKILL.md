---
name: phati-geoportal
description: Use quando projetar, implementar, revisar ou testar frontend web e Android, UX cartográfica, fichas territoriais, camadas, gestão de versões, aprovação e uso offline do Phati. Impõe dados sintéticos e impede mudanças não solicitadas de domínio.
---

# Phati GeoPortal: skill de contexto e revisão

## Autoridade e contexto
Antes de modificar interfaces, leia `DESIGN.md` e `DOSSIE_PHATI.md`, se disponíveis no projeto. Releia também rotas, modelos e regras reais; documentação de orientação não prevalece sobre código nem autoriza presumir funcionalidade já implementada.

## Restrições irrevogáveis de contexto
- Produto cartográfico multitenant com web administrativa e app Android nativo, sem iOS.
- Hierarquia Empresa > Fazenda/Imóvel > Tema/Estudo > Camada/Versão > Feições, atributos e documentos.
- Autorizações por escopo efetivo e perfil, com aprovação cartográfica restrita ao Administrador autorizado ou papel específico.
- Nunca atribuir ao operador técnico acesso a produção; homologação sempre com dados totalmente sintéticos.
- Nunca inserir nomes reais externos, CPF real, localizações proprietárias, prints, dados de produção, URLs privadas, credenciais e chaves no repositório público ou no contexto de ferramentas de design externas.
- Não criar regras de negócio, métricas, integrações ou coleta offline que não foram especificadas.
- Rasters analíticos e ortofotos apenas online. Pacote offline com mapa-base licenciado e camadas/fichas autorizadas.
- Usuário deve conseguir reconhecer fonte, data, ressalvas, versão e documentos pertinentes a uma feição.

## Protocolo em cada tarefa
1. Declare qual das duas experiências será alterada: web de gestão ou Android de consulta.
2. Inspecione o frontend existente. Preserve a stack, o design system e as APIs presentes, salvo pedido explícito.
3. Resuma as decisões conhecidas e as lacunas. Não converter lacunas em fatos.
4. Desenhe primeiro a estrutura da informação (tarefas, prioridades, camadas, estados), depois o estilo.
5. Produza uma mudança pequena e completa, com estados: carregamento, vazio, sem permissão, erro, sem rede e versão desatualizada quando pertinentes.
6. Valide UX de consulta de feição, especialmente múltiplos polígonos coincidentes e documentos locais/remotos.
7. Faça captura/teste com Playwright ou teste nativo equivalente se o projeto permitir.
8. Rode auditoria de acessibilidade, contraste, interação e performance.
9. Liste resultados observados, não alegue testar algo que não foi executado.
10. Antes de concluir, cheque vazamentos de informações no diff, fixtures, stories, capturas e logs.

## Direção visual
- Estética institucional sóbria, clara, sem estilo genérico de template SaaS.
- Mapa é foco da consulta; painel de camadas e ficha são contextuais e recolhíveis.
- Prefira tabelas, árvore de camadas, ficha de proveniência e linha do tempo administrativa a grade de KPIs decorativos.
- Tipografia legível, espaçamento controlado, bordas discretas, sem sombras/gradientes excessivos.
- Não esconder fontes e ressalvas em tooltip inacessível.
- Usar cores semânticas sempre acompanhadas por texto e ícone. Não confundir cor de mapa com aprovação.
- No Android, reconhecer gestos familiares de mapa, abrir detalhes em bottom sheet, adaptar tablet para dois painéis.

## Revisão por papel
- Usuário: encontra fazenda autorizada, consulta mapa e documento sem conhecimento GIS.
- Técnico: sabe onde está a informação, observa se ela é vigente ou revisão, e não aprova sem autorização.
- Curador: encontra inconsistências, estrutura fontes e encaminha revisão.
- Aprovador autorizado: compara versões e registra justificativa.
- Administrador: enxerga apenas o escopo aplicável, verifica concessões e auditoria.

## Saída esperada
Entregar o que foi implementado, arquivos alterados, testes executados e pendências. Não declarar 'pronto para produção' sem teste em dispositivos reais, segurança, autorização e revisão de UX.
