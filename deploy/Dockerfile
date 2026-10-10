# Both stages use the same ABI; the SQLite runtime is explicitly pinned and checked.
FROM python:3.14.8-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83 AS sqlite-build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://sqlite.org/2026/sqlite-autoconf-3510300.tar.gz', 'sqlite.tar.gz')" \
    && echo '81f5be397049b0cae1b167f2225af7646fc0f82e4a9b3c48c9ea3a533e21d77a  sqlite.tar.gz' | sha256sum -c - \
    && tar -xzf sqlite.tar.gz \
    && cd sqlite-autoconf-3510300 \
    && ./configure --prefix=/opt/sqlite --disable-readline \
    && make -j2 && make install

FROM python:3.14.8-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83
COPY --from=sqlite-build /opt/sqlite/lib/ /opt/sqlite/lib/
ENV LD_LIBRARY_PATH=/opt/sqlite/lib PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    WENLI_DATA_DIR=/data WENLI_REQUIRE_SAFE_SQLITE=true \
    CONFIG_PATH=/run/secrets/config.yml STAGE=prod
WORKDIR /app
COPY deploy/requirements.lock /app/deploy/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes -r deploy/requirements.lock \
    && python -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3,51,3), sqlite3.sqlite_version" \
    && groupadd --gid 10001 wenli && useradd --uid 10001 --gid wenli --no-create-home wenli \
    && mkdir /data && chown wenli:wenli /data
COPY deep_research/ /app/deep_research/
COPY server/ /app/server/
COPY deploy/backup.py /app/deploy/backup.py
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
