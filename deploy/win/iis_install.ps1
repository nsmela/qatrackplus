<#
.SYNOPSIS
    Configures IIS to serve a QATrack+ installation, following the official
    Windows deployment guide:
    https://docs.qatrackplus.com/en/stable/install/win.html  ("Setting up IIS")

.DESCRIPTION
    QATrack+ on Windows runs the Django app behind a CherryPy service (default
    port 8080). IIS is used for two jobs:
        1. Serve static / media files directly off disk.
        2. Reverse-proxy everything else to CherryPy.

    This script automates the manual GUI steps from the docs:
        * Enables the reverse-proxy setting in Application Request Routing (ARR).
        * Stops the Default Web Site.
        * Creates a "QATrack Static" site rooted at <InstallRoot>\qatrack on port 80.
        * Adds two URL Rewrite rules:
            - "QATrack Static"        : ^(static|media)/.*   -> action None, stop processing
            - "QATrack Reverse Proxy" : ^(.*)                -> http://localhost:<CherryPyPort>/{R:1}
              plus an HTTP_X_FORWARDED_HOST server variable.
        * Whitelists the HTTP_X_FORWARDED_HOST server variable for rewrite.

    The script is idempotent: re-running it replaces the rules rather than duplicating them.

.NOTES
    * Run from an ELEVATED PowerShell prompt (Administrator).
    * Requires IIS plus the URL Rewrite 2.1 and Application Request Routing 3.0 modules.
      Use -InstallPrereqs to download and install the two modules silently from Microsoft.
    * This configures IIS only. You still need: CherryPy service running on the chosen
      port, and USE_X_FORWARDED_HOST = True in qatrack/local_settings.py (per the docs).

.PARAMETER InstallRoot
    Root of the QATrack+ checkout. Default: C:\deploy\qatrackplus
    (static files are served from <InstallRoot>\qatrack).

.PARAMETER SiteName
    Name for the IIS site. Default: "QATrack Static".

.PARAMETER Port
    Port IIS listens on. Default: 80.

.PARAMETER CherryPyPort
    Port the QATrack+ CherryPy service listens on. Default: 8080.

.PARAMETER ServerName
    Value used for the HTTP_X_FORWARDED_HOST server variable (your public hostname,
    e.g. qatrack.myhospital.org). Defaults to the machine's hostname.

.PARAMETER StopDefaultSite
    Stop the IIS "Default Web Site". Default: $true.

.PARAMETER InstallPrereqs
    If set, downloads and silently installs URL Rewrite 2.1 and ARR 3.0 before configuring.

.EXAMPLE
    .\Configure-QATrackIIS.ps1 -ServerName qatrack.myhospital.org

.EXAMPLE
    .\Configure-QATrackIIS.ps1 -InstallRoot D:\qatrackplus -CherryPyPort 8090 -InstallPrereqs
#>

[CmdletBinding()]
param(
    [string] $InstallRoot   = 'C:\deploy\qatrackplus',
    [string] $SiteName      = 'QATrack Static',
    [int]    $Port          = 80,
    [int]    $CherryPyPort  = 8080,
    [string] $ServerName    = $env:COMPUTERNAME,
    [bool]   $StopDefaultSite = $true,
    [switch] $InstallPrereqs
)

$ErrorActionPreference = 'Stop'

# --- Direct download links for the prerequisite modules (x64) -----------------
$UrlRewriteMsi = 'https://download.microsoft.com/download/1/2/8/128E2E22-C1B9-44A4-BE2A-5859ED1D4592/rewrite_amd64_en-US.msi'
$ArrMsi        = 'https://download.microsoft.com/download/E/9/8/E9849D6A-020E-47E4-9FD0-A023E99B54EB/requestRouter_amd64.msi'

function Write-Step  { param($m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok    { param($m) Write-Host "    OK: $m" -ForegroundColor Green }
function Write-Warn2 { param($m) Write-Host "    WARNING: $m" -ForegroundColor Yellow }

# --- 0. Sanity checks ---------------------------------------------------------
function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p  = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'This script must be run from an elevated (Administrator) PowerShell prompt.'
    }
}

