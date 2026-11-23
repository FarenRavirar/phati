-- Cria os papéis e o banco. Rodar como superusuário, com nomes e senhas no ambiente
-- (as mesmas variáveis que o Django lê):
--   PHATI_BANCO_NOME=phati PHATI_BANCO_DONO_USUARIO=dono PHATI_BANCO_DONO_SENHA=... \
--   PHATI_BANCO_APP_USUARIO=app PHATI_BANCO_APP_SENHA=... PHATI_BANCO_REPLICADOR_SENHA=... \
--     psql -h <host> -p <porta> -U <superusuario> -d postgres -f banco/papeis.sql
-- O papel dono roda migrações e é dono das tabelas; o papel app é o da aplicação: sem BYPASSRLS, sem posse.
-- Idempotente: cada papel e o banco só são criados se faltarem, então rodar de novo num banco que já existe rc=0.
-- `format(... %I / %L)` escapa identificador e literal; \gexec executa o comando montado.
\getenv nome_banco PHATI_BANCO_NOME
\getenv usuario_dono PHATI_BANCO_DONO_USUARIO
\getenv senha_dono PHATI_BANCO_DONO_SENHA
\getenv usuario_app PHATI_BANCO_APP_USUARIO
\getenv senha_app PHATI_BANCO_APP_SENHA
\set tem_senha_replicador false
\getenv senha_replicador PHATI_BANCO_REPLICADOR_SENHA
-- Senha vazia (ou variável ausente) não cria o papel e não falha o init: o `banco` do compose sobe sem ela (só o
-- `preparar` da troca exige). Com a senha, o comportamento é o idempotente de sempre.
\if :{?senha_replicador}
SELECT (:'senha_replicador' <> '') AS tem_senha_replicador \gset
\endif
SELECT format('CREATE ROLE %I LOGIN CREATEDB NOSUPERUSER NOBYPASSRLS PASSWORD %L', :'usuario_dono', :'senha_dono')
  WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'usuario_dono') \gexec
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %L', :'usuario_app', :'senha_app')
  WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'usuario_app') \gexec
-- Replicação lógica (spec 009 R15, decisão 10): papel só para a assinatura da troca de banco. REPLICATION permite o
-- fluxo de replicação; sem ele o assinante não conecta. BYPASSRLS: a cópia inicial e o fluxo lógico leem todas as linhas;
-- sem ele, as políticas de RLS (escopo, leitura_por_fazenda, propria) filtram o que vai ao destino, sem erro. Só o modo
-- lógico precisa disso. O papel é restrito por `pg_hba` à sub-rede interna e por senha forte. Senha só do ambiente, nunca
-- literal neste arquivo. O nome é fixo (`replicador`, no \set abaixo): o nome não é segredo, a senha é.
\set usuario_replicador replicador
\if :tem_senha_replicador
SELECT format('CREATE ROLE %I LOGIN REPLICATION BYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'usuario_replicador', :'senha_replicador')
  WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'usuario_replicador') \gexec
-- Banco que já tem o papel (criado antes deste atributo): o ALTER põe o BYPASSRLS sem trocar a senha.
SELECT format('ALTER ROLE %I LOGIN REPLICATION BYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE', :'usuario_replicador') \gexec
\endif
SELECT format('CREATE DATABASE %I OWNER %I', :'nome_banco', :'usuario_dono')
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'nome_banco') \gexec
-- Concessões do replicador são por banco: precisam de conexão ao `phati` (default ACL é por banco). `\connect` aceita
-- variável (medido em 2026-11-23, PostgreSQL 18 no contêiner descartável). `ALTER DEFAULT PRIVILEGES FOR ROLE dono` cobre
-- tabelas que as migrações do dono criarem depois; o GRANT cobre as tabelas que já existem (banco homologação).
\connect :"nome_banco"
\if :tem_senha_replicador
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"usuario_replicador";
ALTER DEFAULT PRIVILEGES FOR ROLE :"usuario_dono" IN SCHEMA public GRANT SELECT ON TABLES TO :"usuario_replicador";
\else
\echo 'papel de replicação não criado: PHATI_BANCO_REPLICADOR_SENHA vazia'
\endif

-- pg_hba: o repositório não gerencia `pg_hba.conf`. A imagem gera o padrão no initdb (sem linha de replicação).
-- A troca de banco (R15) precisa, no `banco` que publica, destas duas linhas (sub-rede interna da implantação:
-- 172.29.250.0/24, compose.implantacao.yaml; a aplicar fora do repositório, a conferir na VM):
--   host replication replicador <sub-rede-interna> scram-sha-256
--   host <banco> replicador <sub-rede-interna> scram-sha-256
