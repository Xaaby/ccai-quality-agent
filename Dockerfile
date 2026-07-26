FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer caching)
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Generate SQLite database at build time (bakes transcripts into image)
RUN python app/data/generate_transcripts.py

# Expose single port — Cloud Run requirement
EXPOSE 8080

# Single process — Streamlit only, no FastAPI
CMD ["streamlit", "run", "app/streamlit_app.py", \
     "--server.port=8080", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
