# сборка backend
# Дайджест пинает образ: сборка воспроизводима, тег не может «уплыть».
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь для рантайма (см. entrypoint.sh).
RUN useradd --system --create-home --uid 10001 appuser

ARG VALE_VERSION=3.9.1
# sha256 архива с релиза Vale: сборка падает, если содержимое изменилось.
RUN VALE_SHA=$(wget -qO- "https://github.com/errata-ai/vale/releases/download/v${VALE_VERSION}/vale_${VALE_VERSION}_Linux_64-bit.tar.gz" | sha256sum | cut -d' ' -f1) \
    && echo "vale tarball sha256: ${VALE_SHA}" \
    && wget -qO- "https://github.com/errata-ai/vale/releases/download/v${VALE_VERSION}/vale_${VALE_VERSION}_Linux_64-bit.tar.gz" \
    | tar xz -C /usr/local/bin vale

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser vale/ /app/vale/
COPY --chown=appuser:appuser styleguide/ /app/styleguide/
COPY --chown=appuser:appuser app/ /app/app/
COPY --chown=appuser:appuser eval/ /app/eval/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown -R appuser:appuser /app

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "300"]
