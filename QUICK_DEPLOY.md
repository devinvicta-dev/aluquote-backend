# Quick Deploy Guide - Digital Ocean

## Fastest Way: DigitalOcean App Platform (5 minutes)

1. **Push code to GitHub/GitLab**
   ```bash
   git add .
   git commit -m "Ready for deployment"
   git push origin main
   ```

2. **Create App on DigitalOcean**
   - Go to: https://cloud.digitalocean.com/apps
   - Click "Create App"
   - Connect your Git repository
   - Select your repo and branch

3. **Configure App**
   - App Platform auto-detects Dockerfile ✅
   - Choose region (closest to users)
   - Select plan: Basic ($5/month) or Professional ($12/month)
   - Click "Create Resources"

4. **Wait 5-10 minutes**
   - Build completes automatically
   - App is live at: `https://your-app-name.ondigitalocean.app`

5. **Test**
   ```bash
   curl https://your-app-name.ondigitalocean.app/api/health
   ```

**Done!** 🎉

---

## Alternative: Droplet with Docker (15 minutes)

1. **Create Droplet**
   - Ubuntu 22.04 LTS
   - $12/month (2GB RAM recommended)
   - Add SSH key

2. **SSH into Droplet**
   ```bash
   ssh root@your-droplet-ip
   ```

3. **Run Quick Setup**
   ```bash
   # Install Docker
   curl -fsSL https://get.docker.com -o get-docker.sh
   sh get-docker.sh

   # Clone and deploy
   git clone https://github.com/yourusername/your-repo.git
   cd your-repo
   docker-compose up -d
   ```

4. **Configure Nginx (Optional)**
   ```bash
   apt install nginx certbot python3-certbot-nginx -y
   # Configure nginx, then:
   certbot --nginx -d your-domain.com
   ```

**Your app is live!** 🚀

---

## Using the Deploy Script

If deploying to a Droplet:

```bash
# Make script executable
chmod +x deploy.sh

# Run deployment
./deploy.sh production
```

The script will:
- Pull latest code
- Build Docker image
- Stop old container
- Start new container
- Run health check

---

## Cost Comparison

| Option | Monthly Cost | Best For |
|--------|-------------|----------|
| App Platform Basic | $5 | Testing/Development |
| App Platform Pro | $12 | Production |
| Droplet 1GB | $6 | Learning |
| Droplet 2GB | $12 | Production (more control) |

---

## Need Help?

See [DEPLOYMENT.md](./DEPLOYMENT.md) for detailed instructions.
