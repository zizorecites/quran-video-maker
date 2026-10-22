#!/bin/bash
# Quran Video Maker - put the app on GitHub, so anyone can download it.
#
# Double-click this file. The first time, it asks you to sign in to GitHub in
# your browser. After that, double-clicking it again sends any changes and
# builds a fresh Mac + Windows version.

cd "$(dirname "$0")" || exit 1
REPO="quran-video-maker"

say() { printf "\n\033[1;32m==>\033[0m %s\n" "$1"; }
stop() { printf "\n\033[1;31mStopped:\033[0m %s\n\n" "$1"; read -r -p "Press Return to close."; exit 1; }

echo ""
echo "  Quran Video Maker - publishing to GitHub"
echo "  ----------------------------------------"

# 1. git (comes with Apple's developer tools)
if ! git --version >/dev/null 2>&1; then
  stop "Git isn't installed. A box should have popped up asking to install the developer tools - press Install, wait for it to finish, then double-click this file again."
fi

# 2. the GitHub tool
if ! command -v gh >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    say "Installing the GitHub tool (one time only)"
    brew install gh || stop "Couldn't install the GitHub tool."
  elif [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
    brew install gh || stop "Couldn't install the GitHub tool."
  else
    stop "Homebrew isn't installed. Paste this into Terminal, press Return, then double-click this file again:
    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
  fi
fi

# 3. sign in (opens your browser the first time)
if ! gh auth status -h github.com >/dev/null 2>&1; then
  say "Signing in to GitHub - your browser will open"
  echo "  Copy the code it shows you, paste it in the browser, and approve."
  gh auth login --hostname github.com --git-protocol https --web --scopes workflow \
    || stop "Sign-in didn't finish. Double-click this file to try again."
fi
# building needs permission to run GitHub's build robots ("workflow")
if ! gh auth status -h github.com 2>&1 | grep -q "workflow"; then
  say "Asking GitHub for permission to run the builds"
  gh auth refresh -h github.com -s workflow || stop "Permission wasn't given."
fi
gh auth setup-git >/dev/null 2>&1

OWNER="$(gh api user --jq .login)" || stop "Couldn't read your GitHub name."
say "Signed in as $OWNER"

# 4. save this version
# GitHub's build steps live in build/workflows; they go where GitHub looks for them
mkdir -p .github/workflows
cp build/workflows/*.yml .github/workflows/
if [ ! -d .git ]; then
  git init -q -b main
fi
git config user.name >/dev/null 2>&1 || git config user.name "$OWNER"
git config user.email >/dev/null 2>&1 || git config user.email "$(gh api user --jq .id)+$OWNER@users.noreply.github.com"
git add -A
git commit -q -m "Quran Video Maker - $(date '+%Y-%m-%d %H:%M')" >/dev/null 2>&1 || true
git branch -M main

# 5. the project on GitHub (made the first time)
if ! gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  say "Making the project on GitHub: github.com/$OWNER/$REPO"
  gh repo create "$REPO" --public \
    --description "Turn a Quran recitation into a video with the mushaf text and English. By @zizorecites." \
    --homepage "https://$OWNER.github.io/$REPO/" >/dev/null || stop "Couldn't make the project on GitHub."
fi
git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$OWNER/$REPO.git"

# 6. turn on the download page
gh api -X POST "repos/$OWNER/$REPO/pages" -f build_type=workflow >/dev/null 2>&1 \
  || gh api -X PUT "repos/$OWNER/$REPO/pages" -f build_type=workflow >/dev/null 2>&1 || true

# 7. send it, and start the Mac + Windows builds
say "Sending the app to GitHub"
git push -q -u origin main || stop "Couldn't send it to GitHub."
gh api -X POST "repos/$OWNER/$REPO/pages" -f build_type=workflow >/dev/null 2>&1 || true

VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' qvm/paths.py)"
TAG="v${VERSION}-$(date +%Y%m%d-%H%M)"
git tag "$TAG" && git push -q origin "$TAG" || stop "Couldn't start the build."

PAGE="https://$OWNER.github.io/$REPO/"
say "Done! GitHub is now building the Mac and Windows versions (about 15-20 minutes)."
echo ""
echo "  Watch it build:   https://github.com/$OWNER/$REPO/actions"
echo "  Download page:    $PAGE"
echo ""
echo "  When both builds have a green tick, the download buttons on the page work."
echo "  Share the download page link with anyone."
echo ""
open "https://github.com/$OWNER/$REPO/actions" >/dev/null 2>&1
read -r -p "Press Return to close."
