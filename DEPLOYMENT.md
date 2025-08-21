# MCP Perplexity Pro - Deployment Guide

This guide covers various deployment options for the MCP Perplexity Pro server.

## Prerequisites

- Node.js 20+ installed
- Perplexity API key
- Docker (for containerized deployment)
- Smithery CLI (for development and publishing)

## Local Development Setup

### 1. Clone and Install

```bash
git clone https://github.com/cfdude/mcp-perplexity-pro.git
cd mcp-perplexity-pro
npm install
```

### 2. Development Mode

```bash
# Start development server with hot reload
npm run dev

# Run tests
npm test

# Run tests with coverage
npm run test:coverage

# Lint and format
npm run lint
npm run format
```

## MCP Configuration

### Claude Desktop Configuration

Add to your Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "perplexity-pro": {
      "command": "node",
      "args": ["/path/to/mcp-perplexity-pro/dist/index.js"],
      "env": {
        "NODE_ENV": "production"
      },
      "config": {
        "api_key": "your-perplexity-api-key",
        "default_model": "sonar-reasoning-pro",
        "project_root": "/path/to/your/project",
        "storage_path": ".perplexity/chat_history",
        "session_id": "optional-session-id"
      }
    }
  }
}
```

### Smithery Configuration

For Smithery-based deployment:

```json
{
  "servers": {
    "perplexity-pro": {
      "name": "mcp-perplexity-pro",
      "config": {
        "api_key": "your-perplexity-api-key",
        "default_model": "sonar-reasoning-pro",
        "project_root": "${PROJECT_ROOT}",
        "storage_path": ".perplexity",
        "session_id": "${SESSION_ID}"
      }
    }
  }
}
```

## Docker Deployment

### Option 1: Docker Compose (Recommended)

```bash
# Set environment variables
export PROJECT_ROOT=/path/to/your/project

# Build and run
docker-compose up -d

# For development with hot reload
docker-compose --profile dev up -d
```

### Option 2: Direct Docker Build

```bash
# Build image
docker build -t mcp-perplexity-pro .

# Run container
docker run -d \
  --name mcp-perplexity-pro \
  -v /path/to/your/project:/workspace:ro \
  -v ./storage:/app/storage \
  mcp-perplexity-pro
```

## Production Deployment

### 1. Build for Production

```bash
npm run build
npm run type-check
npm run lint
npm test
```

### 2. Environment Variables

Create a `.env` file or set environment variables:

```bash
NODE_ENV=production
PERPLEXITY_API_KEY=your-api-key
PROJECT_ROOT=/path/to/project
STORAGE_PATH=.perplexity
```

### 3. Process Management

Use PM2 for production process management:

```bash
# Install PM2
npm install -g pm2

# Create ecosystem file
cat > ecosystem.config.js << EOF
module.exports = {
  apps: [{
    name: 'mcp-perplexity-pro',
    script: 'dist/index.js',
    env: {
      NODE_ENV: 'production'
    },
    instances: 1,
    exec_mode: 'fork',
    watch: false,
    max_memory_restart: '1G'
  }]
};
EOF

# Start with PM2
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

## Cloud Deployment

### Heroku

1. Create `Procfile`:
```
web: node dist/index.js
```

2. Deploy:
```bash
heroku create your-app-name
heroku config:set NODE_ENV=production
heroku config:set PERPLEXITY_API_KEY=your-key
git push heroku main
```

### Railway

1. Connect your GitHub repository
2. Set environment variables in Railway dashboard
3. Railway will auto-deploy on commits

### DigitalOcean App Platform

1. Create `app.yaml`:
```yaml
name: mcp-perplexity-pro
services:
- name: server
  source_dir: /
  github:
    repo: your-username/mcp-perplexity-pro
    branch: main
  run_command: node dist/index.js
  environment_slug: node-js
  instance_count: 1
  instance_size_slug: basic-xxs
  envs:
  - key: NODE_ENV
    value: production
  - key: PERPLEXITY_API_KEY
    value: your-api-key
    type: SECRET
```

