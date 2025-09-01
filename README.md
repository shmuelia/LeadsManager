# LeadsManager - Quick Setup

## Create New Heroku App (Recommended)

The current app seems to have cached deployment issues. Create a fresh app:

```bash
# Create new Heroku app
heroku create leadmanager-fresh-2024

# Add PostgreSQL
heroku addons:create heroku-postgresql:essential-0 --app leadmanager-fresh-2024

# Deploy
git remote add heroku-fresh https://git.heroku.com/leadmanager-fresh-2024.git
git push heroku-fresh main
```

## Current Status

- ✅ Minimal Flask app created (app.py)
- ✅ Clean requirements.txt (no SQLAlchemy)
- ❌ leadmanagement-dev appears to have cached deployment issues

## URLs

- **Current (broken)**: https://leadmanagement-dev-4c46df30a3b3.herokuapp.com
- **New app**: https://leadmanager-fresh-2024.herokuapp.com (after creation)

## Files Ready

- `app.py` - Minimal working Flask app
- `webhook_server.py` - Full PostgreSQL version (ready when new app works)
- `mobile_app/` - React Native mobile app
- All database schemas ready