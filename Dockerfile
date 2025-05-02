# Dockerfile

# 1) Use a lightweight Python base image
FROM python:3.11-slim

# 2) Set working directory
WORKDIR /app

# 3) Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4) Copy your application code
COPY . .

# 5) Expose the port FastAPI listens on
EXPOSE 8000

# 6) Runtime command: launch Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]