This is the firmware update to be processed by the gateway in order to gain a root access.

You DO NOT need this if you have access to the serial port of your gateway (soldering required here)


!!!! WARNING: THIS IS UNTESTED !!!!

You need to issue a "miIO.ota" command to the archive lummod_gw.bin .

First, get your MIIO device token.
see: https://github.com/jghaanstra/com.xiaomi-miio/blob/master/docs/obtain_token.md
(using the Mi Home app version 5.4.54 appears to be the easiest way)


Get a software to send miio commands:
see:
	https://github.com/rytilahti/python-miio
	https://github.com/aholstenson/miio


Put the lummod_gw.bin file on an HTTP server (or use the URL of GitHub for "lummod_gw.bin" ;) )

!!!! THEORY FOLLOWS !!!!!
!!!!    UNTESTED    !!!!!
Request an OTA update (using miio software + token) to be processed by the gateway and specify:
	url: http://<my_http_server>/lummod_gw.bin
	file_md5 : 525d3181fc3125eccb5e19540e8d771b

	miIO.ota '{"mode":"normal", "install":"1", "app_url":"#url#", "file_md5":"#file_md5#"}'

!!!! WARNING: THIS IS UNTESTED !!!!

If the package has been processed successfully, you should get:
	- an SSH shell (root/admin)
	- modified miio_client launched 10 mins after gateway start.

