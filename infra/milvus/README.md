# Milvus (Docker) for UAE Law RAG

## Start
cd infra/milvus
cp .env.example .env  # optional
docker compose up -d

## Check
docker ps
# Milvus gRPC exposed at localhost:19530

## Stop
docker compose down

## Stop and wipe data
docker compose down -v
