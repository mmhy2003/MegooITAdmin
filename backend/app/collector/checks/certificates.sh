# MegooITAdmin's certificate-expiry check (backend/app/collector/checks/certificates.sh), sent on stdin to `sh -s`. It
# reads the certificate the server serves on each usual TLS port of 127.0.0.1, sending $1 (the server's host name, when
# it has one) as SNI, and prints its subject, issuer, end date and SHA-256 fingerprint. No key is read. Read-only.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL
set -f
command -v openssl > /dev/null 2>&1 || { echo '{"status":"not_available"}'; exit 0; }
name=${1-}
if [ -n "$name" ]; then sni="-servername $name"; else sni=-noservername; fi
echo '{"status":"ok"}'
for port in 443 465 636 853 993 995 5671 6443 8443 8883 9443; do
  cert=$(timeout 5 openssl s_client -connect "127.0.0.1:$port" $sni < /dev/null 2> /dev/null \
    | openssl x509 -noout -subject -issuer -enddate -fingerprint -sha256 -nameopt RFC2253 2> /dev/null) || continue
  [ -n "$cert" ] || continue
  echo "port $port"
  printf '%s\n' "$cert"
done
