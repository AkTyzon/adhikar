# Deployment

## Local

```bash
make serve                          # http://127.0.0.1:8000
docker compose up --build           # same, containerised
```

## Container

```bash
docker build -t adhikar .
docker run -p 8000:8000 \
  -e ADHIKAR_ENVIRONMENT=development \
  -e ADHIKAR_DATABASE_URL=sqlite+aiosqlite:///./adhikar.db \
  adhikar
```

The image is multi-stage, runs as an unprivileged user with no login shell, drops
all capabilities under compose, mounts the root filesystem read-only, and carries
a healthcheck that exercises configuration loading and the clause catalogue — so
a container answering it has genuinely started, not merely bound a port.

## Production checklist

`ADHIKAR_ENVIRONMENT=production` refuses to start in a knowingly unsafe posture:
debug enabled, PII redaction disabled, or SQLite as the database. That is a
validator in [`config.py`](../src/adhikar/config.py), not documentation.

Beyond that:

- [ ] Terminate TLS at a reverse proxy. HSTS is emitted automatically in
      production.
- [ ] Configure the proxy to **rewrite the socket address**. `X-Forwarded-For` is
      deliberately not trusted for rate limiting — honouring a client-supplied
      header hands any caller unlimited identities.
- [ ] Set `ADHIKAR_DATABASE_URL` to PostgreSQL. Only audit records are persisted;
      documents are never written to disk.
- [ ] Supply `ADHIKAR_ANTHROPIC_API_KEY` via your secret manager, never a file in
      the image. With no key the offline engine runs instead of failing.
- [ ] Review `ADHIKAR_INJECTION_BLOCK_THRESHOLD` (default 0.80). Lower is
      stricter; a lower value refuses more documents.
- [ ] Keep `--workers 1`, or give the document store a shared backend first — a
      session's document lives in the worker that received it.
- [ ] Ship logs somewhere with access control. They are PII-scrubbed by a
      processor, but they still record which documents were analysed and when.

## Scaling

The deliberate constraint is that documents are held in memory. Removing it means
replacing `MemoryDocumentStore` in [`store.py`](../src/adhikar/store.py) with a
shared store — at which point the privacy guarantee that nothing touches disk no
longer holds, and that should be a conscious decision rather than an accident of
deployment.

Audit records are already storage-backed and safe to share across workers.
