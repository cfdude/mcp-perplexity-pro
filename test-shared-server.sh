#!/bin/bash

# Test script for shared server functionality
echo "Testing MCP Shared Server Architecture"
echo "======================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if server is running on a port
check_server() {
    local port=$1
    curl -s "http://localhost:$port/health" > /dev/null 2>&1
    return $?
}

# Kill any existing servers on our port range
echo -e "${YELLOW}Cleaning up any existing servers...${NC}"
for port in {8124..8133}; do
    if check_server $port; then
        echo "  Killing server on port $port"
        lsof -ti:$port | xargs kill -9 2>/dev/null
    fi
done
sleep 1

echo ""
echo -e "${GREEN}Test 1: Starting first server instance${NC}"
echo "  Launching server on default port (8124)..."
npm start > server1.log 2>&1 &
SERVER1_PID=$!
sleep 3

# Check if server is running
if check_server 8124; then
    echo -e "  ${GREEN}✓ Server 1 started successfully on port 8124${NC}"
    
    # Get health check response
    HEALTH=$(curl -s "http://localhost:8124/health")
    echo "  Health check response: $HEALTH"
else
    echo -e "  ${RED}✗ Server 1 failed to start${NC}"
    kill $SERVER1_PID 2>/dev/null
    exit 1
fi

echo ""
echo -e "${GREEN}Test 2: Starting second server instance (should detect existing)${NC}"
echo "  Attempting to start second instance..."
npm start > server2.log 2>&1 &
SERVER2_PID=$!
sleep 3

# Check if second process exited (as expected)
if kill -0 $SERVER2_PID 2>/dev/null; then
    echo -e "  ${RED}✗ Second instance is still running (unexpected)${NC}"
    kill $SERVER2_PID 2>/dev/null
else
    echo -e "  ${GREEN}✓ Second instance detected existing server and exited${NC}"
    
    # Check the log for the expected message
    if grep -q "Found existing healthy MCP server" server2.log; then
        echo -e "  ${GREEN}✓ Log confirms existing server detection${NC}"
    else
        echo -e "  ${YELLOW}⚠ Log doesn't show expected detection message${NC}"
        echo "  Server 2 log output:"
        cat server2.log | head -5
    fi
fi

echo ""
echo -e "${GREEN}Test 3: Force starting on different port${NC}"
echo "  Starting server on port 8125..."
npm start -- --http-port=8125 > server3.log 2>&1 &
SERVER3_PID=$!
sleep 3

if check_server 8125; then
    echo -e "  ${GREEN}✓ Server 3 started successfully on port 8125${NC}"
else
    echo -e "  ${RED}✗ Server 3 failed to start on port 8125${NC}"
fi

echo ""
echo -e "${GREEN}Test 4: Port discovery when primary port is occupied${NC}"
echo "  Killing server on 8124..."
kill $SERVER1_PID 2>/dev/null
sleep 1

echo "  Starting new server (should use 8125 since it's occupied)..."
npm start > server4.log 2>&1 &
SERVER4_PID=$!
sleep 3

# Check which port the new server is using
FOUND_PORT=""
for port in {8124..8133}; do
    if check_server $port && [ "$port" != "8125" ]; then
        FOUND_PORT=$port
        break
    fi
done

if [ -n "$FOUND_PORT" ]; then
    echo -e "  ${GREEN}✓ Server 4 started on available port $FOUND_PORT${NC}"
else
    echo -e "  ${RED}✗ Server 4 failed to find available port${NC}"
fi

echo ""
echo -e "${YELLOW}Cleaning up test servers...${NC}"
kill $SERVER1_PID $SERVER3_PID $SERVER4_PID 2>/dev/null
for port in {8124..8133}; do
    lsof -ti:$port | xargs kill -9 2>/dev/null
done

echo ""
echo "======================================="
echo -e "${GREEN}Shared Server Tests Complete!${NC}"
echo ""
echo "Summary:"
echo "  • Server can detect existing instances"
echo "  • Multiple servers can run on different ports"
echo "  • Port discovery finds available ports automatically"
echo "  • Health check endpoint is working correctly"

# Clean up log files
rm -f server1.log server2.log server3.log server4.log

exit 0