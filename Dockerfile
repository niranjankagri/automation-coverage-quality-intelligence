# The hosted dashboard (docs/deployment.md): the package without development tools, the
# sample catalog and gate, and a start script that fetches the published history.
# Base image pinned by version and digest (docs/ci.md, "Pinned for predictable runs").
FROM python:3.13.14-slim-trixie@sha256:9662417aace5ae7b8e2609cce472b72a8958e134ba372808abe9cc1a0c0125e6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .

COPY samples/catalog.toml samples/requirements.toml ./samples/
COPY samples/gates ./samples/gates
COPY deploy/start.sh ./start.sh

# Not root: the process can write only its data folder
RUN useradd --system --uid 10001 --home-dir /app qi \
    && mkdir /data && chown qi /data && chmod 0755 /app/start.sh
USER qi

# Public demonstration of public data (docs/operations.md); behind the platform's TLS proxy
ENV QI_DASHBOARD_PUBLIC=true \
    QI_FORWARDED_ALLOW_IPS=* \
    QI_ACCESS_LOG=json \
    QI_REFRESH_SECONDS=60

EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=4)"
CMD ["/app/start.sh"]
