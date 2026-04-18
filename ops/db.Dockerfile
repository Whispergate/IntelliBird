# ops/db.Dockerfile
# Postgres 16 + TimescaleDB + Apache AGE co-installed.
# Deviation from CONTEXT D-04: uses non-HA timescaledb image because the
# HA variant's Patroni entrypoint is Kubernetes-oriented and incompatible
# with single-host Compose (see 01-RESEARCH.md §"Apache AGE + TimescaleDB
# coexistence"). Non-HA base is correct for our deployment.

# ---- Stage 1: build AGE from source against PG16 headers ----
FROM timescale/timescaledb:latest-pg16 AS age-builder

USER root

RUN apk add --no-cache \
      build-base \
      git \
      bison \
      flex \
      readline-dev \
      zlib-dev \
      clang19 \
      llvm19 \
      perl \
      postgresql16-dev \
      postgresql16-contrib

ARG AGE_VERSION=PG16/v1.5.0-rc0
WORKDIR /build
RUN git clone --depth 1 --branch ${AGE_VERSION} https://github.com/apache/age.git \
    && cd age \
    && make PG_CONFIG=$(which pg_config) \
    && make PG_CONFIG=$(which pg_config) install

# ---- Stage 2: runtime image ----
FROM timescale/timescaledb:latest-pg16

# Copy AGE extension files into the runtime image's extension dirs.
# timescale/timescaledb:latest-pg16 is Alpine-based; extension paths are
# /usr/local/lib/postgresql/ and /usr/local/share/postgresql/extension/.
COPY --from=age-builder /usr/local/lib/postgresql/age.so \
     /usr/local/lib/postgresql/age.so
COPY --from=age-builder /usr/local/share/postgresql/extension/age.control \
     /usr/local/share/postgresql/extension/age.control
COPY --from=age-builder /usr/local/share/postgresql/extension/age--*.sql \
     /usr/local/share/postgresql/extension/

# Ensure both extensions are in shared_preload_libraries. The base image
# already preloads timescaledb; append 'age'.
RUN echo "shared_preload_libraries = 'timescaledb,age'" \
    >> /usr/local/share/postgresql/postgresql.conf.sample

# Inherit the base image's entrypoint + CMD.
