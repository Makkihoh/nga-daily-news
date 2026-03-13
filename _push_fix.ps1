$env:PATH = "C:\Program Files\Git\cmd;C:\Program Files\GitHub CLI;" + $env:PATH
Set-Location "c:\Users\locmai\WorkBuddy\Claw\nga-daily-news"
git status
git add -A
git commit -m "fix: use post content as summary instead of repeating title"
git push
gh workflow run update.yml --repo Makkihoh/nga-daily-news
