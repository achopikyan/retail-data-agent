# --- build stage --------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /web

COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build

# --- serve stage --------------------------------------------------------
FROM nginx:alpine

COPY --from=build /web/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
