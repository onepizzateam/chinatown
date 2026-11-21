# Stage 1: bake the routing tables (needs scipy; kept out of the runtime image).
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS bake
RUN pip install --no-cache-dir numpy==2.3.4 scipy==1.16.3
WORKDIR /src
COPY tools/bake_nav.py tools/
COPY bot/data/map.npz bot/data/
RUN python tools/bake_nav.py bot/data/map.npz bot/data/nav.npz 16 40

# Stage 2: the bot. numpy only, installed system-wide (the bot runs as uid 65534).
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
RUN pip install --no-cache-dir numpy==2.3.4
WORKDIR /bot
COPY bot/*.py ./
COPY bot/data/map.npz data/
COPY --from=bake /src/bot/data/nav.npz data/
ENTRYPOINT ["python3", "-u", "/bot/main.py"]
