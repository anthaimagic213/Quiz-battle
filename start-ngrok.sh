#!/bin/bash

# Script to start ngrok for frontend and backend

echo "🚀 Starting ngrok tunnels..."

# Kill any existing ngrok processes
pkill -f ngrok 2>/dev/null

# Wait a moment
sleep 1

# Start ngrok for frontend (3000)
echo "📱 Starting frontend tunnel on port 3000..."
ngrok http 3000 --log=stdout > /tmp/ngrok-frontend.log 2>&1 &
FRONTEND_PID=$!

# Start ngrok for backend (8000) 
echo "⚙️  Starting backend tunnel on port 8000..."
ngrok http 8000 --region us --log=stdout > /tmp/ngrok-backend.log 2>&1 &
BACKEND_PID=$!

# Wait for ngrok to start
sleep 3

# Get ngrok URLs
echo ""
echo "======================================"
echo "✅ NGROK TUNNELS STARTED"
echo "======================================"
echo ""
echo "📱 Frontend: $(curl -s http://localhost:4040/api/tunnels | grep -o '"public_url":"[^"]*"' | head -1 | cut -d'"' -f4)"
echo "⚙️  Backend: $(curl -s http://localhost:4040/api/tunnels | grep -o '"public_url":"[^"]*"' | tail -1 | cut -d'"' -f4)"
echo ""
echo "Press Ctrl+C to stop tunnels"
echo "======================================"
echo ""

# Keep script running
wait $FRONTEND_PID $BACKEND_PID
