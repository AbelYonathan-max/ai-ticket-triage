# syntax=docker/dockerfile:1.7
# Multi-stage build: the "train" stage builds the model from the data in this repository (fixed
# seeds, so the result is reproducible); the runtime stage is a small non-root image with only the
# app, the trained model and the Microsoft ODBC driver for Azure SQL.

ARG PYTHON_IMAGE=python:3.13-slim-bookworm

FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ---------------------------------------------------------------- train
FROM base AS train
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[train]"
COPY data/test ./data/test
RUN python -m triage.data.synthetic --out data/synthetic/train.csv \
 && python -m triage.ml.train --out /build/models --docs /build/docs

# ---------------------------------------------------------------- runtime
FROM base AS runtime
ARG MSODBC_VERSION=18
# The driver links libgssapi_krb5.so.2, but its package does not list libgssapi-krb5-2, so it is
# named here. Otherwise it arrives only with curl, and removing curl afterwards takes it away. The
# last lines fail the build if the registered driver file, or any library it needs, is missing.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg unixodbc \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
 && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
      > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql${MSODBC_VERSION} libgssapi-krb5-2 \
 && apt-get purge -y curl gnupg \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* \
 && driver="$(odbcinst -q -d -n "ODBC Driver ${MSODBC_VERSION} for SQL Server" | sed -n 's/^Driver=//p')" \
 && test -f "$driver" \
 && if ldd "$driver" | grep "not found"; then exit 1; fi

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . && rm -rf src build
COPY --from=train /build/models ./models
COPY data/test/handwritten.jsonl ./data/test/handwritten.jsonl

USER 10001
ENV TRIAGE_MODEL_DIR=/app/models \
    PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"
CMD ["sh", "-c", "exec uvicorn --factory triage.api.app:create_app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips '*' --no-server-header"]
