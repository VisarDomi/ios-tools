#!/bin/sh
# Sets up https://ios-apps.veron3.space on Hetzner (see ../README.md, "Away installs"). Run from
# the PC. Idempotent: the Mac's publishing key, the site folder, the Caddy site and the login rule.
set -eu
src=$(cd "$(dirname "$0")" && pwd)
edge=erdal@157.90.28.14
receive=/usr/local/lib/ios-apps/receive

# The Mac publishes with its own key, which can only run the receiving script (./receive).
ssh mac 'test -f ~/.ssh/ios-apps_ed25519 || ssh-keygen -q -t ed25519 -N "" -C ios-apps-publish@mac -f ~/.ssh/ios-apps_ed25519'
key=$(ssh mac 'cat ~/.ssh/ios-apps_ed25519.pub')
printf 'command="%s",restrict %s\n' "$receive" "$key" | ssh "$edge" '
	set -e; f=~/.ssh/authorized_keys
	IFS= read -r line
	comment=${line##* }
	before=$(grep -vc " $comment\$" "$f" || true)
	grep -v " $comment\$" "$f" > "$f.new" || true
	printf "%s\n" "$line" >> "$f.new"
	# never replace the file unless every other key survived
	test "$(wc -l < "$f.new")" -eq $((before + 1)) || { rm -f "$f.new"; echo "authorized_keys check failed" >&2; exit 1; }
	chmod 600 "$f.new"; mv "$f.new" "$f"'
scp -q "$src/Caddyfile.snippet" "$edge:/tmp/ios-apps.Caddyfile"
scp -q "$src/receive" "$edge:/tmp/ios-apps.receive"
ssh "$edge" '
	set -e
	# erdal writes, Caddy reads, nobody else enters. New files take the folder'"'"'s group.
	sudo -n install -d -o erdal -g caddy -m 2750 /srv/ios-apps /srv/ios-apps/site
	sudo -n install -d -m 755 /usr/local/lib/ios-apps
	sudo -n install -m 755 /tmp/ios-apps.receive /usr/local/lib/ios-apps/receive; rm -f /tmp/ios-apps.receive
	c=/etc/caddy/Caddyfile
	if ! sudo -n grep -q "^ios-apps.veron3.space {" $c; then
		sudo -n cp -p $c /tmp/Caddyfile.before-ios-apps
		printf "\n" | sudo -n tee -a $c >/dev/null
		sudo -n tee -a $c < /tmp/ios-apps.Caddyfile >/dev/null
		if ! sudo -n caddy validate --config $c --adapter caddyfile >/dev/null 2>&1; then
			sudo -n cp /tmp/Caddyfile.before-ios-apps $c; sudo -n rm -f /tmp/Caddyfile.before-ios-apps
			echo "caddy validate failed; restored" >&2; exit 1
		fi
		sudo -n systemctl reload caddy
		sudo -n rm -f /tmp/Caddyfile.before-ios-apps  # the history is git -C /etc/caddy log
	fi
	rm -f /tmp/ios-apps.Caddyfile
	# Authelia lets every host through unless it has a rule: the page needs one.
	a=/etc/authelia/configuration.yml
	if ! sudo -n grep -q "domain: ios-apps.veron3.space" $a; then
		backup=/tmp/configuration.yml.before-ios-apps
		sudo -n cp -p $a $backup
		sudo -n python3 - $a <<"PY"
import sys
path = sys.argv[1]
text = open(path).read()
anchor = "    - domain: ops.veron3.space\n      policy: one_factor\n"
assert text.count(anchor) == 1, "expected the ops.veron3.space rule once"
open(path, "w").write(text.replace(anchor, anchor + "    - domain: ios-apps.veron3.space\n      policy: one_factor\n"))
PY
		if sudo -n -u authelia sh -c "set -a; . /etc/authelia/environment; /usr/local/bin/authelia validate-config --config $a" >/dev/null; then
			sudo -n systemctl restart authelia-native.service
			sudo -n rm -f $backup  # the history is git -C /etc/authelia log
		else
			sudo -n cp $backup $a; sudo -n rm -f $backup; echo "Authelia config invalid after adding the rule; restored" >&2; exit 1
		fi
	fi
	systemctl is-active caddy authelia-native.service | tr "\n" " "; echo'
