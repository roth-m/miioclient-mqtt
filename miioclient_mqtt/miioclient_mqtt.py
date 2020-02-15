#!/usr/bin/env python3

# (c)2019 RothM - MIIO Client MQTT Dispatcher
# Licensed under GPL v3
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.

import time
import socket
import json
import os
import sys
import yaml
from multiprocessing import Queue
import logging
import paho.mqtt.client as paho


def read_config():
    if len(sys.argv) < 2:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        configfile = script_dir + "/miioclient_mqtt.yaml"
    else:
        configfile = sys.argv[1]

    with open(configfile) as file:
        config = yaml.safe_load(file)
    return config


config = read_config()

# Constants
mqtt_prefix = config.get('mqtt', {}).get('prefix')
miio_len_max = 1480
miio_id = 0

queue = Queue(maxsize=100)

states = {
    'sound':
        config.get('initial_states', {}).get('sound', 2),
    'sound_volume':
        config.get('initial_states', {}).get('sound_volume', 50),
    'light_rgb':
        int(config.get('initial_states', {}).get('light_rgb', 'ffffff'), 16),
    'doorbell_volume':
        config.get('initial_states', {}).get('doorbell_volume', 25),
    'doorbell_sound':
        config.get('initial_states', {}).get('doorbell_sound', 11),
    'alarm_volume':
        config.get('initial_states', {}).get('alarm_volume', 90),
    'alarm_sound':
        config.get('initial_states', {}).get('alarm_sound', 2),
    'arming_time':
        config.get('initial_states', {}).get('arming_time', 30),
    'alarm_duration':
        config.get('initial_states', {}).get('alarm_duration', 1200),
    'brightness':
        config.get('initial_states', {}).get('brightness', 54),
}

ts_last_ping = 0
ts_last_pong = 0

logging.basicConfig(level='DEBUG', format='%(asctime)s - %(message)s',)


def miio_msg_encode(data):
    global miio_id
    if data.get("method") and data.get("method") == "internal.PING":
        msg = data
    else:
        if miio_id != 12345:
            miio_id = miio_id + 1
        else:
            miio_id = miio_id + 2
        if miio_id > 999999999:
            miio_id = 1
        msg = {"id": miio_id}
        msg.update(data)
    return (json.dumps(msg)).encode()


def miio_msg_decode(data):
    logging.debug(data.decode())
    if data[-1] == 0:
        data = data[:-1]
    res = [{""}]
    try:
        fixed_str = data.decode().replace('}{', '},{')
        res = json.loads("[" + fixed_str + "]")
    except:
        logging.warning("Bad JSON received")
    return res


def handle_miio_reply(topic, miio_msgs, state_update):
    global ts_last_pong
    while len(miio_msgs) > 0:
        miio_msg = miio_msgs.pop()
        if state_update is True and miio_msg.get("result"):
            result = miio_msg.get("result")[0].upper()
            logging.debug("Publish on " + mqtt_prefix + topic + "/state" +
                          " result:" + str(result))
            client.publish(mqtt_prefix + topic + "/state", result)   # publish
            if miio_msg.get("method") and \
                    miio_msg.get("method") == "internal.PONG":
                ts_last_pong = time.time()
                logging.debug("PONG: TS updated")
        else:
            handle_miio_msg(miio_msg)


def miio_msg_redispatch(topic, value):
    if topic == "rgb/":
        if int(value) > 0:
            logging.debug("Publish on " + mqtt_prefix + "light/state" +
                          " value: ON")
            client.publish(mqtt_prefix + "light/state", "ON")
        else:
            logging.debug("Publish on " + mqtt_prefix + "light/state" +
                          " value: OFF")
            client.publish(mqtt_prefix + "light/state", "OFF")


def miio_msg_params(topic, params):
    global states

    for key, value in params.items():
        if type(value) is not dict:
            if key == "rgb":
                states['brightness'], states['light_rgb'] = \
                    divmod(value, 0x1000000)
                states['light_rgb'] = \
                    states['light_rgb'] ^ states['brightness']
                logging.debug(
                    "Publish on " + mqtt_prefix + topic + key + "/state" +
                    " value:" + format(states['light_rgb'], 'x')
                )
                client.publish(
                    mqtt_prefix + topic + key + "/state",
                    format(states['light_rgb'], 'x').upper()
                )
                logging.debug(
                    "Publish on " + mqtt_prefix + topic + key +
                    "/brightness/state" + " value:" +
                    str(states['brightness'])
                )
                client.publish(
                    mqtt_prefix + topic + key + "/brightness/state",
                    str(states['brightness']).upper()
                )
            else:
                logging.debug("Publish on " + mqtt_prefix + topic + key +
                              "/state" + " value:" + str(value))
                client.publish(
                    mqtt_prefix + topic + key + "/state",
                    str(value).upper()
                )
        else:
            miio_msg_params(topic + key + "/", value)


