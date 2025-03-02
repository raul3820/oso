#!/bin/bash
set -e  # Exit immediately if a command exits with a non-zero status.

# --- Check for POSTGRES_URL ---
if [ -z "$POSTGRES_URL" ]; then
  echo "Error: POSTGRES_URL environment variable is not set."
  exit 1
fi

# --- check OPENAI_API_URL ---
if [ -z "$OPENAI_API_URL" ]; then
  echo "Error: OPENAI_API_URL environment variable is not set."
  exit 1
fi

# --- Wait for Postgres to be ready ---
echo "Waiting for Postgres at $POSTGRES_URL..."
while ! pg_isready -d "$POSTGRES_URL" -q; do
  echo "$(date) - Postgres is unavailable - sleeping"
  sleep 5
done
echo "Postgres is up and running."

# --- Wait for OpenAI to be ready ---
echo "Waiting for OpenAI at $OPENAI_API_URL/models..."
while ! curl --output /dev/null --silent --fail "$OPENAI_API_URL/models"; do
  echo "$(date) - OpenAI is unavailable - sleeping"
  sleep 5
done
echo "OpenAI is up and running."

python run.py

tail -f /dev/null