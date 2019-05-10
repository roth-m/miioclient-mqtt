#! /bin/sh


cp /tmp/lumi_gateway_mi/* / -rf

# Setup root:admin
echo 'root:$6$e.LunWjb.3/Si5Jm$./43YbDLYZsR0MyoaMUKxI9gTy0ggsrSot.rnZOjJRDgQAXG5oQRe8QOwVrZ2bhSPxFg./S.y7TcH.MOt/2DI0:18018:0:99999:7:::' >/tmp/shadow
grep -v "root:" /etc/shadow >> /tmp/shadow

mv /tmp/shadow /etc/shadow
chmod ug+rw /etc/shadow


sed -e "s/\/home\/root\/fac\/fac_test/\/etc\/init.d\/dropbear start\n\/home\/root\/hack\/miio_replace.sh >\/dev\/null 2\>\&1 \&\n\/home\/root\/fac\/fac_test/g"  /etc/rc.local > /tmp/rc.local

mv /tmp/rc.local /etc/rc.local
chmod ugo+rwx /etc/rc.local

rm /update.sh


reboot