## Kubernetes Deployment

### 1. Create ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-perplexity-config
data:
  NODE_ENV: "production"
  DEFAULT_MODEL: "sonar-reasoning-pro"
  STORAGE_PATH: ".perplexity"
```

### 2. Create Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: mcp-perplexity-secret
type: Opaque
stringData:
  PERPLEXITY_API_KEY: "your-api-key"
```

### 3. Create Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-perplexity-pro
spec:
  replicas: 2
  selector:
    matchLabels:
      app: mcp-perplexity-pro
  template:
    metadata:
      labels:
        app: mcp-perplexity-pro
    spec:
      containers:
      - name: server
        image: mcp-perplexity-pro:latest
        ports:
        - containerPort: 3000
        envFrom:
        - configMapRef:
            name: mcp-perplexity-config
        - secretRef:
            name: mcp-perplexity-secret
        volumeMounts:
        - name: storage
          mountPath: /app/storage
      volumes:
      - name: storage
        persistentVolumeClaim:
          claimName: mcp-storage-pvc
```

## Monitoring and Logging

### Application Logs

```bash
# View logs in development
npm run dev

# View Docker logs
docker-compose logs -f

# View PM2 logs
pm2 logs mcp-perplexity-pro
```

### Health Checks

The server includes built-in health check endpoints:

```bash
# Basic health check
curl http://localhost:3000/health

# Detailed status
curl http://localhost:3000/status
```

### Monitoring Setup

1. **Prometheus + Grafana**: Use provided metrics endpoints
2. **New Relic**: Set `NEW_RELIC_LICENSE_KEY` environment variable
3. **DataDog**: Configure DataDog agent

## Security Considerations

### API Key Management

- Never commit API keys to repository
- Use environment variables or secure secret management
- Rotate API keys regularly
- Use different keys for different environments

### Network Security

- Run behind reverse proxy (nginx, Apache)
- Use HTTPS in production
- Implement rate limiting
- Use firewall rules to restrict access

### Container Security

- Run as non-root user (already configured)
- Use minimal base images
- Scan images for vulnerabilities
- Keep dependencies updated

## Troubleshooting

### Common Issues

1. **API Key Errors**
   - Verify API key is correctly set
   - Check Perplexity API quotas and limits

2. **Storage Permission Errors**
   - Ensure storage directory is writable
   - Check Docker volume mounts

3. **Memory Issues**
   - Monitor memory usage with `pm2 monit`
   - Adjust container memory limits
   - Consider horizontal scaling

### Debug Mode

Enable debug logging:

```bash
DEBUG=mcp-perplexity:* npm start
```

### Performance Optimization

1. **Caching**: Implement Redis for conversation caching
2. **Load Balancing**: Use nginx or cloud load balancer
3. **Database**: Consider PostgreSQL for larger deployments
4. **CDN**: Use CDN for static assets

## Backup and Recovery

### Data Backup

```bash
# Backup conversation data
tar -czf backup-$(date +%Y%m%d).tar.gz storage/

# Automated backup script
#!/bin/bash
BACKUP_DIR="/backups"
DATE=$(date +%Y%m%d_%H%M%S)
tar -czf "$BACKUP_DIR/mcp-perplexity-$DATE.tar.gz" storage/
find "$BACKUP_DIR" -name "mcp-perplexity-*.tar.gz" -mtime +30 -delete
```

### Disaster Recovery

1. Maintain backups in multiple locations
2. Document restoration procedures
3. Test recovery processes regularly
4. Use Infrastructure as Code (Terraform, CloudFormation)

## Scaling

### Horizontal Scaling

- Use load balancer
- Implement session affinity for chat continuity
- Consider shared storage (NFS, S3)

### Vertical Scaling

- Monitor CPU and memory usage
- Increase container resources as needed
- Optimize Node.js heap size

## Support

For deployment issues:
- Check GitHub Issues: https://github.com/cfdude/mcp-perplexity-pro/issues
- Review logs for error messages
- Ensure all prerequisites are met
- Verify configuration settings