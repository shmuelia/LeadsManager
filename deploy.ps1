Write-Host "========================================"
Write-Host "   Quick Deploy to GitHub"
Write-Host "========================================"
Write-Host ""

$message = if ($args[0]) { $args[0] } else { "Quick update" }
Write-Host "Deploying with message: $message"
Write-Host ""

Write-Host "[1/3] Adding files..."
git add .

Write-Host "[2/3] Committing..."
git commit -m $message

Write-Host "[3/3] Pushing to GitHub..."
git push origin main

Write-Host ""
Write-Host "========================================"
Write-Host "   Deploy Complete!"
Write-Host "========================================"
Write-Host ""
Write-Host "Remember to hard refresh (Ctrl+Shift+R)"
