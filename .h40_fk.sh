#!/bin/bash
docker rm -f h40fk >/dev/null 2>&1
docker run -d --name h40fk -e POSTGRES_PASSWORD=p -e POSTGRES_DB=t postgres:16 >/dev/null 2>&1
for i in $(seq 1 60); do
  if docker exec h40fk pg_isready -U postgres >/dev/null 2>&1; then break; fi
  sleep 1
done
docker cp /mnt/f/dev/ktm-hotfix/.h40_fk.sql h40fk:/tmp/t.sql >/dev/null
docker exec h40fk psql -U postgres -d t -f /tmp/t.sql 2>&1
docker rm -f h40fk >/dev/null 2>&1
