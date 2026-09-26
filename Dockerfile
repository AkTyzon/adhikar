# syntax=docker/dockerfile:1

# Multi-stage build for Cloud Run. Deps, build and runtime are separate stages so
# the final image carries no compilers, no dev dependencies and no source.

# ------------------------------------------------------------------ deps
FROM node:22-alpine AS deps
WORKDIR /app
# Manifests only, so a source-only change does not invalidate this layer.
COPY package.json package-lock.json ./
RUN npm ci

# ----------------------------------------------------------------- build
FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# `prebuild` copies the pdf.js worker into public/ before this runs.
RUN npm run build

# --------------------------------------------------------------- runtime
FROM node:22-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080 \
    HOSTNAME=0.0.0.0

# Run unprivileged. A web process that does not need root should never have it.
RUN addgroup -g 1001 -S nodejs && adduser -u 1001 -S nextjs -G nodejs

# `standalone` already contains a minimal node_modules and the server entrypoint.
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public

USER nextjs

# Cloud Run injects PORT; 8080 is its default and the value this image defaults to.
EXPOSE 8080

CMD ["node", "server.js"]
