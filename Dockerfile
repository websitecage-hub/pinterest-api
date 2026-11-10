FROM python:3.12-slim

# Node.js is required by the Arkose solver (jsdom via the `javascript` package)
# and by PyExecJS (arkose.js).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-install the solver's jsdom dependency at build time so a cold start does
# not have to npm-install it.
RUN python -c "from javascript import require; require('jsdom')"

COPY pinterest_cli.py pin_autoauth.py pinterest_app.py reference_api.py proxy_test.py ./
COPY start.sh env.example ./
COPY BypassV3/ BypassV3/
COPY funcaptcha-solver/ funcaptcha-solver/

ENV PIN_DATA_DIR=/data \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data

EXPOSE 8000
CMD ["bash", "start.sh"]
