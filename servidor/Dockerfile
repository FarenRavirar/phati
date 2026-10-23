# Imagens fixadas por versão e digest do índice multi-arquitetura (amd64 e arm64), conferidos no Docker Hub em 2026-10-23.
# python:3.12-slim = Python 3.12.15
FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS construcao
WORKDIR /construcao
COPY requirements.lock.txt .
# shortcut: o lockfile traz também as dependências de desenvolvimento; separar quando o tamanho da imagem importar.
RUN python -m venv /venv && /venv/bin/pip install --no-cache-dir -r requirements.lock.txt

FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home aplicacao
COPY --from=construcao /venv /venv
WORKDIR /aplicacao
COPY --chown=aplicacao . .
USER aplicacao
EXPOSE 8000
# shortcut: só confere que a porta aceita conexão; trocar por rota HTTP de saúde quando a API existir (Fase 5).
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8000), 2)"
CMD ["gunicorn", "projeto.wsgi", "--bind", "0.0.0.0:8000"]
