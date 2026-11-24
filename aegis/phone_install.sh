#!/data/data/com.termux/files/usr/bin/bash
# phone_install.sh - first install of the Aegis bot in Termux on the S10 (deploy_phone.py --first puts it in Download).
exec > /sdcard/Download/aegis_install.log 2>&1
set -x
mkdir -p ~/aegis-re /sdcard/Download/aegis-logs /sdcard/Download/aegis-ctl
cd ~/aegis-re && tar xf /sdcard/Download/aegis_bundle.tar && rm -f /sdcard/Download/aegis_bundle.tar
[ -L logs ] || { rm -rf logs; ln -s /sdcard/Download/aegis-logs logs; }       # logs readable from the PC over adb
mkdir -p ~/.termux/boot
cp aegis/phone_boot.sh ~/.termux/boot/aegis.sh && chmod 700 ~/.termux/boot/aegis.sh
python -c "import sys; sys.path.insert(0, 'aegis'); import device; print('device', device.SERIAL, device.MODEL)"
echo AEGIS_INSTALL_DONE
