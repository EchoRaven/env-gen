FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
# dist/ already contains the public assets (Vite copies public/ into dist/)
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
