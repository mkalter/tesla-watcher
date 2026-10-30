FROM node:22-bookworm-slim
ENV NODE_ENV=production PUPPETEER_SKIP_DOWNLOAD=true CHROMIUM_PATH=/usr/bin/chromium CHROME_NO_SANDBOX=1 HOST=0.0.0.0 BRIDGE_DATA=/app/data
RUN apt-get update && apt-get install -y --no-install-recommends chromium dumb-init ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund && mkdir -p /app/data && chown node:node /app/data
COPY server.js .
USER node
EXPOSE 3000
ENTRYPOINT ["dumb-init", "--"]
CMD ["node", "server.js"]
