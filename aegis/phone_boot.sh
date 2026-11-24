#!/data/data/com.termux/files/usr/bin/sh
# Termux:Boot start script (copied to ~/.termux/boot/aegis.sh): keep the CPU awake, reach the phone's own adb, start the
# watchdog (it starts the bot). After a reboot adb-to-self only works once Wireless debugging / tcpip is back on.
termux-wake-lock
cd ~/aegis-re || exit 1
pkill -f aegis/watchdog.py
adb connect 127.0.0.1:5555 >> logs/boot.log 2>&1
nohup python aegis/watchdog.py >> logs/watchdog_out.log 2>&1 &
echo "$(date '+%F %T') boot script ran" >> logs/boot.log
