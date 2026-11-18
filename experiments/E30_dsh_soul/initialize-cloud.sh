#!/bin/bash
set -euo pipefail
occ() { runuser -u www-data -- php /var/www/html/occ "$@"; }
if ! occ config:system:get skeletondirectory >/dev/null 2>&1; then
    occ config:system:set skeletondirectory --value=""
fi
for resident in alice bob carol; do
    if ! occ user:info "$resident" >/dev/null 2>&1; then
        OC_PASS="${resident}-password" runuser -u www-data -- php /var/www/html/occ user:add --password-from-env "$resident"
    fi
done
