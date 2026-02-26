#!/bin/bash

# 🚀 SYNTHORA ELITE V4 - AUTO DEPLOYMENT SCRIPT V5
# This script automatically deploys Synthora Elite to your GitHub repo

echo "============================================================"
echo "🏙️  SYNTHORA ELITE V4 - DEPLOYMENT SCRIPT V5"
echo "============================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if we're in a git repository
if [ ! -d ".git" ]; then
    echo -e "${RED}❌ ERROR: Not in a git repository!${NC}"
    echo "Please run this script from your Synthora repository root."
    echo ""
    echo "Example:"
    echo "  cd /path/to/Synthora"
    echo "  bash deploy_v5.sh"
    exit 1
fi

echo -e "${BLUE}📂 Current directory: $(pwd)${NC}"
echo ""

# Check if synthora_elite_v4.py exists
if [ ! -f "synthora_elite_v4.py" ]; then
    echo -e "${RED}❌ ERROR: synthora_elite_v4.py not found!${NC}"
    echo "Please make sure synthora_elite_v4.py is in this directory."
    echo ""
    echo "Download it from Claude and place it here, then run this script again."
    exit 1
fi

echo -e "${GREEN}✅ Found synthora_elite_v4.py${NC}"
echo ""

# Show current apex_base.py if it exists
if [ -f "apex_base.py" ]; then
    echo -e "${YELLOW}⚠️  apex_base.py already exists${NC}"
    echo "This will be overwritten with the new version."
    echo ""
fi

# Ask for confirmation
echo -e "${YELLOW}🔍 REVIEW BEFORE DEPLOYMENT:${NC}"
echo "This script will:"
echo "  1. Copy synthora_elite_v4.py → apex_base.py"
echo "  2. Git add apex_base.py"
echo "  3. Git commit with message"
echo "  4. Git push to origin main"
echo ""
read -p "Continue with deployment? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo -e "${RED}❌ Deployment cancelled${NC}"
    exit 0
fi

echo ""
echo "============================================================"
echo "🚀 STARTING DEPLOYMENT"
echo "============================================================"
echo ""

# Step 1: Copy file
echo -e "${BLUE}📋 Step 1/4: Copying synthora_elite_v4.py → apex_base.py${NC}"
cp synthora_elite_v4.py apex_base.py

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ File copied successfully${NC}"
else
    echo -e "${RED}❌ Failed to copy file${NC}"
    exit 1
fi
echo ""

# Step 2: Git add
echo -e "${BLUE}📦 Step 2/4: Git add apex_base.py${NC}"
git add apex_base.py

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ File staged for commit${NC}"
else
    echo -e "${RED}❌ Git add failed${NC}"
    exit 1
fi
echo ""

# Step 3: Git commit
echo -e "${BLUE}💾 Step 3/4: Git commit${NC}"
git commit -m "Synthora Elite V4 - Full autonomous sniper with profit management

Features:
- Real-time Aerodrome pool monitoring
- Multi-layer security (liquidity + honeypot checks)
- Automated buying via Aerodrome Router
- 2.5x take profit with 40% auto-sell
- Moonbag management (60% retention)
- Telegram notifications
- Position tracking
- 24/7 autonomous operation

Config: 0.004 ETH per snipe, 4 ETH min liquidity"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Commit successful${NC}"
else
    echo -e "${YELLOW}⚠️  Commit failed (maybe no changes?)${NC}"
fi
echo ""

# Step 4: Git push
echo -e "${BLUE}🌐 Step 4/4: Git push to origin main${NC}"
git push origin main

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Push successful!${NC}"
else
    echo -e "${RED}❌ Push failed${NC}"
    echo "You may need to pull first or check your git credentials."
    exit 1
fi

echo ""
echo "============================================================"
echo "🎉 DEPLOYMENT COMPLETE!"
echo "============================================================"
echo ""
echo -e "${GREEN}✅ synthora_elite_v4.py deployed as apex_base.py${NC}"
echo ""
echo "📊 NEXT STEPS:"
echo ""
echo "1. ⏳ Wait for Render to auto-deploy (1-2 minutes)"
echo ""
echo "2. 🔍 Check Render logs for:"
echo "   ✅ Connected to Base RPC (Chain ID: 8453)"
echo "   ✅ Synthora Architect loaded: 0x..."
echo "   💰 Balance: X.XXX ETH"
echo "   ✅ Telegram bot connected"
echo "   🚀 Starting Synthora Elite threads..."
echo "   🕵️ Synthora Sentinel: Jacht op Alpha is geopend..."
echo "   📊 Position monitor started"
echo ""
echo "3. 📱 Test Telegram bot:"
echo "   /status      → Check bot status"
echo "   /positions   → View active positions"
echo ""
echo "4. ⚙️  Add trading settings in Render Environment:"
echo "   BUY_AMOUNT_ETH=0.004"
echo "   MIN_LIQUIDITY_ETH=4.0"
echo "   TAKE_PROFIT_X=2.5"
echo "   SELL_PERCENTAGE=40"
echo "   MAX_SLIPPAGE=12"
echo ""
echo "5. 🎯 Monitor for snipes!"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT REMINDERS:${NC}"
echo "   • Start with small amounts (0.004 ETH recommended)"
echo "   • Monitor first 24 hours closely"
echo "   • New tokens are HIGH RISK"
echo "   • Only invest what you can afford to lose"
echo ""
echo "🚀 Happy sniping! Let's get that Alpha!"
echo "============================================================"
