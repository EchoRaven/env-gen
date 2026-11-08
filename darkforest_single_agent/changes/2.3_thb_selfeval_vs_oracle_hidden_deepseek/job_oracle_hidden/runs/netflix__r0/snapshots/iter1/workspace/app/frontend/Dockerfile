FROM node:22-alpine

WORKDIR /srv/frontend

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "preview"]

