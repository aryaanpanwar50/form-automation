#!/usr/bin/env bash
set -euo pipefail

app_path=${1:?Usage: create_macos_dmg.sh <FormAutomation.app> <output.dmg>}
output_path=${2:?Usage: create_macos_dmg.sh <FormAutomation.app> <output.dmg>}

if [[ ! -d "$app_path" ]]; then
  echo "Expected app bundle was not found: $app_path" >&2
  exit 1
fi

mkdir -p "$(dirname "$output_path")"
staging_directory=$(mktemp -d)
trap 'rm -rf "$staging_directory"' EXIT
cp -R "$app_path" "$staging_directory/FormAutomation.app"
ln -s /Applications "$staging_directory/Applications"
hdiutil create \
  -volname "Form Automation" \
  -srcfolder "$staging_directory" \
  -format UDZO \
  -ov \
  "$output_path"
