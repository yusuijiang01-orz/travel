#!/usr/bin/env python3
"""Safely add the managed family-trip path route to a matching host proxy vhost."""
import argparse
import datetime
import hashlib
import ipaddress
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


def has_server_level_include(body):
    clean = uncommented_text(body)
    depth = 0
    for line in clean.splitlines():
        if depth == 0 and re.match(r"^\s*include\s+", line):
            return True
        depth += line.count("{") - line.count("}")
    return False


def has_server_level_redirect(body):
    clean = uncommented_text(body)
    depth = 0
    for line in clean.splitlines():
        if depth == 0 and re.match(r"^\s*(?:return|rewrite)\s+", line):
            return True
        depth += line.count("{") - line.count("}")
    return False


def nginx_inventory(domain):
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
            if any(domain in n.split() for n in names):
                found.append({"file": file, "text": text, "start": start, "opening": opening,
                              "closing": closing, "body": body, "names": names, "listens": listens})
    return found


def direct_ssl_paths(body):
    clean = uncommented_text(body)
    depth = 0
    paths = {"ssl_certificate": [], "ssl_certificate_key": []}
    for line in clean.splitlines():
        if depth == 0:
            for directive in paths:
                match = re.match(r"^\s*" + directive + r"\s+([^;]+);", line)
                if match:
                    paths[directive].append(match.group(1).strip())
        depth += line.count("{") - line.count("}")
    return paths


