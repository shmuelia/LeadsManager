@echo off
echo WARNING: This will DELETE ALL LEADS from the database!
echo.
echo Press Ctrl+C to cancel, or press any key to continue...
pause >nul

echo.
echo Clearing all leads...
curl -X POST https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/admin/clear-leads ^
  -H "Content-Type: application/json" ^
  -d "{\"confirm\":\"DELETE_ALL_LEADS\"}"

echo.
echo.
echo Leads cleared! Now you can re-import from Facebook with form data.
echo.
echo Next steps:
echo 1. Go to Facebook Business Manager
echo 2. Export all leads as CSV
echo 3. Or use Zapier to re-send all leads
echo.
pause