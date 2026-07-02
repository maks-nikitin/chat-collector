FROM node:20-alpine

WORKDIR /usr/src/app

# package.json лежит в node-server/, но контекст сборки — корень проекта
# (см. docker-compose.yml), чтобы можно было скопировать папку frontend
COPY node-server/package.json ./package.json
RUN npm install --omit=dev

COPY node-server/server.js ./server.js
COPY frontend ./frontend

EXPOSE 3000

CMD ["node", "server.js"]
