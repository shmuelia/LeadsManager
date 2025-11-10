# Deployment Notes

## Always Use deploy.ps1 for Deployments

**Command:**
```powershell
powershell.exe -File deploy.ps1 "Your commit message here"
```

**What it does:**
1. Adds all changed files (`git add .`)
2. Commits with your custom message
3. Pushes to GitHub (`git push origin main`)
4. Pushes to Heroku (`git push heroku main`)
5. Opens the campaign manager page in browser
6. Reminds you to hard refresh (Ctrl+Shift+R)

**Why use it:**
- Keeps GitHub and Heroku in sync
- Automatically opens the app for testing
- Consistent deployment process
- Saves time

**From Bash:**
```bash
powershell.exe -File deploy.ps1 "commit message"
```

**From PowerShell:**
```powershell
./deploy.ps1 "commit message"
```
