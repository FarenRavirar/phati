# servidor

Django 6.1 sobre PostgreSQL 18 (compose e CI). Python 3.12 ou mais. Versões fixadas em `requirements.lock.txt`.

## Primeiro uso do clone

Ativar os hooks de pré-commit (vazamento e par arquivo–teste), uma vez por clone: `git config core.hooksPath .githooks`.
O git não versiona essa configuração, então o hook só vale depois deste comando.

## Banco local

Subir o PostgreSQL 18 num contêiner (porta 5433, mesma imagem do compose). O volume vai em `/var/lib/postgresql`,
não em `/var/lib/postgresql/data`: o PG18 grava o cluster em `/var/lib/postgresql/18/docker` e recusa o layout antigo,
então um volume criado pelo PG17 não sobe na imagem 18 (dump/restore ou `pg_upgrade`).

Primeira vez (cria o contêiner e o volume):

    docker run -d --name phati-pg18-local -e POSTGRES_PASSWORD=<superusuario> -p 127.0.0.1:5433:5432 -v phati-pg18-local:/var/lib/postgresql postgres:18@sha256:3a4264520e121176619f54ff867d12774bc81e95e7b84db58d63bccdb6144b81

Nas sessões seguintes o nome já existe: `docker start phati-pg18-local`. Quem sobe, desliga ao terminar: `docker stop phati-pg18-local`.

Com o contêiner no ar, uma vez como superusuário, criar papéis e banco e migrar:

    PHATI_BANCO_NOME=phati PHATI_BANCO_DONO_USUARIO=dono PHATI_BANCO_DONO_SENHA=... PHATI_BANCO_APP_USUARIO=app PHATI_BANCO_APP_SENHA=... psql -h 127.0.0.1 -p 5433 -U postgres -d postgres -f banco/papeis.sql

O papel dono roda as migrações e é dono das tabelas; o papel app é o da aplicação: não é dono e não tem `BYPASSRLS`.
O processo web recebe só a credencial do `app`; a do dono fica em `migracao` e nos testes (sem `PHATI_BANCO_DONO_SENHA`, o `default` do Django é o próprio `app`).
Os nomes das variáveis de ambiente estão em `.env.exemplo`. Sem `PHATI_CHAVE_SECRETA`, `PHATI_CHAVE_CPF` ou `PHATI_SEGREDO_RLS` o servidor não sobe.
`PHATI_SEGREDO_RLS` (32 bytes em base64 urlsafe, gerado do mesmo modo) assina o contexto de RLS; a migração
`permissao/0004` grava uma cópia em `rls_segredo`, que o papel `app` não lê. Rotação em `permissao/contexto.py`. Ao atualizar uma instalação que já tem a versão anterior, parar o `app` antes da `migracao`: worker antigo não assina o contexto e o banco nega tudo até ele sair. `manage.py check --database default` acusa segredo diferente do gravado.
`PHATI_CHAVE_CPF` é a raiz da chave do CPF (32 bytes em base64 urlsafe); gerar com
`python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`. Perder a chave perde o acesso
aos CPFs cifrados e à busca por CPF; rotação em `identidade/cpf.py`. `PHATI_URL_BASE` (padrão `http://localhost:8000`)
monta o link de redefinição; `PHATI_EMAIL_*` configuram o SMTP (padrão `localhost:587`).

    python manage.py migrate

## Testes

    python -m pytest -q

A suíte cria o banco `test_phati` com o papel `dono`; os papéis precisam existir.

## Contêineres (Docker Compose)

    docker compose up -d --build

Sobe `banco` (`postgres:18`, sem porta publicada), roda `migracao` uma vez e sobe `app` (gunicorn em `127.0.0.1:8000`).
Além das variáveis de `.env.exemplo`, o compose exige `PHATI_BANCO_SUPER_SENHA` (senha do superusuário do contêiner `banco`,
usada só na criação do volume). `banco/inicializar-papeis.sh` cria `dono`, `app` e o banco na primeira subida.