def miio_msg_event(topic, event, params):
    value = event[6:]
    if value == "keepalive":
        return
    elif value == "motion":
        value = "on"
    elif value == "no_motion":
        value = "off"
    elif value == "alarm":
        topic = value + "/"
        value = params[0]
        if value == "all_off":
            value = "off"
    elif value == "close":
        value = "closed"
    value = value.upper()
    if len(params) > 0:
        client.publish(mqtt_prefix + topic + "params", str(params))
    logging.debug(
        "Publish on " + mqtt_prefix + topic + "state"+" value:" + str(value)
    )
    client.publish(mqtt_prefix + topic + "state", str(value))


def handle_miio_msg(miio_msg):
    method = miio_msg.get("method", None)
    topic = miio_msg.get("sid", "internal") + "/"
    params = miio_msg.get("params", None)
    if method is not None:
        if method == "props" and "model" in miio_msg:
            if params is not None:
                miio_msg_params(topic, params)
        elif method == "props":
            topic = "internal/"
            if params is not None:
                miio_msg_params(topic, params)
        elif method == "_otc.log":
            if params is not None:
                miio_msg_params(topic, params)
        if method.find("event.") != -1:
            miio_msg_event(topic, method, miio_msg.get("params"))


# Create a UDP socket at client side
UDPClientSocket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
UDPClientSocket.settimeout(1)
# Send a PING first
queue.put(["broker", {"method": "internal.PING"}, True])
ts_last_ping = time.time()
# Is Gateway armed?
queue.put(["alarm", {"method": "get_arming"}, True])
# Set time in seconds after which alarm is really armed
queue.put([
    "alarm/time_to_activate",
    {"method": "set_arming_time", "params": [states['arming_time']]},
    True
])
if (not config['silent_start']):
    # Set duration of alarm if triggered
    queue.put([
        "alarm/duration",
        {
            "method": "set_device_prop",
            "params": {
                "sid": "lumi.0",
                "alarm_time_len": states['alarm_duration']
            }
        },
        True
    ])
    queue.put([
        "sound/alarming/volume",
        {"method": "set_alarming_volume", "params": [states['alarm_volume']]},
        True
    ])
    queue.put([
        "sound/alarming/sound",
        {
            "method": "set_alarming_sound",
            "params": [0, str(states['alarm_sound'])]
        },
        True
    ])
    queue.put([
        "sound/doorbell/volume",
        {
            "method": "set_doorbell_volume",
            "params": [states['doorbell_volume']]
        },
        True
    ])
    queue.put([
        "sound/doorbell/sound",
        {
            "method": "set_doorbell_sound",
            "params": [1, str(states['doorbell_sound'])]
        },
        True
    ])
    # states[sound_volume, arming_time, alarm_duration] is missing
    # Turn OFF sound as previous commands will make the gateway play tones
    queue.put([
        "sound",
        {"method": "set_sound_playing", "params": ["off"]},
        False
    ])
# Set intensity + color
queue.put([
    "rgb",
    {
        "method": "set_rgb",
        "params": [(states['brightness'] << 24) + states['light_rgb']]
    },
    False
])


