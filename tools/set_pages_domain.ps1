# Bind (or unbind) the GitHub Pages custom domain for erikcywong/shinae.work.
#   pwsh -File tools/set_pages_domain.ps1 -Domain www.shinae.work -EnforceHttps
#   pwsh -File tools/set_pages_domain.ps1 -Domain ""            # unbind
param(
  [string]$Repo = "erikcywong/shinae.work",
  [Parameter(Mandatory = $true)][string]$Domain,
  [switch]$EnforceHttps
)
$ErrorActionPreference = "Stop"

if ($Domain -eq "") {
  Write-Host "unbinding custom domain..." -ForegroundColor Yellow
  gh api -X PUT "repos/$Repo/pages" -f cname="" | Out-Null
} else {
  Write-Host "binding $Domain ..." -ForegroundColor Cyan
  $out = gh api -X PUT "repos/$Repo/pages" -f "cname=$Domain" 2>&1
  if ($LASTEXITCODE -ne 0) {
    Write-Host "GitHub refused the domain:" -ForegroundColor Red
    Write-Host $out
    Write-Host ""
    Write-Host "If it says 'already taken', verify ownership with a TXT record first:" -ForegroundColor Yellow
    Write-Host "  _github-pages-challenge-<owner>.shinae.work = <token from Settings > Pages > Verify domain>"
    exit 1
  }
}

if ($EnforceHttps) {
  try {
    gh api -X PUT "repos/$Repo/pages" -F https_enforced=true | Out-Null
    Write-Host "HTTPS enforcement on (certificate may take a few minutes)" -ForegroundColor Green
  } catch {
    Write-Host "could not enforce HTTPS yet — wait for the certificate, then re-run with -EnforceHttps" -ForegroundColor Yellow
  }
}

gh api "repos/$Repo/pages" --jq '"cname=\(.cname // "none")  url=\(.html_url)  https_enforced=\(.https_enforced)  status=\(.status)"'
Write-Host ""
Write-Host "DNS to keep in mind:" -ForegroundColor Cyan
Write-Host "  CNAME  www  -> erikcywong.github.io"
Write-Host "  A      @    -> 185.199.108.153 185.199.109.153 185.199.110.153 185.199.111.153"
