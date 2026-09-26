FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

USER nobody
EXPOSE 8765
CMD ["selfoss-mcp", "--transport", "http", "--host", "0.0.0.0"]
