miio_client without encryption

	This is the client to run on the Xiaomi / Lumi gateway.
	The ARM binary is provided as is.

	It replaces the original miio_client binary which is in charge of communicating with the Xiaomi Cloud AND the local client (lumi gateway controller).

Steps:
	Just copy the binary to your gateway (DO NOT REPLACE the original miio_client as it is still needed to connect the gateway to WIFI)
	ie: scp miio_client root@xiaomigateway:/tmp/

	Launch (in the directory where you copied the file):

		killall miio_client && /tmp/miio_client

	Please note that there is a bash script running on the gateway to monitor miio_client. If it is not present, it will relaunch the original one.
	So, if you want to get back the Xiaomi Cloud, just issue:

		killall miio_client

	The orginal miio_client will be launched a few seconds later.



======

Compiling

	If you want to compile, you will need an ARM toolchain in order to cross compile the binary.
	see: https://releases.linaro.org/components/toolchain/binaries/latest-5/arm-linux-gnueabihf/ for Linaro ARM

	Edit compile.sh and change the variable TOOLCHAIN_ROOTPATH accordingly.

	Launch bash compile.sh in the miio_client directory.

	Copy the miio_client to the gateway.
	ie: scp miio_client root@xiaomi_gateway:/home/root/hack/
