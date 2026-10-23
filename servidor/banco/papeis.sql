-- Cria os papéis e o banco. Rodar uma vez, como superusuário, com as senhas no ambiente:
--   PHATI_BANCO_DONO_SENHA=... PHATI_BANCO_APP_SENHA=... psql -h <host> -p <porta> -U <superusuario> -d postgres -f banco/papeis.sql
-- `dono` roda migrações e é dono das tabelas; `app` é o papel da aplicação: sem BYPASSRLS, sem posse.
-- `format(... %L)` escapa a senha como literal; \gexec executa o comando montado.
\getenv senha_dono PHATI_BANCO_DONO_SENHA
\getenv senha_app PHATI_BANCO_APP_SENHA
SELECT format('CREATE ROLE dono LOGIN CREATEDB NOSUPERUSER NOBYPASSRLS PASSWORD %L', :'senha_dono') \gexec
SELECT format('CREATE ROLE app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %L', :'senha_app') \gexec
CREATE DATABASE phati OWNER dono;
