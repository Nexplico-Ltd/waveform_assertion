FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY src/ ./src/
COPY conftest.py .

# Create output directory
RUN mkdir -p output

ENV PYTHONPATH=/app/src

EXPOSE 7860

CMD ["python", "src/ui/app.py"]
