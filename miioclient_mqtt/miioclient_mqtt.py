# (c)2019 RothM - MIIO Client MQTT Dispatcher
# Licensed under GPL v3
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.

import sys
import time
import socket
import json
from multiprocessing import Queue
import paho.mqtt.client as paho

# Constants
mqtt_username="MQTT_USERNAME"
mqtt_password="MQTT_PASSWORD"
mqtt_prefix="MQTT_PREFIX" # With a leading /
mqtt_broker="MQTT_BROKER_IP"
miio_broker="MIIO_GATEWAY_IP"
miio_port=54321
miio_len_max=1480
miio_id=0;

q = Queue(maxsize=100)


init_sound_volume=50
init_sound=2
init_light_rgb=int("ffffff",16) # Initial light color
init_doorbell_volume=25
init_doorbell_sound=11
init_alarming_volume=90
init_alarming_sound=2
init_arming_time=30
init_alarm_duration=1200
init_brightness=54
ts_last_ping=time.time()

def miio_msg_encode(data):
    global miio_id
    if data.get("method") and data.get("method")=="internal.PING":
        msg=data
    else:
        if miio_id != 12345:
            miio_id=miio_id+1
        else:
            miio_id=miio_id+2
        if miio_id > 999999999:
            miio_id=1
        msg = { "id":miio_id };
        msg.update(data);
    return((json.dumps(msg)).encode())


def miio_msg_decode(data):
    print(data.decode())
    if data[-1] == 0:
        data=data[:-1]
    res=[{""}]
    try:
        fixed_str = data.decode().replace('}{', '},{')
        res = json.loads("[" + fixed_str + "]")
    except:
        print("Bad JSON received")
    return res

def handle_miio_reply(topic, miio_msgs, state_update):
    while len(miio_msgs)>0:
        miio_msg=miio_msgs.pop()
        if state_update == True and miio_msg.get("result"):
            result=miio_msg.get("result")[0].upper()
            print("Publish on "+mqtt_prefix+topic+"/state"+" result:"+str(result))
            client.publish(mqtt_prefix+topic+"/state",result)#publish
            if miio_msg.get("method") and miio_msg.get("method")=="internal.PONG":
                ts_last_ping=time.time()
                print("PONG: TS updated")
        else:
            handle_miio_msg(miio_msg)


def miio_msg_redispatch(topic, value):
     if topic == "rgb/":
         if int(value)>0:
             print("Publish on "+mqtt_prefix+"light/state"+" value: ON")
             client.publish(mqtt_prefix+"light/state","ON")
         else:
             print("Publish on "+mqtt_prefix+"light/state"+" value: OFF")
             client.publish(mqtt_prefix+"light/state","OFF")



def miio_msg_params(topic,params):
    global init_sound_volume,init_sound,init_light_rgb,init_doorbell_volume,init_doorbell_sound,init_alarming_volume
    global init_alarming_sound,init_arming_time,init_alarm_duration,init_brightness
    
    for key, value in params.items():
        if type(value) is not dict:
            print("Publish on "+mqtt_prefix+topic+key+"/state"+" value:"+str(value))
            if key=="rgb":
                # response seem to be increased by 1, unless brightness set to 0
                init_brightness, init_light_rgb = divmod(value-1, 0x1000000)
                if init_brightness==0:
                    init_brightness, init_light_rgb = divmod(value, 0x1000000)
            client.publish(mqtt_prefix+topic+key+"/state",str(value).upper())
# Not needed            miio_msg_redispatch(topic+key+"/",value)
        else:
            miio_msg_params(topic+key+"/",value)

def miio_msg_event(topic,event,params):
        value=event[6:]
        parameter=None
        if value == "keepalive":
            return
        elif value == "motion":
            value="on"
        elif value == "no_motion":
            value="off"
        elif value == "alarm":
            topic=value+"/"
            value=params[0]
            if value=="all_off":
                value="off"
        elif value=="close":
            value="closed"
        value=value.upper()
        if len(params) > 0:
            client.publish(mqtt_prefix+topic+"params",str(params))
        print("Publish on "+mqtt_prefix+topic+"state"+" value:"+str(value))
        client.publish(mqtt_prefix+topic+"state",str(value))



