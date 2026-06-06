FROM python:3.12-slim

WORKDIR /app

# Install system deps (tesseract for OCR fallback on scanned PDFs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p uploads

EXPOSE 53500

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "53500"]
