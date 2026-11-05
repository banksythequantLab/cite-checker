FROM python:3.12-slim
# The app runs as nobody, on a read-only root filesystem, with every Linux
# capability dropped. The only writable path is the cache volume. Egress is
# allow-listed by the HOST kernel (see deploy/egress.sh), not by this image.
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY cite/ cite/
COPY ui/ ui/
ENV CITE_CACHE=/cache/cite_cache.db PYTHONUNBUFFERED=1
# the cache volume must be writable by nobody; a named volume inherits this
# ownership when it is first created from the image
RUN mkdir -p /cache && chown 65534:65534 /cache
VOLUME /cache
USER 65534:65534
EXPOSE 8120
CMD ["uvicorn", "app:app", "--app-dir", "cite", "--host", "0.0.0.0", "--port", "8120"]