def handle_miio_msg(miio_msg):
    topic=""
    if "method" in miio_msg:
        method=miio_msg.get("method")
        if "sid" in miio_msg:
            topic=miio_msg.get("sid")+"/"
        if method == "props" and "model" in miio_msg:
            if "params" in miio_msg:
                miio_msg_params(topic,miio_msg.get("params"))
        elif method == "props":
            topic="internal/"
            if "params" in miio_msg:
                miio_msg_params(topic,miio_msg.get("params"))
        if method.find("event.")!=-1:
            miio_msg_event(topic,miio_msg.get("method"),miio_msg.get("params"))



# Create a UDP socket at client side
UDPClientSocket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
UDPClientSocket.settimeout(0.10)
# Send a PING first
q.put([ "broker",{"method": "internal.PING"} , True])
# Is Gateway armed?
q.put([ "alarm",{"method": "get_arming"} , True])
# Set time in seconds after which alarm is really armed
q.put([ "alarm/time_to_activate",{"method": "set_arming_time", "params": [init_arming_time]} , True])
# Set duration of alarm if triggered
q.put([ "alarm/duration",{"method":"set_device_prop","params":{"sid":"lumi.0","alarm_time_len":init_alarm_duration}} , True])
q.put([ "sound/alarming/volume",{"method": "set_alarming_volume", "params": [init_alarming_volume]} , True])
q.put([ "sound/alarming/sound",{"method": "set_alarming_sound", "params": [0,str(init_alarming_sound)]} , True])
q.put([ "sound/doorbell/volume",{"method": "set_doorbell_volume", "params": [init_doorbell_volume]} , True])
q.put([ "sound/doorbell/sound",{"method": "set_doorbell_sound", "params": [1,str(init_doorbell_sound)]} , True])
# Turn OFF sound as previous commands will make the gateway play tones
q.put([ "sound",{ "method": "set_sound_playing", "params": ["off"] } , False ])
# Set (hardcoded) intensity + color
q.put([ "rgb",{ "method": "set_rgb", "params": [int("54"+init_light_rgb,16)] } , False ])


#MQTT callback
def on_message(client, userdata, message):
    global q
    global init_sound_volume, init_sound,init_light_rgb, init_doorbell_volume, init_doorbell_sound
    global init_alarming_volume, init_alarming_sound, init_arming_time, init_alarm_duration, init_brightness

    print("received message =",str(message.payload.decode("utf-8"))," on: ",message.topic)
    item=message.topic[len(mqtt_prefix):]
    print("Item: "+item)
    command=str(message.payload.decode("utf-8"))
    if item == "heartbeat":
        q.put([ "alarm",{"method": "get_arming"} , True])
    if item == "alarm":
        if command.upper() == "ON":
            q.put([ "alarm",{ "method": "set_arming", "params": ["on"] } , False])
        if command.upper() == "OFF":
            q.put([ "alarm",{ "method": "set_arming", "params": ["off"] } , False ])
    if item == "light":
        if command.upper() == "ON":
            q.put([ "light",{ "method": "toggle_light", "params": ["on"] } , False ])
        if command.upper() == "OFF":
            q.put([ "light",{ "method": "toggle_light", "params": ["off"] } , False])
    if item == "brightness":
        init_brightness=int(command)
        miio_int=(init_brightness << 24) + init_light_rgb
        q.put([ "rgb",{ "method": "set_rgb", "params": [miio_int] } , False ])
    if item == "rgb":
        init_light_rgb=int(command,16);
        miio_int=(init_brightness << 24) + init_light_rgb
        q.put([ "rgb",{ "method": "set_rgb", "params": [miio_int] } , False ])
    if item == "sound/volume":
        init_sound_volume=int(command)
        q.put([ "sound/volume",{"method": "set_gateway_volume", "params": [init_sound_volume]} , True])
    if item == "sound":
        if command.upper() == "ON":
            q.put([ "sound",{ "method": "play_music_new", "params": [ str(init_sound),init_sound_volume] } , False])
        if command.upper() == "OFF":
            q.put([ "sound",{ "method": "set_sound_playing", "params": ["off"] } , False ])
    if item == "sound/sound":
        init_sound=int(command)
    if item == "sound/alarming/volume":
        init_alarming_volume=int(command)
        q.put([ "sound/alarming/volume",{"method": "set_alarming_volume", "params": [init_alarming_volume]} , True])
    if item == "sound/alarming/sound":
        init_alarming_sound=int(command)
        q.put([ "sound/alarming/sound",{"method": "set_alarming_sound", "params": [0,str(init_alarming_sound)]} , True])
    if item == "sound/doorbell/volume":
        init_doorbell_volume=int(command)
        q.put([ "sound/doorbell/volume",{"method": "set_doorbell_volume", "params": [init_alarming_volume]} , True])
    if item == "sound/doorbell/sound":
        init_doorbell_sound=int(command)
        q.put([ "sound/doorbell/sound",{"method": "set_doorbell_sound", "params": [0,str(init_alarming_sound)]} , True])
        

