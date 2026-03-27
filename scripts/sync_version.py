#!/usr/bin/env python3
import re
from pathlib import Path

def main():
    version_file = Path("src/nexora_core/version.py")
    version_content = version_file.read_text(encoding="utf-8")
    
    match = re.search(r'NEXORA_VERSION\s*=\s*"([^"]+)"', version_content)
    if not match:
        raise ValueError("Could not find NEXORA_VERSION in version.py")
    
    version = match.group(1)
    
    manifest_file = Path("ynh-package/manifest.toml")
    manifest_content = manifest_file.read_text(encoding="utf-8")
    
    def replacer(m):
        old_val = m.group(1)
        if '~' in old_val:
            base, suffix = old_val.split('~', 1)
        else:
            suffix = 'ynh1'
        return f'version = "{version}~{suffix}"'

    new_content = re.sub(r'version\s*=\s*"([^"]+)"', replacer, manifest_content, count=1)
    
    if new_content != manifest_content:
        manifest_file.write_text(new_content, encoding="utf-8")
        print(f"Updated manifest.toml to version {version} (kept YunoHost suffix)")
    else:
        print(f"manifest.toml is already synchronously tracking version {version}")

if __name__ == "__main__":
    main()
