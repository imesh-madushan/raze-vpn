#!/usr/bin/env bash
set -u

umask 077
app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
log_dir="${XDG_STATE_HOME:-$HOME/.local/state}/raze-vpn/logs"
profile="$(python3 -c 'import sys;sys.path.insert(0,sys.argv[1]);import profiles;print(profiles.profile_path(profiles.selected()))' "$app_dir")"
mkdir -p "$log_dir" || exit 1
log_file="$(mktemp "$log_dir/connectivity-$(date +%Y%m%d-%H%M%S)-XXXXXX.log")" || exit 1
ln -sfn "$(basename "$log_file")" "$log_dir/latest.log"
exec > >(tee -a "$log_file") 2>&1
printf 'Started: %s\nLog: %s\n' "$(date -Is)" "$log_file"

printf '\nVPN configuration\n'
vpn_binary="$(python3 -c 'import sys;sys.path.insert(0,sys.argv[1]);import paths;print(paths.binary())' "$app_dir")"
if [[ -n "$vpn_binary" ]]; then "$vpn_binary" check -c "$profile"; else printf 'ERROR: sing-box is missing.\n'; fi
printf '\nManaged VPN service\n'
systemctl show raze-vpn.service -p ActiveState,MainPID,Description
printf '\nDirect sing-box processes\n'
pgrep -a -x sing-box || true
printf '\nTunnel interface\n'
ip -brief address show singtun0 2>&1 || true
printf '\nPolicy routing\n'
ip rule show
ip route show table all
printf '\nDNS lookup\n'
getent ahostsv4 chatgpt.com || true

probe() {
    local label="$1" url="$2"
    shift 2
    printf '\n%s: %s\n' "$label" "$url"
    curl --silent --show-error --output /dev/null \
        --connect-timeout 8 --max-time 20 \
        --write-out 'HTTP=%{http_code} remote=%{remote_ip} TLS_verify=%{ssl_verify_result} total=%{time_total}s\n' \
        "$@" "$url" || true
}

for url in https://example.com https://chatgpt.com https://api.openai.com/v1/models https://auth.openai.com; do
    probe 'System route IPv4' "$url" --noproxy '*' --ipv4
    probe 'System route IPv6' "$url" --noproxy '*' --ipv6
    probe 'Local SOCKS proxy' "$url" --noproxy '' --proxy socks5h://127.0.0.1:10808
done
printf '\nCodex endpoint reachability (no credentials; does not test a signed-in session)\n'
probe 'Codex system IPv4' https://chatgpt.com/backend-api/codex/responses --noproxy '*' --ipv4
probe 'Codex SOCKS' https://chatgpt.com/backend-api/codex/responses --noproxy '' --proxy socks5h://127.0.0.1:10808
printf '\nHTTP 401 from /v1/models is expected without credentials and confirms HTTP reachability.\n'
printf 'HTTP 403 shows a response was received, but access was refused.\n'
printf 'Forced IPv6 failures are expected while the IPv4-only VPN is running.\n'
printf 'HTTP 000 means the request failed before an HTTP response; see the curl error.\n'
printf '\nCompleted: %s\nSaved log: %s\n' "$(date -Is)" "$log_file"
