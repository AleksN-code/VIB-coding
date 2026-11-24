FROM node:22-alpine

WORKDIR /app
RUN chown node:node /app
# Запуск не від root
USER node

# Спершу лише залежності — цей шар кешується, поки package*.json не зміниться
COPY --chown=node:node package.json package-lock.json ./
RUN npm ci

COPY --chown=node:node . .

EXPOSE 5173
# Dev-сервер Vite з автооновленням сторінки при зміні коду
CMD ["npm", "run", "dev"]