function Install-Msi {
    param([string]$Url, [string]$Name)
    $tmp = Join-Path $env:TEMP ([IO.Path]::GetFileName($Url))
    Write-Step "Downloading $Name"
    Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing
    Write-Step "Installing $Name (silent)"
    $p = Start-Process msiexec.exe -ArgumentList "/i `"$tmp`" /quiet /norestart" -Wait -PassThru
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
        throw "$Name install failed (msiexec exit code $($p.ExitCode))."
    }
    Write-Ok "$Name installed"
}

# --- Run ----------------------------------------------------------------------
Assert-Admin

$staticPath = Join-Path $InstallRoot 'qatrack'

Write-Step 'Importing WebAdministration module'
Import-Module WebAdministration -ErrorAction Stop
Write-Ok 'IIS PowerShell module loaded'

# Optionally install the prerequisite modules
if ($InstallPrereqs) {
    Install-Msi -Url $UrlRewriteMsi -Name 'URL Rewrite 2.1'
    Install-Msi -Url $ArrMsi        -Name 'Application Request Routing 3.0'
    Write-Warn2 'A new PowerShell session may be needed for newly installed modules to register.'
}

# Verify the static directory exists
if (-not (Test-Path $staticPath)) {
    Write-Warn2 "Static path '$staticPath' does not exist yet. The site will still be created, " +
                "but make sure your QATrack+ checkout lives at '$InstallRoot' and you have run " +
                "'python manage.py collectstatic'."
}

# --- 1. Enable the reverse-proxy setting in ARR -------------------------------
Write-Step 'Enabling reverse proxy in Application Request Routing'
try {
    Set-WebConfigurationProperty -PSPath 'MACHINE/WEBROOT/APPHOST' `
        -Filter 'system.webServer/proxy' -Name 'enabled' -Value 'True'
    Write-Ok 'ARR proxy enabled'
} catch {
    throw ("Could not enable the ARR proxy. Is Application Request Routing 3.0 installed? " +
           "Re-run with -InstallPrereqs to install it. Underlying error: $($_.Exception.Message)")
}

# --- 2. Stop the Default Web Site ---------------------------------------------
if ($StopDefaultSite) {
    Write-Step 'Stopping Default Web Site'
    if (Get-Website -Name 'Default Web Site' -ErrorAction SilentlyContinue) {
        Stop-Website -Name 'Default Web Site' -ErrorAction SilentlyContinue
        Write-Ok 'Default Web Site stopped'
    } else {
        Write-Warn2 'Default Web Site not found (already removed?) - skipping'
    }
}

# --- 3. Create the QATrack Static site ----------------------------------------
Write-Step "Creating/updating site '$SiteName' on port $Port -> $staticPath"
$existing = Get-Website -Name $SiteName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ItemProperty "IIS:\Sites\$SiteName" -Name physicalPath -Value $staticPath
    Write-Ok "Site '$SiteName' already existed - physical path updated"
} else {
    New-Website -Name $SiteName -PhysicalPath $staticPath -Port $Port -Force | Out-Null
    Write-Ok "Site '$SiteName' created"
}

# --- 4. URL Rewrite rules -----------------------------------------------------
$pspath        = "MACHINE/WEBROOT/APPHOST/$SiteName"
$rulesFilter   = 'system.webServer/rewrite/rules'
$allowedFilter = 'system.webServer/rewrite/allowedServerVariables'