# MQTT callback
def on_message(client, userdata, message):
    global queue, states

    logging.debug(
        "received message =" + str(message.payload.decode("utf-8")) + " on: " +
        message.topic
    )
    item = message.topic[len(mqtt_prefix):]
    logging.debug("Item: " + item)
    command = str(message.payload.decode("utf-8"))
    if item == "heartbeat":
        queue.put(["alarm", {"method": "get_arming"}, True])
    if item == "alarm":
        if command.upper() == "ON":
            queue.put([
                "alarm",
                {"method": "set_arming", "params": ["on"]},
                False
            ])
        if command.upper() == "OFF":
            queue.put([
                "alarm",
                {"method": "set_arming", "params": ["off"]},
                False
            ])
    if item == "light":
        if command.upper() == "ON":
            queue.put([
                "light",
                {"method": "toggle_light", "params": ["on"]},
                False
            ])
        if command.upper() == "OFF":
            queue.put([
                "light",
                {"method": "toggle_light", "params": ["off"]},
                False
            ])
    if item == "brightness":
        states['brightness'] = int(command)
        miio_int = (states['brightness'] << 24) + states['light_rgb']
        queue.put(["rgb", {"method": "set_rgb", "params": [miio_int]}, False])
    if item == "rgb":
        states['light_rgb'] = int(command, 16)
        miio_int = (states['brightness'] << 24) + states['light_rgb']
        queue.put(["rgb", {"method": "set_rgb", "params": [miio_int]}, False])
    if item == "sound/volume":
        states['sound_volume'] = int(command)
        queue.put([
            "sound/volume",
            {
                "method": "set_gateway_volume",
                "params": [states['sound_volume']]
            },
            True
        ])
    if item == "sound":
        if command.upper() == "ON":
            queue.put([
                "sound",
                {
                    "method": "play_music_new",
                    "params": [str(states['sound']), states['sound_volume']]
                },
                False
            ])
        if command.upper() == "OFF":
            queue.put([
                "sound",
                {"method": "set_sound_playing", "params": ["off"]},
                False
            ])
    if item == "sound/sound":
        states['sound'] = int(command)
    if item == "sound/alarming/volume":
        states['alarm_volume'] = int(command)
        queue.put([
            "sound/alarming/volume",
            {
                "method": "set_alarming_volume",
                "params": [states['alarm_volume']]
            },
            True
        ])
    if item == "sound/alarming/sound":
        states['alarm_sound'] = int(command)
        queue.put([
            "sound/alarming/sound",
            {
                "method": "set_alarming_sound",
                "params": [0, str(states['alarm_sound'])]
            },
            True
        ])
    if item == "sound/doorbell/volume":
        states['doorbell_volume'] = int(command)
        queue.put([
            "sound/doorbell/volume",
            {
                "method": "set_doorbell_volume",
                "params": [states['alarm_volume']]
            },
            True
        ])
    if item == "sound/doorbell/sound":
        states['doorbell_sound'] = int(command)
        queue.put([
            "sound/doorbell/sound",
            {
                "method": "set_doorbell_sound",
                "params": [0, str(states['alarm_sound'])]
            },
            True
        ])


# Setup MQTT client
client = paho.Client("mqttmiio-001")
client.username_pw_set(
    config.get('mqtt', {}).get('username', ''),
    config.get('mqtt', {}).get('password', '')
)
# Assign callback
client.on_message = on_message

logging.debug("connecting to broker " + config['mqtt']['broker'])
client.connect(config['mqtt']['broker'])    # connect
# start loop to process received messages
client.loop_start()

# Subscribe to default MQTT topics for the gateway
client.subscribe(mqtt_prefix + "heartbeat")
client.subscribe(mqtt_prefix + "alarm")
client.subscribe(mqtt_prefix + "alarm/time_to_activate")
client.subscribe(mqtt_prefix + "alarm/duration")
client.subscribe(mqtt_prefix + "light")
client.subscribe(mqtt_prefix + "brightness")
client.subscribe(mqtt_prefix + "rgb")
client.subscribe(mqtt_prefix + "sound")
client.subscribe(mqtt_prefix + "sound/sound")
client.subscribe(mqtt_prefix + "sound/volume")
client.subscribe(mqtt_prefix + "sound/alarming/volume")
client.subscribe(mqtt_prefix + "sound/alarming/sound")
client.subscribe(mqtt_prefix + "sound/doorbell/volume")
client.subscribe(mqtt_prefix + "sound/doorbell/sound")

while True:
    while not queue.empty():
        # print("Something in the queue")
        # req : topic , miio_msg
        req = queue.get()
        logging.debug("Sending: " + str(miio_msg_encode(req[1])))
        UDPClientSocket.sendto(
            miio_msg_encode(req[1]),
            (config['miio']['broker'], config['miio']['port'])
        )
        UDPClientSocket.settimeout(2)
        try:
            # Wait for response
            handle_miio_reply(
                req[0],
                miio_msg_decode(UDPClientSocket.recvfrom(miio_len_max)[0]),
                req[2]
            )
        except socket.timeout:
            logging.warning("No reply!")
        UDPClientSocket.settimeout(1)
#    print("Waiting...")
    try:
        miio_msgs = miio_msg_decode(UDPClientSocket.recvfrom(miio_len_max)[0])
        while len(miio_msgs) > 0:
            miio_msg = miio_msgs.pop()
            handle_miio_msg(miio_msg)
    except socket.timeout:
        pass

    if (time.time() - ts_last_ping) > 200:
        queue.put(["internal", {"method": "internal.PING"}, True])
        ts_last_ping = time.time()
    if (time.time()-ts_last_pong) > 300:
        logging.debug("Publish on " + mqtt_prefix +
                      "internal/state result: OFFLINE")
        client.publish(mqtt_prefix + "internal/state", "OFFLINE")

# disconnect
client.disconnect()
# stop loop
client.loop_stop()