# Setup MQTT client
client= paho.Client("mqttmiio-001")
client.username_pw_set(mqtt_username, mqtt_password)
# Assign callback
client.on_message=on_message

print("connecting to broker ",mqtt_broker)
client.connect(mqtt_broker)#connect
#start loop to process received messages
client.loop_start()

#Subscribe to default MQTT topics for the gateway
client.subscribe(mqtt_prefix+"heartbeat")
client.subscribe(mqtt_prefix+"alarm")
client.subscribe(mqtt_prefix+"alarm/time_to_activate")
client.subscribe(mqtt_prefix+"alarm/duration")
client.subscribe(mqtt_prefix+"light")
client.subscribe(mqtt_prefix+"brightness")
client.subscribe(mqtt_prefix+"rgb")
client.subscribe(mqtt_prefix+"sound")
client.subscribe(mqtt_prefix+"sound/sound")
client.subscribe(mqtt_prefix+"sound/volume")
client.subscribe(mqtt_prefix+"sound/alarming/volume")
client.subscribe(mqtt_prefix+"sound/alarming/sound")
client.subscribe(mqtt_prefix+"sound/doorbell/volume")
client.subscribe(mqtt_prefix+"sound/doorbell/sound")

count_idle_messages=0

while True:
    while not q.empty():
#        print("Something in the queue")
        # req : topic , miio_msg
        req=q.get();
        print("Sending: "+str(miio_msg_encode(req[1])))
        UDPClientSocket.sendto(miio_msg_encode(req[1]), (miio_broker,miio_port))
        UDPClientSocket.settimeout(2)
        try:
            # Wait for response
            handle_miio_reply(req[0],miio_msg_decode(UDPClientSocket.recvfrom(miio_len_max)[0]), req[2])
        except socket.timeout:
            print("No reply!")
        UDPClientSocket.settimeout(0.10)
#    print("Waiting...")
    try:
        miio_msgs=miio_msg_decode(UDPClientSocket.recvfrom(miio_len_max)[0])
        while len(miio_msgs)>0:
            miio_msg=miio_msgs.pop()
            handle_miio_msg(miio_msg)
    except socket.timeout:
        count_idle_messages=count_idle_messages+1
        pass

# Send PING  approx every 5 minutes
    if count_idle_messages>3000:
        count_idle_messages=0
        q.put([ "internal",{"method": "internal.PING"} , True])
        # 10 minutes without PONG
        if (time.time()-ts_last_ping) > 600:
            print("Publish on "+mqtt_prefix+"broker/state result: OFFLINE")
            client.publish(mqtt_prefix+"broker/state","OFFLINE")
        
#disconnect
client.disconnect()
#stop loop
client.loop_stop()

