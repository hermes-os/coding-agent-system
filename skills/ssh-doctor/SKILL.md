---
name: ssh-doctor
description: "Diagnose SSH connection, authentication, server, network, and stale-session failures."
---

# SSH Doctor

Diagnose from the narrowest boundary outward. Inspect first and separate
client, network, server-listener, pre-authentication, authentication, and
session-start failures before changing configuration.

## Baseline

1. Record the client and server platform, target host, user, port, and exact
   failure without printing credentials.
2. Run a verbose non-interactive client probe with bounded timeout.
3. On the server, verify service state, listening sockets, effective SSH
   configuration, account eligibility, resource pressure, and recent service
   logs.
4. Test loopback. Loopback failure is server-side; loopback success with remote
   failure points to routing, firewall, address family, filtering, or bind
   scope.
5. Compare key selection, agent state, ownership/modes, and server
   authorization without printing private keys or secret values.

Prefer:

```bash
ssh -vv -o BatchMode=yes -o ConnectTimeout=10 \
  -o RequestTTY=no -o RemoteCommand=none user@host true
```

On Linux, inspect `systemctl status ssh` or `sshd`, `ss -lntp`, `sshd -T`,
`journalctl -u ssh` or `sshd`, and the applicable firewall. On macOS, inspect
Remote Login, `launchctl` state, listening sockets, the application firewall,
and unified SSH logs. Use commands supported by the detected host.

## Changes

- Report suspicious effective configuration before editing it.
- Validate configuration with `sshd -t` before reload.
- Prefer reload over restart when supported and preserve the current session.
- Do not terminate sessions until their ownership and activity are known.
- Never copy secret material or add persistent access unless explicitly in
  scope.
- Keep an independent recovery path before firewall, listener, or account
  changes on a remote-only host.

## Closeout

Report the failed boundary, root cause and confidence, changes made, fresh local
and remote proof, and whether another endpoint should retry.
