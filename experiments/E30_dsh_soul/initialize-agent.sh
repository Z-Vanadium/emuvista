#!/bin/bash
set -euo pipefail
export DSH_HOME=/root/.dsh
profile="$DSH_HOME/profiles/e30"
pending="$DSH_HOME/.e30-initializing"
soul_rename="$DSH_HOME/.e30-soul-package-rename"
mkdir -p "$DSH_HOME"
exec 9>"$DSH_HOME/.e30-lock"
flock 9
if [[ ! -d "$profile" || -f "$pending" ]]; then
    touch "$pending"
    if [[ ! -d "$profile" ]]; then
        dsh --profile e30 --from-default-profile web --dump-config >/dev/null
    fi
    for package in cloud-bundle claw-bundle chat-client dsh-soul; do
        dsh plugin --profile e30 add "/opt/emuvista/agent-plugins/$package"
    done
    cp /opt/emuvista/e30.patch.yml "$profile/cordis.patch.yml"
    dsh --profile e30 --dump-config >/dev/null
    rm -f "$pending"
else
    has_package() {
        node -e 'const manifest = require(process.argv[1]); process.exit(Object.hasOwn(manifest.dependencies ?? {}, process.argv[2]) ? 0 : 1)' \
            "$profile/package.json" "$1"
    }
    if has_package @emuvista/dsh-soul; then
        touch "$soul_rename"
        dsh plugin --profile e30 remove @emuvista/dsh-soul
    fi
    if [[ -f "$soul_rename" ]] && ! has_package @emuvista/soul; then
        dsh plugin --profile e30 add /opt/emuvista/agent-plugins/dsh-soul
    fi
    dsh --profile e30 --dump-config >/dev/null
    if [[ -f "$soul_rename" ]]; then
        old_link="$profile/node_modules/@emuvista/dsh-soul"
        if [[ -L "$old_link" ]]; then
            rm "$old_link"
        fi
        rm "$soul_rename"
    fi
fi
