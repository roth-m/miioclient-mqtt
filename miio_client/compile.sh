#!/bin/bash
TOOLCHAIN_ROOTPATH="/opt/toolchains/gcc-arm-8.3-2019.03-x86_64-arm-linux-gnueabihf"

echo "Compiling"
$TOOLCHAIN_ROOTPATH/bin/arm-linux-gnueabihf-gcc   -std=c99 -Wall -pedantic -Wextra -fno-strict-aliasing -I$TOOLCHAIN_ROOTPATH/arm-linux-gnueabihf/include  -o miio_client.o -c miio_client.c
$TOOLCHAIN_ROOTPATH/bin/arm-linux-gnueabihf-gcc   -std=c99 -Wall -pedantic -Wextra -fno-strict-aliasing -I$TOOLCHAIN_ROOTPATH/arm-linux-gnueabihf/include  -o lib/cJSON/cJSON.o -c lib/cJSON/cJSON.c
echo "Linking"
$TOOLCHAIN_ROOTPATH/bin/arm-linux-gnueabihf-gcc  -std=c99 -Wall -pedantic -Wextra -fno-strict-aliasing -I$TOOLCHAIN_ROOTPATH/arm-linux-gnueabihf/include miio_client.o lib/cJSON/cJSON.o -o miio_client

if [ "$?" -eq "0" ]; then
	echo "Success";
fi;

