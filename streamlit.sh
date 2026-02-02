#!/bin/bash
set -e
python -m pip install --upgrade pip
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0
