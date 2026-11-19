# Creates (or resets) a sign-in account from the console. Normally use Settings > Accounts instead.
#   .\scripts\add-user.ps1 abraham -Role admin
param(
    [Parameter(Mandatory)][string]$Name,
    [ValidateSet("admin", "hr", "viewer")][string]$Role = "hr",
    [string]$Nas = "192.168.5.18",
    [string]$User = "it-admin"
)
ssh -t "$User@$Nas" "cd /volume1/docker/attendance && sudo /usr/local/bin/docker compose exec att python -m app.manage adduser $Name --role $Role"
