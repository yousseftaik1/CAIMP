FROM pgvector/pgvector:pg16 AS pgvector_src

# Collect only pgvector files into a staging directory
RUN mkdir -p /pgvector/lib /pgvector/ext \
    && cp /usr/lib/postgresql/16/lib/vector.so /pgvector/lib/ \
    && cp /usr/share/postgresql/16/extension/vector* /pgvector/ext/

FROM timescale/timescaledb:latest-pg16

# Copy pgvector files from the staging directory — no apt-get, no compilation
COPY --from=pgvector_src /pgvector/lib/ /usr/lib/postgresql/16/lib/
COPY --from=pgvector_src /pgvector/ext/ /usr/share/postgresql/16/extension/

RUN echo "shared_preload_libraries = 'timescaledb'" >> /usr/share/postgresql/postgresql.conf.sample
