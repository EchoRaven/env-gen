FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY seed_data.json ./
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh
EXPOSE 8000
CMD ["sh", "entrypoint.sh"]
