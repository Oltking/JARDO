#!/usr/bin/env bash
# Create a persistent self-signed code-signing certificate for Jardo.
#
# Why: ad-hoc signing ("-") gives the app a NEW code identity on every build, so
# macOS treats each rebuild as a different app and wipes all Automation and
# Accessibility grants. A stable self-signed cert keeps ONE identity across
# rebuilds, so you grant those permissions once and they stick. Free, no Apple
# Developer account needed (the app is still not notarized — that needs a paid
# account — but permissions no longer reset).
#
# Run this ONCE per machine. It adds "Jardo Dev" to your login keychain. The
# build (tauri.conf.json signingIdentity) already points at "Jardo Dev".
set -euo pipefail

CERT_NAME="Jardo Dev"

# Note: we check without -v. A self-signed cert is "not trusted" so it never
# shows under "valid identities", but codesign can still sign with it, and TCC
# keys permissions on the cert identity either way — which is all we need.
if security find-identity -p codesigning | grep -q "$CERT_NAME"; then
  echo "==> '$CERT_NAME' code-signing identity already exists. Nothing to do."
  security find-identity -p codesigning | grep "$CERT_NAME"
  exit 0
fi

echo "==> Creating self-signed code-signing certificate '$CERT_NAME'"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Certificate config: a code-signing (extendedKeyUsage 1.3.6.1.5.5.7.3.3) leaf.
cat > "$TMP/cert.conf" <<EOF
[ req ]
distinguished_name = dn
x509_extensions = v3
prompt = no
[ dn ]
CN = $CERT_NAME
[ v3 ]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
EOF

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$TMP/key.pem" -out "$TMP/cert.pem" \
  -days 3650 -config "$TMP/cert.conf" >/dev/null 2>&1

KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
# Import the private key and cert as separate PEMs. PKCS#12 import is avoided
# because macOS `security` often can't verify the MAC that modern openssl writes.
# macOS pairs the key + cert into a code-signing identity by matching public keys.
# -T codesign lets codesign use the key without an interactive prompt each build.
security import "$TMP/key.pem" -k "$KEYCHAIN" \
  -T /usr/bin/codesign -T /usr/bin/security >/dev/null
security import "$TMP/cert.pem" -k "$KEYCHAIN" \
  -T /usr/bin/codesign -T /usr/bin/security >/dev/null

# Allow codesign to access the private key non-interactively.
security set-key-partition-list -S apple-tool:,apple:,codesign: \
  -k "" "$KEYCHAIN" >/dev/null 2>&1 || true

echo ""
echo "==> Done. Verifying:"
security find-identity -p codesigning | grep "$CERT_NAME" || {
  echo "    WARNING: certificate not found after import. Check Keychain Access."
  exit 1
}
echo ""
echo "Next: rebuild with ./scripts/build-macos-dmg.sh — it now signs with"
echo "'$CERT_NAME'. Grant Automation + Accessibility once; they persist from here."
