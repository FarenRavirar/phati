# servidor

Django 6.1 sobre PostgreSQL 17. Python 3.12 ou mais. Versões fixadas em `requirements.lock.txt`.

## Primeiro uso do clone

Ativar os hooks de pré-commit (vazamento e par arquivo–teste), uma vez por clone: `git config core.hooksPath .githooks`.
O git não versiona essa configuração, então o hook só vale depois deste comando.

## Banco local

Subir o PostgreSQL 17 (binário portátil, porta 5433). No Windows, `pg_ctl start` pelo Git Bash trava o terminal;
usar PowerShell (`E001` em `.specify/memory/errors.md`):

    Start-Process -WindowStyle Hidden -FilePath <pgsql>in\pg_ctl.exe -ArgumentList @('-D','<dados>','-l','<log>','-o','"-p 5433"','start')

Depois, uma vez como superusuário, criar papéis e banco e migrar:

    PHATI_BANCO_DONO_USUARIO=dono PHATI_BANCO_DONO_SENHA=... PHATI_BANCO_APP_USUARIO=app PHATI_BANCO_APP_SENHA=... psql -h 127.0.0.1 -p 5433 -U postgres -d postgres -f banco/papeis.sql

O papel dono roda as migrações e é dono das tabelas; o papel app é o da aplicação: não é dono e não tem `BYPASSRLS`.
O processo web recebe só a credencial do `app`; a do dono fica em `migracao` e nos testes (sem `PHATI_BANCO_DONO_SENHA`, o `default` do Django é o próprio `app`).
Os nomes das variáveis de ambiente estão em `.env.exemplo`. Sem `PHATI_CHAVE_SECRETA` o servidor não sobe.

    python manage.py migrate

## Testes

    python -m pytest -q

A suíte cria o banco `test_phati` com o papel `dono`; os papéis precisam existir.

## Contêineres (Docker Compose)

    docker compose up -d --build

Sobe `banco` (`postgres:17`, sem porta publicada), roda `migracao` uma vez e sobe `app` (gunicorn em `127.0.0.1:8000`).
Além das variáveis de `.env.exemplo`, o compose exige `PHATI_BANCO_SUPER_SENHA` (senha do superusuário do contêiner `banco`,
usada só na criação do volume). `banco/inicializar-papeis.sh` cria `dono`, `app` e o banco na primeira subida.
