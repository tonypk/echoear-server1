# CI/CD Setup Guide - HiTony Server

This guide sets up automatic deployment from GitHub to your GCE server.

## 🎯 How it works

```
Developer → GitHub Push → GitHub Actions → SSH Deploy → GCE Server → Restart Service
```

Every push to `main` branch automatically:
1. Pulls latest code on server
2. Updates Python dependencies
3. Restarts systemd service
4. Verifies service is running

## 🔐 Step 1: Add GitHub Secrets

Go to your GitHub repo settings and add these secrets:

**Repository**: https://github.com/tonypk/echoear-server1

Navigate to: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

### Add 3 secrets:

#### 1. `SERVER_HOST`
```
136.111.249.161
```

#### 2. `SERVER_USER`
```
tonypk25
```

#### 3. `SERVER_SSH_KEY`
Copy the ENTIRE private key (including BEGIN/END lines):
```
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACD6QiyFp+b+4ko4CNYQXGnEB/MRcLcmRPKc/FCztHLaeAAAAJhYS1FwWEtR
cAAAAAtzc2gtZWQyNTUxOQAAACD6QiyFp+b+4ko4CNYQXGnEB/MRcLcmRPKc/FCztHLaeA
AAAED8Pi4oSRR2GRxUA0n1D8p3TMoWmWsdwJ84rUygBpSKAPpCLIWn5v7iSjgI1hBcacQH
8xFwtyZE8pz8ULO0ctp4AAAAFWdpdGh1Yi1hY3Rpb25zLWRlcGxveQ==
-----END OPENSSH PRIVATE KEY-----
```

## 📦 Step 2: Push Workflow to GitHub

```bash
cd /Users/anna/Documents/xiaozhi/echoear-server/echoear-server1

# Add and commit the workflow
git add .github/workflows/deploy.yml CICD_SETUP.md
git commit -m "Add GitHub Actions CI/CD workflow

- Auto-deploy on push to main
- SSH deployment to GCE server
- Automatic service restart
- Health check verification
"

# Push to GitHub
git push origin main
```

## 🧪 Step 3: Test Deployment

After pushing, GitHub Actions will automatically run. You can:

1. **Watch live deployment**:
   - Go to https://github.com/tonypk/echoear-server1/actions
   - Click on the latest workflow run
   - Watch real-time logs

2. **Manual trigger** (optional):
   - Go to Actions tab
   - Select "Deploy to GCE Server"
   - Click "Run workflow"

## ✅ Verify Deployment

After successful deployment, check:

```bash
# SSH to server
ssh echoear-gce

# Check service status
sudo systemctl status echoear-server

# View recent logs
sudo journalctl -u echoear-server -n 50 --no-pager
```

## 🔄 Daily Workflow

From now on, your workflow is:

```bash
# 1. Make changes locally
cd /Users/anna/Documents/xiaozhi/echoear-server/echoear-server1
# ... edit files ...

# 2. Commit and push
git add .
git commit -m "Your change description"
git push

# 3. GitHub Actions automatically deploys!
# Watch it happen: https://github.com/tonypk/echoear-server1/actions
```

## 🚨 Troubleshooting

### Deployment fails with "Permission denied"
- Check that the deploy key is in server's `~/.ssh/authorized_keys`
- Verify GitHub secret `SERVER_SSH_KEY` has correct private key (with BEGIN/END lines)

### Service restart fails
- SSH to server manually and check: `sudo journalctl -u echoear-server -n 100`
- Verify service name matches: `echoear-server` (not `hitony-server` yet)

### Can't find directory
- Current server path: `~/echoear-server1` or `~tonypk25/echoear-server1`
- If you renamed the directory, update `.github/workflows/deploy.yml`

## 📚 Advanced: Deployment Environments

To add staging/production environments:

1. Create branches: `staging`, `production`
2. Duplicate workflow for each environment
3. Use different secrets: `STAGING_HOST`, `PROD_HOST`, etc.

## 🔒 Security Notes

- Deploy key has write access ONLY to server (not GitHub)
- Never commit private keys to Git
- Rotate deploy keys periodically
- Use GitHub Actions secrets (encrypted at rest)
