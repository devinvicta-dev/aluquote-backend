# Digital Ocean Deployment Guide

This guide covers multiple deployment options for the AluQuote AI backend on Digital Ocean.

## Prerequisites

- Digital Ocean account
- Git repository (GitHub, GitLab, or Bitbucket) with your code
- Basic knowledge of Docker and command line

---

## Option 1: DigitalOcean App Platform (Recommended for Quick Setup)

DigitalOcean App Platform is the easiest way to deploy. It automatically builds from your Dockerfile and handles scaling.

### Step 1: Prepare Your Repository

1. Push your code to GitHub, GitLab, or Bitbucket
2. Ensure your `Dockerfile` is in the root directory (✅ already done)

### Step 2: Create App on DigitalOcean

1. Go to [DigitalOcean App Platform](https://cloud.digitalocean.com/apps)
2. Click **"Create App"**
3. Connect your Git repository
4. Select the repository and branch
5. App Platform will auto-detect your Dockerfile

### Step 3: Configure the App

**Basic Settings:**
- **Name**: `aluquote-backend` (or your preferred name)
- **Region**: Choose closest to your users
- **Build Command**: (auto-detected from Dockerfile)
- **Run Command**: If not auto-detected, manually enter:
  ```
  uvicorn main:app --host 0.0.0.0 --port 8000
  ```

**Note**: If Digital Ocean shows "No run command defined", manually set it in the Run Command field above.

**Resource Configuration:**
- **Plan**: Basic ($5/month) for testing, Professional for production
- **Instance Size**: Basic (512MB RAM) minimum, recommended 1GB+ for production
- **Instance Count**: 1 for dev, 2+ for production (high availability)

**Environment Variables** (if needed in the future):
```
# Add these in App Platform settings if you need them
PORT=8000
```

### Step 4: Deploy

1. Review the settings
2. Click **"Create Resources"**
3. Wait for build and deployment (5-10 minutes)
4. Your app will be available at `https://your-app-name.ondigitalocean.app`

### Step 5: Configure Custom Domain (Optional)

1. Go to **Settings** → **Domains**
2. Add your custom domain
3. Follow DNS configuration instructions

---

## Option 2: DigitalOcean Droplet with Docker

For more control over the environment, deploy on a Droplet.

### Step 1: Create a Droplet

1. Go to [DigitalOcean Droplets](https://cloud.digitalocean.com/droplets/new)
2. **Choose an image**: Ubuntu 22.04 LTS
3. **Plan**:
   - **Basic**: $6/month (1GB RAM) for testing
   - **Basic**: $12/month (2GB RAM) recommended for production
4. **Authentication**: SSH keys (recommended) or password
5. **Hostname**: `aluquote-backend`
6. Click **"Create Droplet"**

### Step 2: SSH into Your Droplet

```bash
ssh root@your-droplet-ip
```

### Step 3: Install Docker

```bash
# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
apt install docker-compose -y

# Add current user to docker group (if not root)
# usermod -aG docker $USER
```

### Step 4: Clone Your Repository

```bash
# Install Git if needed
apt install git -y

# Clone your repository
git clone https://github.com/yourusername/your-repo.git
cd your-repo
```

### Step 5: Build and Run Docker Container

```bash
# Build the Docker image
docker build -t aluquote-backend .

# Run the container
docker run -d \
  --name aluquote-backend \
  -p 8000:8000 \
  --restart unless-stopped \
  -v $(pwd)/uploads:/app/uploads \
  -v $(pwd)/exports:/app/exports \
  aluquote-backend
```

### Step 6: Verify Deployment

```bash
# Check if container is running
docker ps

# Check logs
docker logs aluquote-backend

# Test the API
curl http://localhost:8000/api/health
```

### Step 7: Configure Firewall

```bash
# Allow SSH
ufw allow OpenSSH

# Allow HTTP/HTTPS
ufw allow 80/tcp
ufw allow 443/tcp

# Allow your app port (if accessing directly)
ufw allow 8000/tcp

# Enable firewall
ufw enable
```

### Step 8: Set Up Nginx Reverse Proxy (Recommended)

Install Nginx to handle SSL and proxy requests:

```bash
# Install Nginx
apt install nginx -y

# Create Nginx configuration
nano /etc/nginx/sites-available/aluquote-backend
```

Add the following configuration:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Increase timeout for file uploads
        client_max_body_size 50M;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }
}
```

Enable the site:

```bash
ln -s /etc/nginx/sites-available/aluquote-backend /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx
```

### Step 9: Set Up SSL with Let's Encrypt

```bash
# Install Certbot
apt install certbot python3-certbot-nginx -y

