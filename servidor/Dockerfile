# Imagens fixadas por versão e digest do índice multi-arquitetura (amd64 e arm64), conferidos no Docker Hub em 2026-10-23.
# python:3.12-slim = Python 3.12.15
FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS construcao
WORKDIR /construcao
COPY requirements.lock.txt .
# shortcut: o lockfile traz também as dependências de desenvolvimento; separar quando o tamanho da imagem importar.
RUN python -m venv /venv && /venv/bin/pip install --no-cache-dir --only-binary=:all: -r requirements.lock.txt
# Geração do pacote offline (004b): `rio pmtiles` com hashes (requirements.pacote.txt) e o CLI `pmtiles` v1.31.2 do release
# oficial, conferido pelo SHA-256 de cada arquitetura (digest da API do release, 2026-11-05). Sem isto `gerar_pacote_fazenda`
# não roda dentro do contêiner (CodeRabbit, PR #50).
COPY requirements.pacote.txt .
RUN /venv/bin/pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements.pacote.txt
ARG TARGETARCH
RUN set -eu;     case "$TARGETARCH" in       amd64) arq=x86_64; soma=3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f ;;       arm64) arq=arm64; soma=f8bd47e7ea866863489cad588fbaf2f31f42e5821f7a03f009b3769f05801cb1 ;;       *) echo "arquitetura sem hash do pmtiles: $TARGETARCH" >&2; exit 1 ;;     esac;     python -c "import sys,urllib.request as u;u.urlretrieve(sys.argv[1],sys.argv[2])"       "https://github.com/protomaps/go-pmtiles/releases/download/v1.31.2/go-pmtiles_1.31.2_Linux_${arq}.tar.gz" /tmp/pmtiles.tar.gz;     echo "${soma}  /tmp/pmtiles.tar.gz" | sha256sum -c -;     tar -xzf /tmp/pmtiles.tar.gz -C /usr/local/bin pmtiles

FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# `libexpat1`: o `rio` (rasterio, wheel com GDAL embutido) não importa sem ela na imagem slim; medido com `ldd`, é a única que falta.
# Aprovada pelo mantenedor em 2026-11-06 (pacote Debian da própria base, sem fixar versão).
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 --no-create-home aplicacao
COPY --from=construcao /venv /venv
COPY --from=construcao /usr/local/bin/pmtiles /usr/local/bin/pmtiles
# Diretório dos pacotes (PHATI_PACOTES_DIR, padrão /pacotes): o volume nomeado herda dono e modo da imagem na primeira montagem;
# sem isto nasceria de root e o `aplicacao` não conseguiria gravar a versão gerada.
RUN mkdir /pacotes && chown aplicacao /pacotes
WORKDIR /aplicacao
COPY --chown=aplicacao . .
USER aplicacao
EXPOSE 8000
# Sonda `/saude` (006 R10): 200 só com o banco alcançável. O Host é o primeiro de PHATI_HOSTS_PERMITIDOS, senão o
# `ALLOWED_HOSTS` recusa a chamada (400) quando a lista não inclui `127.0.0.1`, como na implantação.
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import os,urllib.request as u;h=(os.environ.get('PHATI_HOSTS_PERMITIDOS') or 'localhost').split(',')[0];u.urlopen(u.Request('http://127.0.0.1:8000/saude',headers={'Host':h}),timeout=2)"
CMD ["gunicorn", "projeto.wsgi", "--bind", "0.0.0.0:8000"]
