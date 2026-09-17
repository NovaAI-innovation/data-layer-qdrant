# syntax=docker/dockerfile:1.7
# data-layer-qdrant — Qdrant RAG container.
# Wraps qdrant/qdrant and layers our config + entrypoint so the
# container applies migrations and (optionally) seeds on first boot.
FROM qdrant/qdrant:v1.19.1

# Use bash for the entrypoint (Qdrant's image is debian-based with bash available).
RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends bash curl ca-certificates python3 \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /qdrant/config /qdrant/migrations /qdrant/seeds /qdrant/storage /qdrant/snapshots

# Layer our config + entrypoint + migration + seed assets over the
# upstream image. Volumes mounted at runtime override these.
COPY qdrant_config.yaml /qdrant/config/production.yaml
COPY docker-entrypoint.sh /qdrant/docker-entrypoint.sh
COPY migrations/ /qdrant/migrations/
COPY seeds/ /qdrant/seeds/
COPY lib/qdrant.sh /qdrant/lib/qdrant.sh

RUN chmod +x /qdrant/docker-entrypoint.sh /qdrant/lib/qdrant.sh

WORKDIR /qdrant

# Qdrant's upstream image listens on 6333 + 6334 by default.
EXPOSE 6333 6334

ENTRYPOINT ["/bin/bash", "/qdrant/docker-entrypoint.sh"]
CMD []
