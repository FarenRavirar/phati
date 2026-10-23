-- Cria os papéis e o banco. Rodar uma vez, como superusuário, com nomes e senhas no ambiente
-- (as mesmas variáveis que o Django lê):
--   PHATI_BANCO_DONO_USUARIO=dono PHATI_BANCO_DONO_SENHA=... PHATI_BANCO_APP_USUARIO=app PHATI_BANCO_APP_SENHA=... \
--     psql -h <host> -p <porta> -U <superusuario> -d postgres -f banco/papeis.sql
-- O papel dono roda migrações e é dono das tabelas; o papel app é o da aplicação: sem BYPASSRLS, sem posse.
-- `format(... %I / %L)` escapa identificador e literal; \gexec executa o comando montado.
\getenv usuario_dono PHATI_BANCO_DONO_USUARIO
\getenv senha_dono PHATI_BANCO_DONO_SENHA
\getenv usuario_app PHATI_BANCO_APP_USUARIO
\getenv senha_app PHATI_BANCO_APP_SENHA
SELECT format('CREATE ROLE %I LOGIN CREATEDB NOSUPERUSER NOBYPASSRLS PASSWORD %L', :'usuario_dono', :'senha_dono') \gexec
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %L', :'usuario_app', :'senha_app') \gexec
SELECT format('CREATE DATABASE phati OWNER %I', :'usuario_dono') \gexec