function Remove-RuleIfPresent {
    param([string]$Name)
    try {
        Remove-WebConfigurationProperty -PSPath $pspath -Filter $rulesFilter `
            -Name '.' -AtElement @{name=$Name} -ErrorAction SilentlyContinue
    } catch { }
}

Write-Step 'Adding URL Rewrite rules (idempotent)'

# Clear any previous versions of our rules so re-runs do not duplicate them
Remove-RuleIfPresent -Name 'QATrack Static'
Remove-RuleIfPresent -Name 'QATrack Reverse Proxy'

# 4a. Static rule  -- must come FIRST so static/media bypass the proxy
Add-WebConfigurationProperty -PSPath $pspath -Filter $rulesFilter -Name '.' `
    -Value @{ name = 'QATrack Static'; stopProcessing = 'True' }
Set-WebConfigurationProperty -PSPath $pspath `
    -Filter "$rulesFilter/rule[@name='QATrack Static']/match" -Name 'url' -Value '^(static|media)/.*'
Set-WebConfigurationProperty -PSPath $pspath `
    -Filter "$rulesFilter/rule[@name='QATrack Static']/action" -Name 'type' -Value 'None'
Write-Ok "Rule 'QATrack Static'  : ^(static|media)/.*  -> None (stop processing)"

# 4b. Reverse-proxy rule -- catch-all forwarded to CherryPy
Add-WebConfigurationProperty -PSPath $pspath -Filter $rulesFilter -Name '.' `
    -Value @{ name = 'QATrack Reverse Proxy'; stopProcessing = 'True' }
Set-WebConfigurationProperty -PSPath $pspath `
    -Filter "$rulesFilter/rule[@name='QATrack Reverse Proxy']/match" -Name 'url' -Value '^(.*)'
Set-WebConfigurationProperty -PSPath $pspath `
    -Filter "$rulesFilter/rule[@name='QATrack Reverse Proxy']/action" -Name 'type' -Value 'Rewrite'
Set-WebConfigurationProperty -PSPath $pspath `
    -Filter "$rulesFilter/rule[@name='QATrack Reverse Proxy']/action" -Name 'url' `
    -Value "http://localhost:$CherryPyPort/{R:1}"
Write-Ok "Rule 'QATrack Reverse Proxy' : ^(.*)  -> http://localhost:$CherryPyPort/{R:1}"

# 4c. Server variable HTTP_X_FORWARDED_HOST on the proxy rule
Add-WebConfigurationProperty -PSPath $pspath `
    -Filter "$rulesFilter/rule[@name='QATrack Reverse Proxy']/serverVariables" -Name '.' `
    -Value @{ name = 'HTTP_X_FORWARDED_HOST'; value = $ServerName }
Write-Ok "Server variable HTTP_X_FORWARDED_HOST = $ServerName"

# 4d. Whitelist that server variable (ARR refuses to set it otherwise)
try {
    Remove-WebConfigurationProperty -PSPath $pspath -Filter $allowedFilter `
        -Name '.' -AtElement @{name='HTTP_X_FORWARDED_HOST'} -ErrorAction SilentlyContinue
} catch { }
Add-WebConfigurationProperty -PSPath $pspath -Filter $allowedFilter -Name '.' `
    -Value @{ name = 'HTTP_X_FORWARDED_HOST' }
Write-Ok 'HTTP_X_FORWARDED_HOST added to allowedServerVariables'

# --- 5. Start the site --------------------------------------------------------
Write-Step "Starting site '$SiteName'"
Start-Website -Name $SiteName -ErrorAction SilentlyContinue
Write-Ok 'Site started'

# --- 6. Verification ----------------------------------------------------------
Write-Step 'Verifying static file serving (the Linux penguin test from the docs)'
try {
    $url  = "http://localhost:$Port/static/qa/img/tux.png"
    $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
    if ($resp.StatusCode -eq 200) {
        Write-Ok "$url returned 200 - static serving works"
    } else {
        Write-Warn2 "$url returned status $($resp.StatusCode)"
    }
} catch {
    Write-Warn2 ("Could not fetch tux.png ($($_.Exception.Message)). " +
                 "Confirm 'collectstatic' has been run and the path '$staticPath\static' exists.")
}

Write-Host ''
Write-Step 'IIS configuration complete.'
Write-Host @"
Remaining steps (NOT handled by this script):
  1. Ensure the QATrack+ CherryPy Windows service is installed and running on port $CherryPyPort.
       (browse http://localhost:$CherryPyPort/ and confirm you see the plain login form)
  2. In qatrack\local_settings.py set:  USE_X_FORWARDED_HOST = True
  3. Set up the Django Q cluster (Task Scheduler) for background tasks.
Then browse to http://$ServerName/ to reach QATrack+.
"@ -ForegroundColor Gray
