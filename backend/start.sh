#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib uvicorn main:app --reload --port 8000
