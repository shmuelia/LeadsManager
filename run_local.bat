@echo off
echo Starting LeadsManager locally...

REM Set environment variables for local development
REM You need to replace these with your actual PostgreSQL credentials
set DATABASE_URL=postgresql://postgres:your_password@localhost:5432/leadsmanager_dev
set SECRET_KEY=your-local-secret-key-change-this

echo Environment variables set:
echo DATABASE_URL=%DATABASE_URL%
echo.

REM Check if database exists, if not run setup
python setup_database.py
if %errorlevel% neq 0 (
    echo Database setup failed. Please check your PostgreSQL connection.
    pause
    exit /b 1
)

echo.
echo Starting Flask application...
python app.py

pause
