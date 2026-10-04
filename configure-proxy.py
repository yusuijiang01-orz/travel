#!/usr/bin/env python3
"""Safely add the managed family-trip path route to a matching host proxy vhost."""
import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MARKER = "# BEGIN managed family-travel /family-trip"
END = "# END managed family-travel /family-trip"


def fail(message):
    print(f"Proxy setup stopped: {message}", file=sys.stderr)
    print("Diagnosis: sudo bash /opt/family-travel/diagnose-vps.sh", file=sys.stderr)
    raise SystemExit(2)


def uncommented_text(text):
    """Blank comments and quoted string bodies while preserving offsets/braces."""
    chars = list(text)
    quote = None
    escaped = False
    comment = False
    for i, c in enumerate(chars):
        if comment:
            if c == "\n":
                comment = False
            else:
                chars[i] = " "
            continue
        if quote:
            chars[i] = " "
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == quote:
                quote = None
            continue
        if c in ('"', "'"):
            quote = c
            chars[i] = " "
        elif c == "#":
            comment = True
            chars[i] = " "
    return "".join(chars)


def matching_blocks(text, keyword):
    clean = uncommented_text(text)
    blocks = []
    for match in re.finditer(r"\b" + re.escape(keyword) + r"\s*\{", clean):
        opening = clean.find("{", match.start(), match.end())
        depth = 1
        for i in range(opening + 1, len(clean)):
            if clean[i] == "{":
                depth += 1
            elif clean[i] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append((match.start(), opening, i))
                    break
        else:
            fail(f"unclosed {keyword} block in proxy config")
    return clean, blocks


