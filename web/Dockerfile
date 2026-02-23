FROM node:22-slim AS build

WORKDIR /app
COPY package.json ./
RUN npm install --production=false
COPY . .
RUN npm run build

FROM nginx:1-alpine
RUN sed -i 's/worker_processes.*auto;/worker_processes 2;/' /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
