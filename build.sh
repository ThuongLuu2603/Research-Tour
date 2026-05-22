#!/usr/bin/env bash
set -euo pipefail

echo "Building frontend..."
cd frontend
npm ci
npm run build
cd ..

echo "Installing backend dependencies..."
cd backend
pip install -r requirements.txt
cd ..

echo "Build complete."