def nginx_target(domain):
    result = subprocess.run(["nginx", "-T"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        fail("nginx -T failed; existing Nginx configuration was not changed")
    config_files = []
    current = None
    for line in result.stdout.splitlines():
        marker = re.match(r"# configuration file (/.+):\s*$", line)
        if marker:
            current = Path(marker.group(1))
            if current not in config_files:
                config_files.append(current)
    found = []
    for listed_file in config_files:
        try:
            # nginx -T commonly reports sites-enabled symlinks. Edit the resolved
            # source file so atomic replacement never replaces the symlink itself.
            file = listed_file.resolve(strict=True)
            text = file.read_text()
        except (OSError, UnicodeError):
            continue
        clean, blocks = matching_blocks(text, "server")
        for start, opening, closing in blocks:
            body = clean[opening + 1:closing]
            names = re.findall(r"(?m)^\s*server_name\s+([^;]+);", body)
            listens = re.findall(r"(?m)^\s*listen\s+([^;]+);", body)
            if any(domain in n.split() for n in names) and any("ssl" in item.split() for item in listens):
                if MARKER in text[start:closing]:
                    found.append((file, text, closing, True))
                else:
                    # Do not shadow an existing route managed outside this installer.
                    if re.search(r"(?m)^\s*location\s+(?:=\s*)?\^?~?\s*/family-trip(?:/|\s|\{)", body):
                        fail(f"matching Nginx vhost already has a /family-trip location in {file}; review it manually")
                    found.append((file, text, closing, False))
    if len(found) != 1:
        fail(f"expected one host Nginx HTTPS vhost for {domain}, found {len(found)}; no proxy config was changed")
    return found[0]


def caddy_target(domain):
    service = subprocess.run(["systemctl", "show", "caddy", "-p", "ExecStart", "--value"],
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    exec_start = service.stdout.strip()
    config_match = re.search(r"(?:^|\s)--config(?:=|\s+)(\S+)", exec_start)
    config_name = config_match.group(1) if config_match else "/etc/caddy/Caddyfile"
    if config_name != "/etc/caddy/Caddyfile":
        fail(f"Caddy service uses {config_name}, not the supported /etc/caddy/Caddyfile")
    file = Path(config_name)
    if not file.is_file():
        fail("system Caddy service is active but /etc/caddy/Caddyfile is missing")
    text = file.read_text()
    clean = uncommented_text(text)
    # A Caddy site address is the token(s) immediately before a top-level opening brace.
    depth = 0
    starts = []
    for i, c in enumerate(clean):
        if c == "{":
            if depth == 0:
                line_start = clean.rfind("\n", 0, i) + 1
                header = clean[line_start:i].strip()
                if header and not header.startswith("#"):
                    starts.append((header, i))
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                fail("invalid Caddyfile braces")
    if depth:
        fail("unclosed block in Caddyfile")
    found = []
    for header, opening in starts:
        addresses = header.split()
        if domain in addresses:
            depth = 1
            closing = None
            for i in range(opening + 1, len(clean)):
                if clean[i] == "{": depth += 1
                elif clean[i] == "}":
                    depth -= 1
                    if depth == 0:
                        closing = i
                        break
            if closing is not None:
                site_body = clean[opening + 1:closing]
                if MARKER not in text[opening:closing] and re.search(r"(?m)\b(?:handle_path|handle|reverse_proxy|path)\b[^\n]*family-trip", site_body):
                    fail("matching Caddy site already defines a /family-trip route; review it manually")
                found.append((file, text, closing, MARKER in text[opening:closing]))
    if re.search(r"(?m)^\s*import\s+", clean):
        fail("Caddyfile uses imports; source ownership is ambiguous, so automatic edits are disabled")
    if len(found) != 1:
        fail(f"expected one direct Caddy site block for {domain}, found {len(found)}; no proxy config was changed")
    return found[0]


def save_with_backup(file, text):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = file.with_name(file.name + f".travel-backup-{stamp}")
    shutil.copy2(file, backup)
    temp = file.with_name(file.name + ".travel-tmp")
    temp.write_text(text)
    shutil.copystat(file, temp)
    os.replace(temp, file)
    return backup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("proxy", choices=("nginx", "caddy"))
    parser.add_argument("domain")
    parser.add_argument("port", type=int)
    parser.add_argument("path")
    args = parser.parse_args()
    file, original, closing, already = nginx_target(args.domain) if args.proxy == "nginx" else caddy_target(args.domain)
    if already:
        print(f"Managed /family-trip route already exists in {file}.")
        return
    if args.proxy == "nginx":
        snippet = Path("/etc/nginx/snippets/family-travel-path.conf")
        snippet.parent.mkdir(parents=True, exist_ok=True)
        snippet_text = (f"location = {args.path} {{ return 308 {args.path}/; }}\n"
                        f"location ^~ {args.path}/ {{\n"
                        f"    proxy_pass http://127.0.0.1:{args.port};\n"
                        "    proxy_http_version 1.1;\n"
                        "    proxy_set_header Host $host;\n"
                        "    proxy_set_header X-Real-IP $remote_addr;\n"
                        "    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
                        "    proxy_set_header X-Forwarded-Proto $scheme;\n"
                        "}\n")
        snippet_created = not snippet.exists()
        if snippet.exists() and snippet.read_text() != snippet_text:
            fail(f"managed snippet {snippet} exists with different content; refusing to overwrite")
        if snippet_created:
            snippet.write_text(snippet_text)
        addition = f"\n    {MARKER}\n    include {snippet};\n    {END}\n"
        updated = original[:closing] + addition + original[closing:]
        backup = save_with_backup(file, updated)
        test = subprocess.run(["nginx", "-t"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if test.returncode:
            shutil.copy2(backup, file)
            if snippet_created:
                snippet.unlink(missing_ok=True)
            fail(f"nginx -t rejected the change; original vhost restored from {backup}")
        reload_result = subprocess.run(["systemctl", "reload", "nginx"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if reload_result.returncode:
            shutil.copy2(backup, file)
            if snippet_created:
                snippet.unlink(missing_ok=True)
            subprocess.run(["nginx", "-t"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["systemctl", "reload", "nginx"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            fail(f"Nginx reload failed; original vhost restored from {backup}")
    else:
        snippet = Path("/etc/caddy/family-travel-path.caddy")
        snippet_text = (f"@family_trip path {args.path} {args.path}/*\n"
                        f"handle @family_trip {{\n    reverse_proxy 127.0.0.1:{args.port}\n}}\n")
        snippet_created = not snippet.exists()
        if snippet.exists() and snippet.read_text() != snippet_text:
            fail(f"managed snippet {snippet} exists with different content; refusing to overwrite")
        if snippet_created:
            snippet.write_text(snippet_text)
        addition = f"\n    {MARKER}\n    import {snippet}\n    {END}\n"
        updated = original[:closing] + addition + original[closing:]
        backup = save_with_backup(file, updated)
        test = subprocess.run(["caddy", "validate", "--config", str(file)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if test.returncode:
            shutil.copy2(backup, file)
            if snippet_created:
                snippet.unlink(missing_ok=True)
            fail(f"caddy validate rejected the change; original Caddyfile restored from {backup}")
        reload_result = subprocess.run(["systemctl", "reload", "caddy"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if reload_result.returncode:
            shutil.copy2(backup, file)
            if snippet_created:
                snippet.unlink(missing_ok=True)
            subprocess.run(["systemctl", "reload", "caddy"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            fail(f"Caddy reload failed; original Caddyfile restored from {backup}")
    print(f"Updated {args.proxy} HTTPS vhost {file}; backup: {backup}")


if __name__ == "__main__":
    main()
