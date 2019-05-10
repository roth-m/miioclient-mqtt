#!/bin/ash
# Wait 10 minutes for original miio_client to make its own stuff
sleep 600
killall miio_client && /home/root/hack/miio_client >/dev/null 2>&1
