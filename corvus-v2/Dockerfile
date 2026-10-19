# The Corvus v2 decision-engine image (P1's WP1-WP16).
# The build context is the REPO ROOT (the decision-register.yaml is the
# compiler's SSOT, mounted into the image — the C6 git-shipped delivery
# mode; the register updates are config changes, not image rebuilds).
FROM python:3.12-slim

WORKDIR /app

COPY corvus-v2/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY corvus-v2/corvus/ /app/corvus/
COPY decision-register.yaml /app/decision-register.yaml

# The conformance CLI is the image's built-in probe (WP14: the engine
# ships its own probe — `docker run ... conformance` runs the fixtures
# against any base-url).
COPY corvus-v2/corvus/conformance.py /app/corvus/conformance.py

EXPOSE 8933
CMD ["python", "-m", "corvus.engine_shim", "--port", "8933"]
