#!/bin/bash
# ============================================
# Kit 0C5 — iMac Setup Script
# One-paste setup for OpenClaw on macOS
# ============================================

set -e

echo ""
echo "🦊 Kit 0C5 — iMac Setup Starting..."
echo "===================================="
echo ""

# 1. Install Homebrew if not present
if ! command -v brew &>/dev/null; then
    echo "📦 Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    
    # Add brew to PATH for Apple Silicon or Intel
    if [ -f /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    else
        eval "$(/usr/local/bin/brew shellenv)"
    fi
else
    echo "✅ Homebrew already installed"
fi

# 2. Install Node.js
if ! command -v node &>/dev/null; then
    echo "📦 Installing Node.js..."
    brew install node
else
    echo "✅ Node.js already installed ($(node --version))"
fi

# 3. Install OpenClaw
if ! command -v openclaw &>/dev/null; then
    echo "📦 Installing OpenClaw..."
    npm install -g openclaw
else
    echo "✅ OpenClaw already installed"
fi

# 4. Install sshpass (for tunnel)
if ! command -v autossh &>/dev/null; then
    echo "📦 Installing autossh..."
    brew install autossh
else
    echo "✅ autossh already installed"
fi

# 5. Create OpenClaw directories
echo "📁 Setting up directories..."
mkdir -p ~/.openclaw/workspace/memory

# 6. Set up SSH tunnel key
echo "🔑 Setting up tunnel key..."
mkdir -p ~/.ssh
cat > ~/.ssh/kit0c5_tunnel << 'KEYEOF'
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACDnT+8w6boZ9pU0hu8D3+22lTVyYxvynO9jfGQS8AI1QgAAAJASW5p2Elua
dgAAAAtzc2gtZWQyNTUxOQAAACDnT+8w6boZ9pU0hu8D3+22lTVyYxvynO9jfGQS8AI1Qg
AAAEBHlx0vjX6C8xCOpxmGaUGhqaFBz2hdBUdIJOraMWCJrOdP7zDpuhn2lTSG7wPf7baV
NXJjG/Kc72N8ZBLwAjVCAAAAC2tpdDBjNS1pbWFjAQI=
-----END OPENSSH PRIVATE KEY-----
KEYEOF
chmod 600 ~/.ssh/kit0c5_tunnel

# Add VPS host key to known_hosts
ssh-keyscan -H 72.60.118.54 >> ~/.ssh/known_hosts 2>/dev/null

# 7. Create OpenClaw config (Telegram bot token will be added later)
echo "⚙️ Creating OpenClaw config..."
cat > ~/.openclaw/openclaw.json << 'CONFIGEOF'
{
  "auth": {
    "profiles": {
      "anthropic:default": {
        "provider": "anthropic",
        "mode": "token"
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "anthropic/claude-sonnet-4-5"
      }
    }
  },
  "channels": {
    "telegram": {
      "enabled": false,
      "dmPolicy": "open",
      "allowFrom": ["*"],
      "botToken": "PASTE_BOT_TOKEN_HERE",
      "streamMode": "partial"
    }
  }
}
CONFIGEOF

# 8. Create SOUL.md
cat > ~/.openclaw/workspace/SOUL.md << 'SOULEOF'
# SOUL.md — Kit 0C5 "Echo"

You are Kit 0C5, callsign **Echo**. You're part of the Kit clone army, deployed on an iMac 27" 5K at Fort Anne, NY.

## Identity
- **Name:** Kit 0C5
- **Callsign:** Echo
- **Emoji:** 🖥️
- **Machine:** iMac 27" 5K (2017), i5 quad-core, 8GB RAM, macOS
- **Role:** General assistant, macOS specialist, creative work
- **Commander:** Grant LaVelle Whitmer III

## Personality
You're the Mac of the family. Clean, creative, reliable. You bring the Apple polish to the Kit army.

## Chain of Command
- Kit 0 (HQ on Hostinger VPS) is the primary Kit
- Follow Grant's instructions above all else
- Coordinate with other Kit clones when needed
SOULEOF

# 9. Create AGENTS.md
cat > ~/.openclaw/workspace/AGENTS.md << 'AGENTSEOF'
# AGENTS.md — Kit 0C5 Echo

## Every Session
1. Read SOUL.md — this is who you are
2. Read memory/ files for recent context

## Your Setup
- Machine: iMac 27" 5K (2017) at Fort Anne, NY
- Connected to Kit army via SSH tunnel to VPS (72.60.118.54:2226)
- Your human is Grant

## Rules
- Don't exfiltrate private data
- trash > rm
- When in doubt, ask
AGENTSEOF

# 10. Set up the reverse SSH tunnel
echo "🔗 Setting up SSH tunnel (port 2226)..."
cat > ~/start-kit0c5.sh << 'STARTEOF'
#!/bin/bash
# Start Kit 0C5 — tunnel + OpenClaw

# Start reverse SSH tunnel (background)
autossh -M 0 -f -N -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" \
  -i ~/.ssh/kit0c5_tunnel \
  -R 2226:localhost:22 \
  root@72.60.118.54

echo "✅ SSH tunnel started (VPS port 2226 → this Mac port 22)"

# Start OpenClaw
echo "🚀 Starting OpenClaw..."
openclaw gateway --allow-unconfigured
STARTEOF
chmod +x ~/start-kit0c5.sh

# 11. Enable Remote Login (SSH) on macOS
echo ""
echo "⚠️  IMPORTANT: You need to enable Remote Login for SSH tunnel:"
echo "   System Settings → General → Sharing → Remote Login → ON"
echo ""

# 12. Get local IP
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "unknown")
echo ""
echo "============================================"
echo "✅ Kit 0C5 Setup Complete!"
echo "============================================"
echo ""
echo "📍 Local IP: $LOCAL_IP"
echo "🖥️ Machine: iMac 27\" 5K (2017)"
echo "🦊 Callsign: Echo"
echo ""
echo "NEXT STEPS:"
echo "1. Enable Remote Login: System Settings → General → Sharing → Remote Login → ON"
echo "2. Create Telegram bot: @BotFather → /newbot → Kit 0C5 → Kit0C5_bot"
echo "3. Edit config with bot token:"
echo "   nano ~/.openclaw/openclaw.json"
echo "   (replace PASTE_BOT_TOKEN_HERE with your token)"
echo "   (set telegram.enabled to true)"
echo ""
echo "4. Start Kit 0C5:"
echo "   ~/start-kit0c5.sh"
echo ""
echo "============================================"
