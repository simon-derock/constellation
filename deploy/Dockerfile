# One container, two processes: FalkorDB (loopback only) and the API. Sized for a 512 MB free host.
FROM falkordb/falkordb:v4.22.1@sha256:b0bdcac2cbaff989e77cb0610439b7a9289e86de033ccbbd4368b66fb680ae7a

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin app \
 && mkdir -p /data && chown app /data

WORKDIR /app
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY third_party ./third_party
COPY results/published ./results/published
RUN uv sync --locked --no-dev && chmod -R a+rX /opt /app

COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

# the browser UI bundled in the base image is not wanted; the API is the only port exposed
ENV BROWSER=0 HOST=0.0.0.0 PORT=8000 FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=6379
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
