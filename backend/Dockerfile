FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models

WORKDIR /app

# CPU-only torch first: the default wheel pulls ~2 GB of CUDA libraries the app never uses.
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
# The embedding model (~130 MB) downloads on first use into the /models volume.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