def certificate_is_valid(path, domain):
    if not path or not Path(path).is_absolute() or not Path(path).is_file():
        return False
    host_check = subprocess.run(["openssl", "x509", "-in", path, "-noout", "-checkhost", domain],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    expiry_check = subprocess.run(["openssl", "x509", "-in", path, "-noout", "-checkend", "0"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return host_check.returncode == 0 and expiry_check.returncode == 0


def nginx_target(domain):
    hosts = nginx_inventory(domain)
    secure = [host for host in hosts if any("ssl" in item.split() for item in host["listens"])]
    if len(secure) == 1:
        host = secure[0]
        names = [name for directive in host["names"] for name in directive.split()]
        if names != [domain]:
            fail(f"HTTPS vhost {host['file']} also serves other names; refusing to replace its certificate or alter the site")
        if MARKER not in host["text"][host["start"]:host["closing"]] and re.search(
                r"(?m)^\s*location\s+(?:=\s*)?\^?~?\s*/family-trip(?:/|\s|\{)", host["body"]):
            fail(f"matching Nginx vhost already has a /family-trip location in {host['file']}; review it manually")
        paths = direct_ssl_paths(host["body"])
        cert_paths = paths["ssl_certificate"]
        key_paths = paths["ssl_certificate_key"]
        cert_valid = len(cert_paths) == 1 and len(key_paths) == 1 and certificate_is_valid(cert_paths[0], domain)
        tls_action = False if cert_valid else "repair"
        if tls_action and (len(cert_paths) > 1 or len(key_paths) > 1 or has_server_level_include(host["body"])):
            fail(f"HTTPS vhost {host['file']} has indirect or ambiguous certificate directives; refusing to replace them")
        if tls_action:
            http_hosts = [candidate for candidate in hosts if not candidate["listens"] or any(
                args and (args[0] == "80" or args[0].endswith(":80")) for args in
                (item.split() for item in candidate["listens"]))]
            if len(http_hosts) != 1:
                fail(f"wrong/missing HTTPS certificate and expected one matching HTTP vhost for {domain}, found {len(http_hosts)}; no config was changed")
            http_names = [name for directive in http_hosts[0]["names"] for name in directive.split()]
            if http_names != [domain]:
                fail("HTTP challenge vhost also serves other names; refusing automatic certificate repair")
        return {"file": host["file"], "text": host["text"], "closing": host["closing"],
                "opening": host["opening"], "already": MARKER in host["text"][host["start"]:host["closing"]],
                "tls_action": tls_action, "listens": [], "ssl_paths": paths}
    if len(secure) > 1:
        fail(f"found {len(secure)} Nginx HTTPS vhosts for {domain}; no proxy config was changed")

    plain_http = []
    for host in hosts:
        listen_args = [item.split() for item in host["listens"]]
        has_http = not listen_args or any(args and (args[0] == "80" or args[0].endswith(":80")) for args in listen_args)
        if has_http and not any(args and "ssl" in args for args in listen_args):
            plain_http.append(host)
    if len(plain_http) != 1:
        fail(f"expected one Nginx vhost for {domain}; found {len(secure)} HTTPS and {len(plain_http)} HTTP candidates. DNS/port 80 and proxy config were not changed")
    host = plain_http[0]
    names = [name for directive in host["names"] for name in directive.split()]
    if names != [domain]:
        fail(f"HTTP vhost {host['file']} also serves other names; refusing to apply a single-domain certificate")
    if has_server_level_include(host["body"]):
        fail(f"HTTP vhost {host['file']} has server-level includes; refusing to guess which directives they add")
    if has_server_level_redirect(host["body"]):
        fail(f"HTTP vhost {host['file']} has a server-level redirect/rewrite that could affect the new HTTPS listener")
    if MARKER in host["text"][host["start"]:host["closing"]] or re.search(
            r"(?m)^\s*location\s+(?:=\s*)?\^?~?\s*/family-trip(?:/|\s|\{)", host["body"]):
        fail(f"HTTP vhost {host['file']} already contains a /family-trip route; review it manually before enabling TLS")
    listen_args = [item.split() for item in host["listens"]]
    for args in listen_args:
        if not args or not (args[0] == "80" or args[0].endswith(":80")) or "default_server" in args:
            fail(f"HTTP vhost {host['file']} has a nonstandard listen directive; refusing to alter other sites")
    return {"file": host["file"], "text": host["text"], "closing": host["closing"],
            "opening": host["opening"], "already": False, "tls_action": "enable",
            "listens": host["listens"], "ssl_paths": {"ssl_certificate": [], "ssl_certificate_key": []}}


def check_dns_and_http(domain):
    if not shutil.which("dig"):
        subprocess.run(["apt-get", "install", "-y", "--no-install-recommends", "dnsutils"], check=True)
    public_ip = subprocess.run(["curl", "-4", "--fail", "--silent", "--show-error", "--max-time", "15", "https://api.ipify.org"],
                               text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if public_ip.returncode or not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", public_ip.stdout.strip()):
        fail("cannot determine this VPS public IPv4; certificate was not requested")
    records = subprocess.run(["dig", "+short", "A", domain, "@1.1.1.1"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    addresses = [line.strip() for line in records.stdout.splitlines() if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", line.strip())]
    if not addresses or any(ipaddress.ip_address(address) != ipaddress.ip_address(public_ip.stdout.strip()) for address in addresses):
        fail(f"DNS A for {domain} must point only to this VPS ({public_ip.stdout.strip()}); got {', '.join(addresses) or 'no A record'}. Certificate was not requested")
    aaaa = subprocess.run(["dig", "+short", "AAAA", domain, "@1.1.1.1"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    v6_records = [line.strip() for line in aaaa.stdout.splitlines() if ":" in line]
    if v6_records:
        current_v6 = subprocess.run(["curl", "-6", "--fail", "--silent", "--show-error", "--max-time", "10", "https://api6.ipify.org"],
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if current_v6.returncode or any(ipaddress.ip_address(address) != ipaddress.ip_address(current_v6.stdout.strip()) for address in v6_records):
            fail(f"DNS AAAA for {domain} does not match a working public IPv6 on this VPS; correct/remove AAAA before requesting a certificate")
    listener = subprocess.run(["ss", "-H", "-ltn", "sport = :80"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if listener.returncode or not listener.stdout.strip():
        fail("no host listener is accepting TCP port 80; open provider/OS firewalls and rerun. Certificate was not requested")
    probe = subprocess.run(["curl", "-4", "--silent", "--show-error", "--connect-timeout", "5", "--max-time", "10",
                            "-o", os.devnull, "-w", "%{http_code}", f"http://{domain}/"],
                           text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if probe.returncode or probe.stdout.strip() == "000":
        fail(f"HTTP TCP 80 preflight to http://{domain}/ failed; verify provider firewall/routing before requesting a certificate")
    print(f"DNS and HTTP preflight passed: {domain} -> {public_ip.stdout.strip()}, TCP 80 responded HTTP {probe.stdout.strip()}.")


def find_existing_certificate(domain):
    live = Path("/etc/letsencrypt/live")
    if not live.is_dir() or not shutil.which("openssl"):
        return None
    for certificate in live.glob("*/fullchain.pem"):
        host_check = subprocess.run(["openssl", "x509", "-in", str(certificate), "-noout", "-checkhost", domain],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        expiry_check = subprocess.run(["openssl", "x509", "-in", str(certificate), "-noout", "-checkend", "0"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if host_check.returncode == 0 and expiry_check.returncode == 0:
            key = certificate.with_name("privkey.pem")
            if key.is_file():
                return certificate, key
    return None


def obtain_certificate(domain, vhost_file):
    certificate = find_existing_certificate(domain)
    if certificate:
        print(f"Using existing valid Let's Encrypt certificate: {certificate[0].parent}")
        return certificate
    named_certificate_dir = Path("/etc/letsencrypt/live") / domain
    if named_certificate_dir.exists():
        fail(f"an existing certificate directory for {domain} is invalid or expired; refusing to replace it automatically")
    email = os.environ.get("ACME_EMAIL", "").strip()
    if email and not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email):
        fail("ACME_EMAIL is not a valid address; certificate was not requested")
    subprocess.run(["apt-get", "install", "-y", "--no-install-recommends", "certbot", "python3-certbot-nginx"], check=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    before_backup = vhost_file.with_name(vhost_file.name + f".travel-before-certbot-{stamp}")
    shutil.copy2(vhost_file, before_backup)
    before = hashlib.sha256(vhost_file.read_bytes()).hexdigest()
    command = ["certbot", "certonly", "--nginx", "--non-interactive", "--agree-tos", "--no-eff-email",
               "--deploy-hook", "systemctl reload nginx", "--cert-name", domain, "-d", domain]
    if email:
        command.extend(["--email", email])
    else:
        print("No ACME_EMAIL is configured. Certbot will register without a contact email; certificate expiry notices will not be sent.", file=sys.stderr)
        command.append("--register-unsafely-without-email")
    print("Requesting a domain certificate with Certbot Nginx authenticator (HTTP-01 requires public TCP 80)...")
    result = subprocess.run(command)
    try:
        after = hashlib.sha256(vhost_file.read_bytes()).hexdigest()
    except OSError:
        after = ""
    if before != after:
        restore_backup(before_backup, vhost_file)
        test = subprocess.run(["nginx", "-t"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if test.returncode == 0:
            subprocess.run(["systemctl", "reload", "nginx"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        fail(f"Certbot changed the existing HTTP vhost during certonly; original restored from {before_backup}")
    before_backup.unlink(missing_ok=True)
    if result.returncode:
        fail("Certbot could not validate the domain. Check DNS A/AAAA, provider firewall TCP 80, and Nginx HTTP reachability")
    certificate = find_existing_certificate(domain)
    if not certificate:
        fail("Certbot completed but no valid certificate/key pair for this domain was found")
    return certificate


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


def restore_backup(backup, file):
    temp = file.with_name(file.name + ".travel-restore")
    shutil.copy2(backup, temp)
    os.replace(temp, file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("proxy", choices=("nginx", "caddy"))
    parser.add_argument("domain")
    parser.add_argument("port", type=int)
    parser.add_argument("path")
    args = parser.parse_args()
    tls_action = False
    listens = []
    if args.proxy == "nginx":
        target = nginx_target(args.domain)
        file, original, closing = target["file"], target["text"], target["closing"]
        already, tls_action, listens = target["already"], target["tls_action"], target["listens"]
        certificate = None
        if tls_action:
            check_dns_and_http(args.domain)
            if subprocess.run(["nginx", "-t"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
                fail("nginx -t failed before certificate request; no TLS configuration was changed")
            certificate = obtain_certificate(args.domain, file)
            # certonly does not create a TLS vhost. Re-read the same managed target before editing.
            target = nginx_target(args.domain)
            file, original, closing = target["file"], target["text"], target["closing"]
            already = target["already"]
            if target["tls_action"] != tls_action:
                fail("Nginx vhost changed during certificate issuance; refusing to inject the route")
    else:
        file, original, closing, already = caddy_target(args.domain)
    if already and not (args.proxy == "nginx" and tls_action == "repair"):
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
        tls_addition = ""
        if tls_action == "enable":
            tls_listeners = []
            for directive in (listens or ["80"]):
                endpoint = directive.split()[0]
                if endpoint == "80":
                    endpoint = "443"
                else:
                    endpoint = endpoint[:-2] + "443"
                line = f"    listen {endpoint} ssl;\n"
                if line not in tls_listeners:
                    tls_listeners.append(line)
            cert_file, key_file = certificate
            tls_addition = ("\n    # HTTPS listener added by family-travel deployment. HTTP remains unchanged.\n" +
                            "".join(tls_listeners) +
                            f"    ssl_certificate {cert_file};\n"
                            f"    ssl_certificate_key {key_file};\n")
        if tls_action == "repair":
            cert_file, key_file = certificate
            opening = target["opening"]
            body = original[opening + 1:closing]
            for directive, replacement in (("ssl_certificate", cert_file), ("ssl_certificate_key", key_file)):
                pattern = re.compile(r"(?m)^(\s*)" + directive + r"\s+[^;]+;")
                matches = list(pattern.finditer(uncommented_text(body)))
                if len(matches) > 1:
                    fail(f"multiple {directive} directives found in {file}; refusing to rewrite the vhost")
                if matches:
                    body = pattern.sub(lambda m: m.group(1) + directive + " " + replacement + ";", body, count=1)
                else:
                    body += f"\n    {directive} {replacement};\n"
            original = original[:opening + 1] + body + original[closing:]
            closing += len(body) - (closing - opening - 1)
        addition = "" if already else f"\n{tls_addition}    {MARKER}\n    include {snippet};\n    {END}\n"
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