# Get SSL certificate
certbot --nginx -d your-domain.com

# Auto-renewal is set up automatically
```

---

## Option 3: Using Docker Compose (Recommended for Production)

Use the provided `docker-compose.yml` for easier management.

### On Your Droplet:

```bash
# Clone repository
git clone https://github.com/yourusername/your-repo.git
cd your-repo

# Start services
docker-compose up -d

# Check logs
docker-compose logs -f

# Stop services
docker-compose down
```

---

## Post-Deployment Configuration

### 1. Persistent Storage

For App Platform, use **Spaces** (Object Storage) or mount volumes.

For Droplets, use Docker volumes (already configured in docker-compose.yml):

```yaml
volumes:
  - ./uploads:/app/uploads
  - ./exports:/app/exports
```

### 2. Environment Variables

Create a `.env` file for sensitive configuration:

```bash
# .env (for docker-compose)
PORT=8000
# Add other variables as needed
```

### 3. Monitoring

**Health Check Endpoint:**
```
GET https://your-domain.com/api/health
```

**Set up monitoring:**
- DigitalOcean Monitoring (built-in)
- Application logs: `docker logs aluquote-backend` or App Platform logs tab

### 4. Backups

**For Droplets:**
- Use DigitalOcean automated backups ($2-4/month)
- Backup volumes: `docker exec container tar -czf backup.tar.gz /app/uploads /app/exports`

**For App Platform:**
- Backups are handled automatically for databases
- For file storage, use Spaces with lifecycle policies

---

## Scaling

### App Platform:
- Go to **Settings** → **Resources**
- Increase instance count or size
- Horizontal scaling is automatic

### Droplets:
- Use Docker Swarm or Kubernetes
- Or use a load balancer with multiple droplets
- Consider DigitalOcean Kubernetes for advanced scaling

---

## Troubleshooting

### Container won't start:
```bash
# Check logs
docker logs aluquote-backend

# Check if port is in use
netstat -tulpn | grep 8000
```

### File upload issues:
- Ensure `uploads/` and `exports/` directories have write permissions
- Check disk space: `df -h`
- Verify volume mounts in Docker

### Memory issues:
- Increase Droplet RAM or App Platform instance size
- Check memory usage: `docker stats`

### SSL issues:
- Verify DNS settings
- Check Certbot certificate: `certbot certificates`
- Renew certificate: `certbot renew`

---

## Cost Estimation

### App Platform:
- **Basic**: $5/month (512MB RAM, 1 vCPU)
- **Professional**: $12/month (1GB RAM, 1 vCPU) - Recommended

### Droplet:
- **Basic**: $6/month (1GB RAM) - Testing
- **Basic**: $12/month (2GB RAM) - Production Recommended
- **Backups**: +20% of droplet cost

### Additional Costs:
- **Domain**: $12/year (if using custom domain)
- **SSL**: Free with Let's Encrypt
- **Spaces/Object Storage**: $5/month for 250GB (if needed)

---

## Security Best Practices

1. **Always use HTTPS** (SSL/TLS)
2. **Keep system updated**: `apt update && apt upgrade`
3. **Use SSH keys** instead of passwords
4. **Configure firewall** (ufw)
5. **Regular backups**
6. **Monitor logs** for suspicious activity
7. **Use environment variables** for secrets (when needed)
8. **Enable App Platform auto-deploy from Git** (for App Platform)

---

## Next Steps

1. Set up CI/CD pipeline for automatic deployments
2. Configure monitoring and alerting
3. Set up automated backups
4. Configure custom domain with SSL
5. Set up staging environment for testing

---

## Support Resources

- [DigitalOcean Documentation](https://docs.digitalocean.com/)
- [App Platform Docs](https://docs.digitalocean.com/products/app-platform/)
- [Docker Documentation](https://docs.docker.com/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
