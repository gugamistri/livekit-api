# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# install your deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy code + any .env if you need python-dotenv (optional)
COPY . .

# default cmd is no-op—override in compose
CMD ["bash","-c","echo \"Specify a command in docker-compose!\""]