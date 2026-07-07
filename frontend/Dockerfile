FROM node:22-alpine AS build

ARG APP_VERSION=1.0
ENV VITE_APP_VERSION=$APP_VERSION

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
ARG APP_VERSION=1.0
LABEL org.opencontainers.image.title="wecom-workbot-query-ui" \
      org.opencontainers.image.version=$APP_VERSION
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
