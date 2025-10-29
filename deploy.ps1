Write-Host "========================================"
Write-Host "   Deploy to Heroku Dev"
Write-Host "========================================"
Write-Host ""

$message = if ($args[0]) { $args[0] } else { "Quick update" }
Write-Host "Deploying with message: $message"
Write-Host ""

Write-Host "[1/4] Adding files..."
git add .

Write-Host "[2/4] Committing..."
git commit -m $message

Write-Host "[3/4] Pushing to GitHub..."
git push origin main

Write-Host "[4/4] Deploying to Heroku..."
git push heroku main

Write-Host ""
Write-Host "========================================"
Write-Host "   Deploy Complete!"
Write-Host "========================================"
Write-Host ""
Write-Host "Opening application in browser..."
Start-Process "https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/"
Write-Host ""
Write-Host "Remember to hard refresh (Ctrl+Shift+R)"
