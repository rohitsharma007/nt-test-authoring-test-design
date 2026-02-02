#!/bin/bash
set -e

echo "Installing dependencies..."
python -m pip install --upgrade pip

if [ -f requirements.txt ]; then
    pip install -r requirements.txt
fi

echo "Starting Multi-Agent Test Authoring Application..."
python -m streamlit run app_multi_agent.py --server.port 8000 --server.address 0.0.0.0
